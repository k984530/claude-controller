"""
Goal Engine — 목표 관리자
추상적 목표를 구조화하고, 진행 상태를 추적하며, 완료 조건을 판단한다.

사용 흐름:
  1. create_goal("테스트 커버리지 80%로 올려") → goal_id
  2. Planner가 DAG 생성 → attach_dag(goal_id, dag)
  3. Dispatcher가 실행 → update_task_status(goal_id, task_id, status)
  4. 모든 태스크 완료 → evaluate_completion(goal_id) → True/False
"""

import json
import os
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional


class GoalStatus(str, Enum):
    PENDING = "pending"          # 생성됨, 계획 미수립
    PLANNING = "planning"        # Planner가 DAG 생성 중
    READY = "ready"              # DAG 생성 완료, 실행 대기
    RUNNING = "running"          # 태스크 실행 중
    GATE_WAITING = "gate_waiting"  # Gate 모드: 사용자 승인 대기
    EVALUATING = "evaluating"    # Evaluator가 결과 검증 중
    COMPLETED = "completed"      # 목표 달성
    FAILED = "failed"            # 목표 달성 실패
    CANCELLED = "cancelled"      # 사용자가 취소


class ExecutionMode(str, Enum):
    FULL_AUTO = "full_auto"      # 완전 자율
    GATE = "gate"                # 단계별 승인
    WATCH = "watch"              # 자율 + 관찰/중단 가능
    PAIR = "pair"                # 태스크별 공동 리뷰


class GoalEngine:
    """목표 생성, 상태 추적, 완료 판단을 담당하는 엔진."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.goals_dir = self.data_dir / "goals"
        self.goals_dir.mkdir(parents=True, exist_ok=True)

    def create_goal(
        self,
        objective: str,
        mode: ExecutionMode = ExecutionMode.GATE,
        context: Optional[dict] = None,
        budget_usd: float = 5.0,
        max_tasks: int = 20,
    ) -> dict:
        """새 목표를 생성한다.

        Args:
            objective: 자연어 목표 ("테스트 커버리지를 80%로 올려")
            mode: 실행 모드
            context: 추가 맥락 (cwd, target_files 등)
            budget_usd: 비용 상한 (초과 시 자동 중단)
            max_tasks: 최대 태스크 수
        Returns:
            생성된 목표 dict
        """
        goal_id = f"goal-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        goal = {
            "id": goal_id,
            "objective": objective,
            "mode": mode.value,
            "status": GoalStatus.PENDING.value,
            "context": context or {},
            "budget_usd": budget_usd,
            "max_tasks": max_tasks,
            "success_criteria": [],      # Planner가 채움
            "dag": None,                 # Planner가 생성한 DAG
            "progress": {
                "total_tasks": 0,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "cost_usd": 0.0,
            },
            "memory_refs": [],           # 이 목표 실행 중 참조/생성된 메모리 ID
            "created_at": time.time(),
            "updated_at": time.time(),
            "completed_at": None,
        }
        self._save_goal(goal)
        return goal

    def get_goal(self, goal_id: str) -> Optional[dict]:
        """목표를 조회한다."""
        path = self.goals_dir / f"{goal_id}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def list_goals(self, status: Optional[str] = None) -> list[dict]:
        """목표 목록을 반환한다. status 필터 가능."""
        goals = []
        for path in sorted(self.goals_dir.glob("goal-*.json"), reverse=True):
            with open(path) as f:
                goal = json.load(f)
            if status is None or goal["status"] == status:
                goals.append(goal)
        return goals

    def update_status(self, goal_id: str, status: GoalStatus) -> dict:
        """목표 상태를 변경한다."""
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal not found: {goal_id}")
        goal["status"] = status.value
        goal["updated_at"] = time.time()
        if status in (GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.CANCELLED):
            goal["completed_at"] = time.time()
        self._save_goal(goal)
        return goal

    def attach_dag(self, goal_id: str, dag: dict, success_criteria: list[str]) -> dict:
        """Planner가 생성한 DAG와 성공 기준을 목표에 연결한다."""
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal not found: {goal_id}")
        goal["dag"] = dag
        goal["success_criteria"] = success_criteria
        goal["progress"]["total_tasks"] = len(dag.get("tasks", []))
        goal["status"] = GoalStatus.READY.value
        goal["updated_at"] = time.time()
        self._save_goal(goal)
        return goal

    def update_task_status(
        self, goal_id: str, task_id: str, status: str, cost_usd: float = 0.0
    ) -> dict:
        """DAG 내 개별 태스크의 상태를 갱신하고 진행률을 재계산한다."""
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal not found: {goal_id}")

        # DAG 내 태스크 상태 갱신
        if goal["dag"]:
            for task in goal["dag"].get("tasks", []):
                if task["id"] == task_id:
                    task["status"] = status
                    task["cost_usd"] = task.get("cost_usd", 0) + cost_usd
                    break

        # 진행률 재계산
        tasks = goal["dag"].get("tasks", []) if goal["dag"] else []
        goal["progress"]["completed_tasks"] = sum(
            1 for t in tasks if t.get("status") == "completed"
        )
        goal["progress"]["failed_tasks"] = sum(
            1 for t in tasks if t.get("status") == "failed"
        )
        goal["progress"]["cost_usd"] += cost_usd
        goal["updated_at"] = time.time()

        # 예산 초과 확인
        if goal["progress"]["cost_usd"] > goal["budget_usd"]:
            goal["status"] = GoalStatus.FAILED.value
            goal["completed_at"] = time.time()

        self._save_goal(goal)
        return goal

    def evaluate_completion(self, goal_id: str) -> dict:
        """목표 달성 여부를 판단한다.

        Returns:
            { "achieved": bool, "criteria_results": [...], "summary": str }
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal not found: {goal_id}")

        tasks = goal["dag"].get("tasks", []) if goal["dag"] else []
        all_done = all(t.get("status") == "completed" for t in tasks)
        any_failed = any(t.get("status") == "failed" for t in tasks)

        result = {
            "achieved": all_done and not any_failed,
            "all_tasks_done": all_done,
            "failed_tasks": [t["id"] for t in tasks if t.get("status") == "failed"],
            "total_cost_usd": goal["progress"]["cost_usd"],
            "criteria": goal["success_criteria"],
        }

        if result["achieved"]:
            self.update_status(goal_id, GoalStatus.COMPLETED)
        elif any_failed and not any(
            t.get("status") in ("pending", "running") for t in tasks
        ):
            self.update_status(goal_id, GoalStatus.FAILED)

        return result

    def get_next_tasks(self, goal_id: str) -> list[dict]:
        """DAG에서 현재 실행 가능한 태스크들을 반환한다 (의존성 충족된 것만)."""
        goal = self.get_goal(goal_id)
        if not goal or not goal["dag"]:
            return []

        tasks = goal["dag"].get("tasks", [])
        task_map = {t["id"]: t for t in tasks}
        ready = []

        for task in tasks:
            if task.get("status") not in (None, "pending"):
                continue
            deps = task.get("depends_on", [])
            if all(
                task_map.get(d, {}).get("status") == "completed" for d in deps
            ):
                ready.append(task)

        return ready

    def cancel_goal(self, goal_id: str) -> dict:
        """목표를 취소한다."""
        return self.update_status(goal_id, GoalStatus.CANCELLED)

    def _save_goal(self, goal: dict):
        """목표를 파일에 원자적으로 저장한다 (temp → rename)."""
        path = self.goals_dir / f"{goal['id']}.json"
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(goal, f, indent=2, ensure_ascii=False)
        os.replace(str(tmp_path), str(path))
