"""
DAG Visualizer — DAG 시각화 유틸리티

- to_tree_dict: DAG를 프론트엔드 트리 뷰용 계층형 dict로 변환
- to_summary: DAG 실행 통계 요약
- to_mermaid: graph.py의 to_mermaid() 위임 (일관된 진입점)
"""

from dag.graph import TaskDAG, TaskNode


def to_tree_dict(dag: TaskDAG) -> list[dict]:
    """DAG를 계층형 dict 리스트로 변환한다 (프론트엔드 트리 렌더링용).

    루트 노드(의존성 없는 노드)부터 시작하여 자식 방향으로 재귀 탐색.
    동일 노드가 여러 부모를 가지면 첫 번째 부모 아래에만 배치하고,
    이후 참조는 children에 포함하지 않는다 (트리 변환이므로).

    Returns:
        [
            {
                "id": "t1", "name": "분석", "worker_type": "analyst",
                "status": "completed", "cost_usd": 0.12,
                "duration_ms": 15000, "retries": 0,
                "children": [
                    {"id": "t2", ..., "children": [...]},
                ]
            },
        ]
    """
    if not dag.nodes:
        return []

    # 루트 = 의존성이 없는 노드
    roots = [n for n in dag.nodes.values() if not n.depends_on]

    # 자식 맵: parent_id → [child_nodes]
    children_map: dict[str, list[TaskNode]] = {}
    for node in dag.nodes.values():
        for dep in node.depends_on:
            children_map.setdefault(dep, []).append(node)

    # 중복 방지 (DAG → Tree 변환 시 한 노드가 여러 부모에 나타나지 않도록)
    visited: set[str] = set()

    def _build(node: TaskNode) -> dict:
        visited.add(node.id)
        children = [
            c for c in children_map.get(node.id, [])
            if c.id not in visited
        ]
        return {
            "id": node.id,
            "name": node.name,
            "worker_type": node.worker_type,
            "status": node.status,
            "cost_usd": node.cost_usd,
            "duration_ms": node.duration_ms,
            "retries": node.retries,
            "children": [
                _build(c) for c in sorted(children, key=lambda x: x.id)
            ],
        }

    return [_build(r) for r in sorted(roots, key=lambda x: x.id)]


def to_summary(dag: TaskDAG) -> dict:
    """DAG 실행 통계 요약을 반환한다.

    Returns:
        {
            "total": 8,
            "pending": 2, "running": 1, "completed": 4, "failed": 1,
            "total_cost_usd": 1.23,
            "total_duration_ms": 45000,
            "is_complete": False,
            "has_failures": True,
        }
    """
    nodes = list(dag.nodes.values())
    return {
        "total": len(nodes),
        "pending": sum(1 for n in nodes if n.status == "pending"),
        "running": sum(1 for n in nodes if n.status == "running"),
        "completed": sum(1 for n in nodes if n.status == "completed"),
        "failed": sum(1 for n in nodes if n.status == "failed"),
        "total_cost_usd": round(sum(n.cost_usd for n in nodes), 4),
        "total_duration_ms": sum(n.duration_ms for n in nodes),
        "is_complete": dag.is_complete(),
        "has_failures": dag.has_failures(),
    }


def to_mermaid(dag: TaskDAG) -> str:
    """DAG를 Mermaid 다이어그램 문법으로 변환한다.

    graph.py의 TaskDAG.to_mermaid()에 위임.
    """
    return dag.to_mermaid()
