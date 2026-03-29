"""
DAG (Directed Acyclic Graph) — 태스크 의존성 그래프
Planner가 생성한 태스크들의 선행/후행 관계를 관리하고,
토폴로지 정렬 기반으로 실행 순서를 결정한다.
"""

from collections import defaultdict, deque
from typing import Optional


class TaskNode:
    """DAG 내 개별 태스크 노드."""

    __slots__ = (
        "id", "name", "worker_type", "prompt", "depends_on",
        "status", "cost_usd", "duration_ms", "result", "retries",
    )

    def __init__(
        self,
        task_id: str,
        name: str,
        worker_type: str,
        prompt: str,
        depends_on: Optional[list[str]] = None,
    ):
        self.id = task_id
        self.name = name
        self.worker_type = worker_type  # coder, reviewer, tester, analyst, writer
        self.prompt = prompt
        self.depends_on = depends_on or []
        self.status = "pending"         # pending, running, completed, failed
        self.cost_usd = 0.0
        self.duration_ms = 0
        self.result = None
        self.retries = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "worker_type": self.worker_type,
            "prompt": self.prompt,
            "depends_on": self.depends_on,
            "status": self.status,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "retries": self.retries,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskNode":
        node = cls(
            task_id=d["id"],
            name=d["name"],
            worker_type=d["worker_type"],
            prompt=d["prompt"],
            depends_on=d.get("depends_on", []),
        )
        node.status = d.get("status", "pending")
        node.cost_usd = d.get("cost_usd", 0.0)
        node.duration_ms = d.get("duration_ms", 0)
        node.retries = d.get("retries", 0)
        return node


class TaskDAG:
    """태스크 방향성 비순환 그래프.

    핵심 기능:
    - 토폴로지 정렬: 실행 순서 결정
    - 실행 가능 태스크: 의존성이 모두 완료된 태스크 반환
    - 병렬 그룹: 동시 실행 가능한 태스크 집합 반환
    - 순환 감지: DAG 유효성 검증
    """

    def __init__(self):
        self.nodes: dict[str, TaskNode] = {}
        self._adj: dict[str, list[str]] = defaultdict(list)    # 정방향 간선
        self._rev: dict[str, list[str]] = defaultdict(list)    # 역방향 간선

    def add_task(self, node: TaskNode):
        """태스크를 DAG에 추가한다."""
        self.nodes[node.id] = node
        for dep in node.depends_on:
            self._adj[dep].append(node.id)
            self._rev[node.id].append(dep)

    def validate(self) -> tuple[bool, str]:
        """DAG의 유효성을 검증한다 (순환 감지, 누락 의존성)."""
        # 누락된 의존성 확인
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    return False, f"Task '{node.id}' depends on unknown task '{dep}'"

        # 순환 감지 (Kahn's algorithm)
        in_degree = {nid: 0 for nid in self.nodes}
        for nid, node in self.nodes.items():
            for dep in node.depends_on:
                in_degree[nid] += 1  # 아닌, 이미 위에서 계산

        # 재계산
        in_degree = {nid: len(self._rev.get(nid, [])) for nid in self.nodes}
        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        visited = 0

        while queue:
            nid = queue.popleft()
            visited += 1
            for child in self._adj.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if visited != len(self.nodes):
            return False, "Cycle detected in task DAG"
        return True, "OK"

    def topological_sort(self) -> list[str]:
        """토폴로지 정렬 순서를 반환한다."""
        in_degree = {nid: len(self._rev.get(nid, [])) for nid in self.nodes}
        queue = deque(
            sorted(nid for nid, deg in in_degree.items() if deg == 0)
        )
        order = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for child in sorted(self._adj.get(nid, [])):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return order

    def get_ready_tasks(self) -> list[TaskNode]:
        """현재 실행 가능한 태스크들을 반환한다 (의존성 충족 + pending 상태)."""
        ready = []
        for node in self.nodes.values():
            if node.status != "pending":
                continue
            deps_met = all(
                self.nodes[d].status == "completed"
                for d in node.depends_on
                if d in self.nodes
            )
            if deps_met:
                ready.append(node)
        return ready

    def get_parallel_groups(self) -> list[list[str]]:
        """병렬 실행 가능한 태스크 그룹을 계층별로 반환한다.

        Returns:
            [[t1, t2], [t3, t4, t5], [t6]] — 같은 리스트 내 태스크는 동시 실행 가능
        """
        in_degree = {nid: len(self._rev.get(nid, [])) for nid in self.nodes}
        groups = []
        remaining = set(self.nodes.keys())

        while remaining:
            # in-degree가 0인 노드 = 현재 레벨에서 실행 가능
            level = [nid for nid in remaining if in_degree.get(nid, 0) == 0]
            if not level:
                break  # 순환이 있으면 중단 (validate에서 이미 검사)
            groups.append(sorted(level))
            for nid in level:
                remaining.discard(nid)
                for child in self._adj.get(nid, []):
                    in_degree[child] -= 1

        return groups

    def is_complete(self) -> bool:
        """모든 태스크가 완료되었는지 확인한다."""
        return all(n.status == "completed" for n in self.nodes.values())

    def has_failures(self) -> bool:
        """실패한 태스크가 있는지 확인한다."""
        return any(n.status == "failed" for n in self.nodes.values())

    def to_dict(self) -> dict:
        """DAG를 직렬화한다."""
        return {
            "tasks": [node.to_dict() for node in self.nodes.values()],
            "parallel_groups": self.get_parallel_groups(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskDAG":
        """직렬화된 DAG를 복원한다."""
        dag = cls()
        for td in data.get("tasks", []):
            dag.add_task(TaskNode.from_dict(td))
        return dag

    def to_mermaid(self) -> str:
        """DAG를 Mermaid 다이어그램 문법으로 변환한다 (UI 시각화용)."""
        lines = ["graph TD"]
        status_style = {
            "pending": ":::pending",
            "running": ":::running",
            "completed": ":::completed",
            "failed": ":::failed",
        }
        for node in self.nodes.values():
            label = f'{node.id}["{node.name}<br/>{node.worker_type}"]'
            style = status_style.get(node.status, "")
            lines.append(f"    {label}{style}")
        for node in self.nodes.values():
            for dep in node.depends_on:
                lines.append(f"    {dep} --> {node.id}")
        # 스타일 정의
        lines.extend([
            "    classDef pending fill:#e2e8f0,stroke:#94a3b8",
            "    classDef running fill:#bfdbfe,stroke:#3b82f6",
            "    classDef completed fill:#bbf7d0,stroke:#22c55e",
            "    classDef failed fill:#fecaca,stroke:#ef4444",
        ])
        return "\n".join(lines)
