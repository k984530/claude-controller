"""
Dispatcher — DAG 기반 작업 배분기
DAG의 실행 순서에 따라 Worker를 배정하고, claude -p 프로세스를 관리한다.

핵심 정책:
- 의존성 충족된 태스크만 실행
- Worker 유형별 전문화된 시스템 프롬프트 주입
- 동시성 제한 준수
- 실패 태스크 자동 재시도 (최대 2회, 프롬프트 변형)
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Callable

from dag.graph import TaskDAG, TaskNode
from dag.worker_utils import (
    parse_cost, load_system_prompt,
    augment_retry_prompt, build_claude_cmd,
)


class WorkerProcess:
    """실행 중인 Worker 프로세스를 추적한다."""

    __slots__ = ("task_id", "process", "started_at", "output_path")

    def __init__(self, task_id: str, process: subprocess.Popen, output_path: str):
        self.task_id = task_id
        self.process = process
        self.started_at = time.time()
        self.output_path = output_path


class Dispatcher:
    """DAG 순서에 따라 태스크를 Worker에게 디스패치한다."""

    MAX_RETRIES = 2

    def __init__(
        self,
        claude_bin: str,
        logs_dir: str,
        prompts_dir: str,
        max_concurrent: int = 5,
        on_task_complete: Optional[Callable] = None,
        on_task_fail: Optional[Callable] = None,
    ):
        self.claude_bin = claude_bin
        self.logs_dir = Path(logs_dir)
        self.prompts_dir = Path(prompts_dir)
        self.max_concurrent = max_concurrent
        self.on_task_complete = on_task_complete
        self.on_task_fail = on_task_fail

        self._active: dict[str, WorkerProcess] = {}  # task_id → WorkerProcess
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def run_dag(self, dag: TaskDAG, cwd: str, goal_id: str) -> TaskDAG:
        """DAG 전체를 실행한다. 모든 태스크가 완료/실패할 때까지 루프.

        Args:
            dag: 실행할 태스크 DAG
            cwd: 작업 디렉토리
            goal_id: 목표 ID (로그 구분용)

        Returns:
            실행 완료된 DAG (각 태스크에 상태/결과 포함)
        """
        while not dag.is_complete() and not self._all_blocked(dag):
            # 1. 완료된 프로세스 수확
            self._harvest_completed(dag)

            # 2. 실행 가능한 태스크 디스패치
            ready = dag.get_ready_tasks()
            slots = self.max_concurrent - len(self._active)

            for task in ready[:slots]:
                self._dispatch_task(task, cwd, goal_id)

            # 3. 짧은 대기 (폴링 주기)
            if self._active:
                time.sleep(2)

        # 마지막 수확
        self._harvest_completed(dag)
        return dag

    def _dispatch_task(self, task: TaskNode, cwd: str, goal_id: str):
        """개별 태스크를 claude -p 프로세스로 실행한다."""
        system_prompt = load_system_prompt(self.prompts_dir, task.worker_type)
        output_path = str(self.logs_dir / f"{goal_id}_{task.id}.out")

        cmd = build_claude_cmd(
            self.claude_bin, task.prompt, task.worker_type, system_prompt,
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
        self._active[task.id] = WorkerProcess(task.id, process, output_path)

    def _harvest_completed(self, dag: TaskDAG):
        """완료된 프로세스를 확인하고 태스크 상태를 갱신한다."""
        done_ids = []
        for task_id, wp in self._active.items():
            ret = wp.process.poll()
            if ret is None:
                continue  # 아직 실행 중

            node = dag.nodes[task_id]
            duration_ms = int((time.time() - wp.started_at) * 1000)
            node.duration_ms = duration_ms

            # 결과 파싱
            cost = parse_cost(wp.output_path)
            node.cost_usd = cost

            if ret == 0:
                node.status = "completed"
                if self.on_task_complete:
                    self.on_task_complete(task_id, cost)
            else:
                node.retries += 1
                if node.retries <= self.MAX_RETRIES:
                    # 재시도: 프롬프트 앞에 실패 맥락 추가
                    node.prompt = augment_retry_prompt(
                        node.prompt, node.retries, self.MAX_RETRIES
                    )
                    node.status = "pending"
                else:
                    node.status = "failed"
                    if self.on_task_fail:
                        self.on_task_fail(task_id, cost)

            done_ids.append(task_id)

        for tid in done_ids:
            del self._active[tid]

    def _all_blocked(self, dag: TaskDAG) -> bool:
        """모든 남은 태스크가 실행 불가능한 상태인지 확인한다."""
        if self._active:
            return False  # 아직 실행 중인 것이 있음
        ready = dag.get_ready_tasks()
        return len(ready) == 0

