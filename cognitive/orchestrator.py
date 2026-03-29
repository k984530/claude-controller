"""
Orchestrator — 인지 루프의 두뇌
Goal Engine, Planner, Dispatcher, Evaluator, Memory를 조율하여
목표를 자율적으로 달성하는 전체 라이프사이클을 관리한다.

인지 루프:
  Goal → Plan → Execute → Evaluate → [Learn] → Done/Retry
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from cognitive.goal_engine import GoalEngine, GoalStatus, ExecutionMode
from cognitive.planner import Planner
from cognitive.dispatcher import Dispatcher
from cognitive.evaluator import Evaluator
from cognitive.learning import LearningModule
from memory.store import MemoryStore, MemoryType
from dag.graph import TaskDAG

logger = logging.getLogger("orchestrator")


class Orchestrator:
    """인지 루프를 구동하는 최상위 조율기.

    사용법:
        orch = Orchestrator(base_dir="/path/to/controller")
        goal = orch.set_goal("API 응답 시간 50% 단축", cwd="/project")
        orch.run(goal["id"])  # 자율 실행
    """

    def __init__(self, base_dir: str, claude_bin: str = "claude"):
        self.base_dir = Path(base_dir)
        self.claude_bin = claude_bin

        # 핵심 컴포넌트 초기화
        self.goal_engine = GoalEngine(str(self.base_dir / "data"))
        self.memory = MemoryStore(str(self.base_dir / "memory"))
        self.planner = Planner(claude_bin)
        self.evaluator = None  # cwd 설정 후 초기화
        self.learning = LearningModule(
            memory=self.memory,
            data_dir=str(self.base_dir / "data" / "learning"),
        )

        self._dispatcher = None

    def set_goal(
        self,
        objective: str,
        cwd: str,
        mode: str = "gate",
        budget_usd: float = 5.0,
        max_tasks: int = 20,
    ) -> dict:
        """새 목표를 설정한다.

        Returns:
            생성된 목표 dict
        """
        exec_mode = ExecutionMode(mode)
        context = {"cwd": cwd}

        goal = self.goal_engine.create_goal(
            objective=objective,
            mode=exec_mode,
            context=context,
            budget_usd=budget_usd,
            max_tasks=max_tasks,
        )

        logger.info(f"Goal created: {goal['id']} — {objective}")
        return goal

    def plan(self, goal_id: str) -> dict:
        """목표에 대한 실행 계획(DAG)을 생성한다.

        Returns:
            DAG 정보가 포함된 업데이트된 목표 dict
        """
        goal = self.goal_engine.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        cwd = goal["context"].get("cwd", ".")
        self.goal_engine.update_status(goal_id, GoalStatus.PLANNING)

        # 관련 메모리 수집
        memories = self.memory.get_relevant(
            goal["objective"],
            project=cwd,
        )

        # Planner 호출
        dag, criteria = self.planner.create_plan(
            objective=goal["objective"],
            cwd=cwd,
            memory_context=memories,
            max_tasks=goal["max_tasks"],
        )

        # DAG를 Goal에 연결
        goal = self.goal_engine.attach_dag(
            goal_id,
            dag=dag.to_dict(),
            success_criteria=criteria,
        )

        logger.info(
            f"Plan created for {goal_id}: "
            f"{len(dag.nodes)} tasks, {len(criteria)} criteria"
        )
        return goal

    def execute(self, goal_id: str) -> dict:
        """계획된 DAG를 실행한다.

        Returns:
            실행 완료된 목표 dict
        """
        goal = self.goal_engine.get_goal(goal_id)
        if not goal or not goal["dag"]:
            raise ValueError(f"Goal not found or no plan: {goal_id}")

        cwd = goal["context"].get("cwd", ".")
        self.goal_engine.update_status(goal_id, GoalStatus.RUNNING)

        # Dispatcher 초기화
        dispatcher = Dispatcher(
            claude_bin=self.claude_bin,
            logs_dir=str(self.base_dir / "logs" / "goals"),
            prompts_dir=str(self.base_dir / "cognitive" / "prompts"),
            max_concurrent=5,
            on_task_complete=lambda tid, cost: self.goal_engine.update_task_status(
                goal_id, tid, "completed", cost
            ),
            on_task_fail=lambda tid, cost: self.goal_engine.update_task_status(
                goal_id, tid, "failed", cost
            ),
        )

        # DAG 실행
        dag = TaskDAG.from_dict(goal["dag"])
        completed_dag = dispatcher.run_dag(dag, cwd, goal_id)

        # DAG 상태를 Goal에 반영
        goal["dag"] = completed_dag.to_dict()
        goal["updated_at"] = time.time()
        self.goal_engine._save_goal(goal)

        logger.info(f"Execution completed for {goal_id}")
        return goal

    def evaluate(self, goal_id: str) -> dict:
        """실행 결과를 평가하고 목표 달성 여부를 판단한다.

        Returns:
            { "achieved": bool, "report": EvaluationReport, "goal": dict }
        """
        goal = self.goal_engine.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        cwd = goal["context"].get("cwd", ".")
        self.goal_engine.update_status(goal_id, GoalStatus.EVALUATING)

        evaluator = Evaluator(self.claude_bin, cwd)

        # 성공 기준 검증
        eval_report = evaluator.evaluate_goal(
            goal_id=goal_id,
            success_criteria=goal.get("success_criteria", []),
        )

        # 태스크 완료 상태 검증
        completion = self.goal_engine.evaluate_completion(goal_id)

        result = {
            "achieved": completion["achieved"] and eval_report.overall_pass,
            "report": eval_report.to_dict(),
            "completion": completion,
            "goal": self.goal_engine.get_goal(goal_id),
        }

        # 학습
        self.learning.record_outcome(
            goal_id=goal_id,
            objective=goal["objective"],
            achieved=result["achieved"],
            dag=goal["dag"],
            cost_usd=goal["progress"]["cost_usd"],
            eval_report=eval_report.to_dict(),
        )

        return result

    def run(self, goal_id: str) -> dict:
        """인지 루프 전체를 실행한다: Plan → Execute → Evaluate.

        Gate 모드에서는 각 단계 후 반환하여 사용자 승인을 기다린다.
        Full Auto 모드에서는 끝까지 자율 실행한다.

        Returns:
            최종 평가 결과
        """
        goal = self.goal_engine.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        mode = goal.get("mode", "gate")

        # Phase 1: Plan
        goal = self.plan(goal_id)

        if mode == ExecutionMode.GATE.value:
            self.goal_engine.update_status(goal_id, GoalStatus.GATE_WAITING)
            return {
                "phase": "plan_complete",
                "message": "계획이 생성되었습니다. 승인 후 실행을 시작합니다.",
                "goal": goal,
            }

        # Phase 2: Execute
        goal = self.execute(goal_id)

        if mode == ExecutionMode.GATE.value:
            self.goal_engine.update_status(goal_id, GoalStatus.GATE_WAITING)
            return {
                "phase": "execute_complete",
                "message": "실행이 완료되었습니다. 평가를 시작하려면 승인하세요.",
                "goal": goal,
            }

        # Phase 3: Evaluate
        result = self.evaluate(goal_id)

        return {
            "phase": "done",
            "message": "목표 달성" if result["achieved"] else "목표 미달성",
            **result,
        }

    def approve_gate(self, goal_id: str) -> dict:
        """Gate 모드에서 다음 단계를 승인한다."""
        goal = self.goal_engine.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        if goal["status"] != GoalStatus.GATE_WAITING.value:
            return {"error": "현재 승인 대기 상태가 아닙니다."}

        # 현재 단계 판단
        dag = goal.get("dag")
        if dag is None:
            # 계획이 아직 없음 → 오류
            return {"error": "계획이 없습니다. plan을 먼저 실행하세요."}

        tasks = dag.get("tasks", [])
        any_running = any(t.get("status") == "running" for t in tasks)
        all_done = all(t.get("status") in ("completed", "failed") for t in tasks)

        if not any_running and not all_done:
            # 계획 수립 완료 → 실행 단계로 진입
            return self.execute(goal_id)
        elif all_done:
            # 실행 완료 → 평가 단계로 진입
            return self.evaluate(goal_id)
        else:
            return {"error": "태스크가 아직 실행 중입니다."}

    def get_status(self, goal_id: str) -> dict:
        """목표의 현재 상태를 반환한다."""
        goal = self.goal_engine.get_goal(goal_id)
        if not goal:
            return {"error": "Goal not found"}

        dag_info = None
        if goal["dag"]:
            dag = TaskDAG.from_dict(goal["dag"])
            dag_info = {
                "total": len(dag.nodes),
                "completed": sum(1 for n in dag.nodes.values() if n.status == "completed"),
                "running": sum(1 for n in dag.nodes.values() if n.status == "running"),
                "failed": sum(1 for n in dag.nodes.values() if n.status == "failed"),
                "pending": sum(1 for n in dag.nodes.values() if n.status == "pending"),
                "mermaid": dag.to_mermaid(),
            }

        return {
            "goal": {
                "id": goal["id"],
                "objective": goal["objective"],
                "status": goal["status"],
                "mode": goal["mode"],
                "progress": goal["progress"],
                "created_at": goal["created_at"],
            },
            "dag": dag_info,
        }
