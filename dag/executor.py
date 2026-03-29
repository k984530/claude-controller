"""
DAG Executor — DAG 순회 기반 태스크 실행 엔진

핵심 기능:
- ready 노드 추출 → Worker 프롬프트 조립 → claude -p 디스패치
- 결과 수집 → 상태 갱신 → 다음 ready 노드 반복
- 동시성 제한 (max_concurrent)
- 실패 재시도 (max_retries=2, 프롬프트 변형)
- 비용 예산 체크 (budget_usd 초과 시 자동 중단)
- 메모리 컨텍스트를 Worker 프롬프트에 주입
"""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Callable

from dag.graph import TaskDAG, TaskNode
from dag.worker_utils import (
    parse_cost, parse_result as _parse_result_file,
    load_system_prompt, augment_retry_prompt, build_claude_cmd,
)

logger = logging.getLogger("dag.executor")


class BudgetExceeded(Exception):
    """비용 예산 초과 시 발생."""

    def __init__(self, spent: float, budget: float):
        self.spent = spent
        self.budget = budget
        super().__init__(f"Budget exceeded: ${spent:.2f} / ${budget:.2f}")


class _WorkerHandle:
    """실행 중인 Worker 프로세스 핸들."""

    __slots__ = ("task_id", "process", "output_file", "output_path", "started_at")

    def __init__(
        self,
        task_id: str,
        process: subprocess.Popen,
        output_file,
        output_path: str,
    ):
        self.task_id = task_id
        self.process = process
        self.output_file = output_file
        self.output_path = output_path
        self.started_at = time.time()


# Worker 도구 맵 → dag/worker_utils.py로 통합됨


class DAGExecutor:
    """DAG 기반 태스크 실행 엔진.

    Dispatcher(cognitive/dispatcher.py)의 핵심 루프를 계승하면서,
    예산 체크와 메모리 컨텍스트 주입을 추가한 상위 실행기.

    사용법:
        executor = DAGExecutor(claude_bin="claude", logs_dir="logs/goals")
        result_dag = executor.execute(
            dag, cwd="/project", goal_id="goal-123",
            budget_usd=5.0, memory_context=[...]
        )
    """

    MAX_RETRIES = 2
    POLL_INTERVAL = 2  # seconds

    def __init__(
        self,
        claude_bin: str = "claude",
        logs_dir: str = "logs/goals",
        prompts_dir: str = "cognitive/prompts",
        max_concurrent: int = 5,
        on_task_complete: Optional[Callable[[str, float], None]] = None,
        on_task_fail: Optional[Callable[[str, float], None]] = None,
    ):
        self.claude_bin = claude_bin
        self.logs_dir = Path(logs_dir)
        self.prompts_dir = Path(prompts_dir)
        self.max_concurrent = max_concurrent
        self.on_task_complete = on_task_complete
        self.on_task_fail = on_task_fail

        self._active: dict[str, _WorkerHandle] = {}
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────

    def execute(
        self,
        dag: TaskDAG,
        cwd: str,
        goal_id: str,
        budget_usd: float = 0.0,
        memory_context: Optional[list[dict]] = None,
    ) -> TaskDAG:
        """DAG 전체를 실행한다.

        Args:
            dag: 실행할 태스크 DAG
            cwd: 작업 디렉토리
            goal_id: 목표 ID (로그 구분용)
            budget_usd: 비용 상한 (0이면 무제한)
            memory_context: Worker 프롬프트에 주입할 메모리 컨텍스트

        Returns:
            실행 완료된 DAG (각 노드에 상태/비용/결과 포함)

        Raises:
            BudgetExceeded: 누적 비용이 budget_usd를 초과하면 발생
        """
        total_cost = 0.0
        memory_snippet = self._format_memory(memory_context)

        logger.info(
            f"DAG execution started: {goal_id} "
            f"({len(dag.nodes)} tasks, budget=${budget_usd:.2f})"
        )

        try:
            while not dag.is_complete() and not self._is_blocked(dag):
                # 1. 완료된 프로세스 수확
                total_cost += self._harvest(dag)

                # 2. 예산 체크
                if budget_usd > 0 and total_cost > budget_usd:
                    self._terminate_all()
                    raise BudgetExceeded(total_cost, budget_usd)

                # 3. 실행 가능한 태스크 디스패치
                ready = dag.get_ready_tasks()
                slots = self.max_concurrent - len(self._active)
                for task in ready[:slots]:
                    self._dispatch(task, cwd, goal_id, memory_snippet)

                # 4. 폴링 대기
                if self._active:
                    time.sleep(self.POLL_INTERVAL)

            # 마지막 수확
            total_cost += self._harvest(dag)

            if budget_usd > 0 and total_cost > budget_usd:
                raise BudgetExceeded(total_cost, budget_usd)

        except BudgetExceeded:
            logger.warning(f"Budget exceeded for {goal_id}: ${total_cost:.2f}")
            raise
        finally:
            self._terminate_all()

        status = "completed" if dag.is_complete() else "partial"
        logger.info(
            f"DAG execution {status}: {goal_id} (cost=${total_cost:.2f})"
        )
        return dag

    # ── Dispatch & Harvest ─────────────────────────────────────

    def _dispatch(
        self, task: TaskNode, cwd: str, goal_id: str, memory_snippet: str,
    ):
        """태스크를 claude -p 프로세스로 디스패치한다."""
        prompt = self._build_prompt(task, memory_snippet)
        output_path = str(self.logs_dir / f"{goal_id}_{task.id}.out")

        system_prompt = load_system_prompt(self.prompts_dir, task.worker_type)
        cmd = build_claude_cmd(
            self.claude_bin, prompt, task.worker_type, system_prompt,
        )

        out_file = open(output_path, "w")
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=out_file,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )

        task.status = "running"
        self._active[task.id] = _WorkerHandle(
            task.id, process, out_file, output_path,
        )
        logger.info(f"Dispatched {task.id} ({task.worker_type}): {task.name}")

    def _harvest(self, dag: TaskDAG) -> float:
        """완료된 프로세스를 수확하고 이번 수확분 비용 합계를 반환한다."""
        cost = 0.0
        done_ids = []

        for task_id, handle in self._active.items():
            ret = handle.process.poll()
            if ret is None:
                continue  # 아직 실행 중

            handle.output_file.close()
            node = dag.nodes[task_id]
            node.duration_ms = int((time.time() - handle.started_at) * 1000)

            task_cost = parse_cost(handle.output_path)
            node.cost_usd = task_cost
            cost += task_cost

            if ret == 0:
                node.status = "completed"
                node.result = _parse_result_file(handle.output_path)
                logger.info(f"Task {task_id} completed (${task_cost:.4f})")
                if self.on_task_complete:
                    self.on_task_complete(task_id, task_cost)
            else:
                node.retries += 1
                if node.retries <= self.MAX_RETRIES:
                    node.prompt = augment_retry_prompt(
                        node.prompt, node.retries, self.MAX_RETRIES,
                    )
                    node.status = "pending"
                    logger.info(
                        f"Task {task_id} failed, scheduling retry "
                        f"{node.retries}/{self.MAX_RETRIES}"
                    )
                else:
                    node.status = "failed"
                    logger.warning(f"Task {task_id} failed permanently")
                    if self.on_task_fail:
                        self.on_task_fail(task_id, task_cost)

            done_ids.append(task_id)

        for tid in done_ids:
            del self._active[tid]

        return cost

    def _is_blocked(self, dag: TaskDAG) -> bool:
        """모든 남은 태스크가 진행 불가한 상태인지 확인한다."""
        if self._active:
            return False
        return len(dag.get_ready_tasks()) == 0

    def _terminate_all(self):
        """모든 활성 프로세스를 종료한다."""
        for handle in self._active.values():
            try:
                handle.process.terminate()
                handle.output_file.close()
            except (OSError, ProcessLookupError):
                pass
        self._active.clear()

    # ── Prompt Building ────────────────────────────────────────

    def _build_prompt(self, task: TaskNode, memory_snippet: str) -> str:
        """태스크 프롬프트에 메모리 컨텍스트를 주입한다."""
        if not memory_snippet:
            return task.prompt
        return (
            f"## 참고 컨텍스트 (메모리)\n{memory_snippet}\n\n"
            f"## 태스크\n{task.prompt}"
        )

    def _format_memory(self, memory_context: Optional[list[dict]]) -> str:
        """메모리 컨텍스트를 Worker 주입용 텍스트로 변환한다."""
        if not memory_context:
            return ""
        lines = []
        for mem in memory_context[:10]:
            content = mem.get("content", "")
            mtype = mem.get("type", "unknown")
            lines.append(f"- [{mtype}] {content}")
        return "\n".join(lines)

    # parse_cost, parse_result, load_system_prompt
    # → dag/worker_utils.py로 추출됨 (공통 유틸리티)
