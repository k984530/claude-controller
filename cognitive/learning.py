"""
Learning Module — 자기 개선 엔진
태스크 실행 결과를 분석하여 패턴을 추출하고,
향후 계획·실행의 품질을 개선한다.

학습 영역:
  1. 프롬프트 최적화: 성공/실패 패턴 → 프롬프트 템플릿 개선
  2. 시간/비용 추정: 과거 데이터 기반 정확도 향상
  3. Worker 선택: 태스크 유형별 최적 Worker 매핑
  4. 실패 패턴: 반복되는 실패 원인 축적 → 사전 회피
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from memory.store import MemoryStore, MemoryType


class LearningModule:
    """태스크 실행 결과를 분석하여 시스템을 개선한다."""

    def __init__(self, memory: MemoryStore, data_dir: str):
        self.memory = memory
        self.data_dir = Path(data_dir)
        self.outcomes_dir = self.data_dir / "outcomes"
        self.outcomes_dir.mkdir(parents=True, exist_ok=True)

    def record_outcome(
        self,
        goal_id: str,
        objective: str,
        achieved: bool,
        dag: dict,
        cost_usd: float,
        eval_report: dict,
    ):
        """목표 실행 결과를 기록한다."""
        outcome = {
            "goal_id": goal_id,
            "objective": objective,
            "achieved": achieved,
            "cost_usd": cost_usd,
            "task_count": len(dag.get("tasks", [])),
            "eval_report": eval_report,
            "timestamp": time.time(),
            "tasks_summary": self._summarize_tasks(dag),
        }

        # 결과 파일 저장
        path = self.outcomes_dir / f"{goal_id}.json"
        with open(path, "w") as f:
            json.dump(outcome, f, indent=2, ensure_ascii=False)

        # 실패 패턴 → Memory에 축적
        if not achieved:
            self._learn_from_failure(outcome)

        # 성공 패턴 → Memory에 축적
        if achieved:
            self._learn_from_success(outcome)

    def get_cost_estimate(self, task_count: int) -> dict:
        """과거 데이터 기반 비용/시간 추정."""
        outcomes = self._load_recent_outcomes(limit=50)
        if not outcomes:
            return {
                "estimated_cost_usd": task_count * 0.25,
                "confidence": "low",
                "basis": "기본 추정 (데이터 부족)",
            }

        # 태스크당 평균 비용 계산
        total_cost = sum(o["cost_usd"] for o in outcomes)
        total_tasks = sum(o["task_count"] for o in outcomes)

        if total_tasks == 0:
            cost_per_task = 0.25
        else:
            cost_per_task = total_cost / total_tasks

        return {
            "estimated_cost_usd": round(task_count * cost_per_task, 2),
            "cost_per_task": round(cost_per_task, 3),
            "confidence": "high" if len(outcomes) > 10 else "medium",
            "basis": f"최근 {len(outcomes)}개 목표의 평균",
        }

    def get_success_rate(self) -> dict:
        """전체 목표 성공률을 반환한다."""
        outcomes = self._load_recent_outcomes(limit=100)
        if not outcomes:
            return {"rate": 0.0, "total": 0, "achieved": 0}

        achieved = sum(1 for o in outcomes if o["achieved"])
        return {
            "rate": round(achieved / len(outcomes), 2),
            "total": len(outcomes),
            "achieved": achieved,
        }

    def get_failure_patterns(self, limit: int = 10) -> list[dict]:
        """최근 실패 패턴을 반환한다."""
        failures = self.memory.search(
            query="",
            memory_type=MemoryType.FAILURE,
            limit=limit,
        )
        return failures

    def _learn_from_failure(self, outcome: dict):
        """실패로부터 패턴을 추출하여 Memory에 저장한다."""
        failed_tasks = [
            t for t in outcome.get("tasks_summary", [])
            if t.get("status") == "failed"
        ]

        if not failed_tasks:
            return

        # 실패 태스크의 Worker 유형과 실패 원인 축적
        for task in failed_tasks:
            self.memory.add(
                memory_type=MemoryType.FAILURE,
                title=f"실패: {task.get('name', 'unknown')}",
                content=(
                    f"목표: {outcome['objective']}\n"
                    f"태스크: {task.get('name')}\n"
                    f"Worker: {task.get('worker_type')}\n"
                    f"재시도: {task.get('retries', 0)}회\n"
                    f"비용: ${task.get('cost_usd', 0)}"
                ),
                tags=[
                    task.get("worker_type", "unknown"),
                    "failure",
                    outcome["goal_id"],
                ],
                goal_id=outcome["goal_id"],
            )

    def _learn_from_success(self, outcome: dict):
        """성공으로부터 패턴을 추출한다."""
        # 효율적인 DAG 구조 기록 (비용이 평균 이하인 경우)
        avg_cost = self._get_avg_cost()
        if avg_cost > 0 and outcome["cost_usd"] < avg_cost * 0.7:
            self.memory.add(
                memory_type=MemoryType.PATTERN,
                title=f"효율적 패턴: {outcome['objective'][:50]}",
                content=(
                    f"목표: {outcome['objective']}\n"
                    f"태스크 수: {outcome['task_count']}\n"
                    f"비용: ${outcome['cost_usd']} (평균 ${avg_cost:.2f} 대비 절약)\n"
                    f"DAG 구조: {len(outcome.get('tasks_summary', []))} 태스크"
                ),
                tags=["efficient", "cost_saving", outcome["goal_id"]],
                goal_id=outcome["goal_id"],
            )

    def _summarize_tasks(self, dag: dict) -> list[dict]:
        """DAG의 태스크들을 요약한다."""
        return [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "worker_type": t.get("worker_type"),
                "status": t.get("status"),
                "cost_usd": t.get("cost_usd", 0),
                "retries": t.get("retries", 0),
            }
            for t in dag.get("tasks", [])
        ]

    def _load_recent_outcomes(self, limit: int = 50) -> list[dict]:
        """최근 실행 결과를 로드한다."""
        outcomes = []
        paths = sorted(self.outcomes_dir.glob("goal-*.json"), reverse=True)
        for path in paths[:limit]:
            with open(path) as f:
                outcomes.append(json.load(f))
        return outcomes

    def _get_avg_cost(self) -> float:
        """전체 평균 비용을 계산한다."""
        outcomes = self._load_recent_outcomes(limit=50)
        if not outcomes:
            return 0.0
        return sum(o["cost_usd"] for o in outcomes) / len(outcomes)
