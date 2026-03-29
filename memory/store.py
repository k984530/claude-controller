"""
Memory Store — 영구 지식 저장소
세션을 넘어 축적되는 지식을 관리한다: 결정, 패턴, 실패 원인, 코드베이스 맥락.

각 메모리는 JSON 파일로 저장되며, 키워드 기반 검색을 지원한다.
향후 임베딩 기반 유사도 검색으로 확장 가능한 인터페이스.
"""

import json
import os
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional


class MemoryType(str, Enum):
    DECISION = "decision"    # 아키텍처/설계 결정
    PATTERN = "pattern"      # 코드 패턴/관례
    FAILURE = "failure"      # 실패 원인 + 해결책
    CONTEXT = "context"      # 코드베이스 맥락


# 메모리 유형 → 서브디렉토리 매핑
_TYPE_DIR = {
    MemoryType.DECISION: "decisions",
    MemoryType.PATTERN: "patterns",
    MemoryType.FAILURE: "failures",
    MemoryType.CONTEXT: "context",
}


class MemoryStore:
    """영구 지식 CRUD + 검색."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        for sub in _TYPE_DIR.values():
            (self.base_dir / sub).mkdir(parents=True, exist_ok=True)

    def add(
        self,
        memory_type: MemoryType,
        title: str,
        content: str,
        tags: list[str],
        project: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> dict:
        """새 메모리를 추가한다.

        Args:
            memory_type: 메모리 유형
            title: 짧은 제목 ("JWT 대신 세션 방식 채택")
            content: 상세 내용
            tags: 검색용 태그 ["auth", "session", "security"]
            project: 프로젝트 스코프 (특정 프로젝트에만 유효)
            goal_id: 이 메모리를 생성한 목표 ID
        """
        mem_id = f"mem-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        memory = {
            "id": mem_id,
            "type": memory_type.value,
            "title": title,
            "content": content,
            "tags": tags,
            "project": project,
            "goal_id": goal_id,
            "created_at": time.time(),
            "accessed_at": time.time(),
            "access_count": 0,
        }
        self._save(memory)
        return memory

    def get(self, mem_id: str) -> Optional[dict]:
        """메모리를 조회하고 접근 기록을 갱신한다."""
        for sub in _TYPE_DIR.values():
            path = self.base_dir / sub / f"{mem_id}.json"
            if path.exists():
                with open(path) as f:
                    memory = json.load(f)
                memory["accessed_at"] = time.time()
                memory["access_count"] += 1
                self._save(memory)
                return memory
        return None

    def search(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[list[str]] = None,
        project: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """키워드 + 태그 기반 검색.

        검색 전략:
        1. query의 각 단어가 title, content, tags에 포함되는지 확인
        2. 매칭 점수 = 매칭된 필드 수 × 가중치
        3. 최근 접근, 높은 접근 횟수에 보너스
        """
        query_words = query.lower().split() if query else []
        results = []

        dirs = (
            [self.base_dir / _TYPE_DIR[memory_type]]
            if memory_type
            else [self.base_dir / d for d in _TYPE_DIR.values()]
        )

        for d in dirs:
            if not d.exists():
                continue
            for path in d.glob("mem-*.json"):
                with open(path) as f:
                    mem = json.load(f)

                # 프로젝트 필터
                if project and mem.get("project") and mem["project"] != project:
                    continue

                # 태그 필터
                if tags and not set(tags) & set(mem.get("tags", [])):
                    continue

                # 키워드 점수 계산
                score = self._score(mem, query_words)
                if score > 0 or not query_words:
                    results.append((score, mem))

        results.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in results[:limit]]

    def list_all(
        self,
        memory_type: Optional[MemoryType] = None,
        limit: int = 50,
    ) -> list[dict]:
        """모든 메모리를 최신순으로 반환한다."""
        memories = []
        dirs = (
            [self.base_dir / _TYPE_DIR[memory_type]]
            if memory_type
            else [self.base_dir / d for d in _TYPE_DIR.values()]
        )
        for d in dirs:
            if not d.exists():
                continue
            for path in d.glob("mem-*.json"):
                with open(path) as f:
                    memories.append(json.load(f))
        memories.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return memories[:limit]

    def update(self, mem_id: str, **kwargs) -> Optional[dict]:
        """메모리의 필드를 갱신한다."""
        mem = self.get(mem_id)
        if not mem:
            return None
        for key in ("title", "content", "tags", "project"):
            if key in kwargs:
                mem[key] = kwargs[key]
        self._save(mem)
        return mem

    def delete(self, mem_id: str) -> bool:
        """메모리를 삭제한다."""
        for sub in _TYPE_DIR.values():
            path = self.base_dir / sub / f"{mem_id}.json"
            if path.exists():
                path.unlink()
                return True
        return False

    def get_relevant(
        self, objective: str, project: Optional[str] = None, limit: int = 5
    ) -> list[dict]:
        """목표에 관련된 메모리를 반환한다. Planner가 계획 수립 시 참조."""
        return self.search(query=objective, project=project, limit=limit)

    def _score(self, mem: dict, query_words: list[str]) -> float:
        """메모리의 검색 점수를 계산한다."""
        if not query_words:
            return 0.0

        score = 0.0
        title_lower = mem.get("title", "").lower()
        content_lower = mem.get("content", "").lower()
        tags_lower = [t.lower() for t in mem.get("tags", [])]

        for word in query_words:
            if word in title_lower:
                score += 3.0
            if word in content_lower:
                score += 1.0
            if word in tags_lower:
                score += 2.0

        # 접근 빈도 보너스 (최대 +2)
        access_count = mem.get("access_count", 0)
        score += min(access_count * 0.1, 2.0)

        # 최신성 보너스 (7일 이내: +1)
        age_days = (time.time() - mem.get("created_at", 0)) / 86400
        if age_days < 7:
            score += 1.0

        return score

    def _save(self, memory: dict):
        """메모리를 파일에 원자적으로 저장한다."""
        sub = _TYPE_DIR.get(MemoryType(memory["type"]), "context")
        dir_path = self.base_dir / sub
        dir_path.mkdir(parents=True, exist_ok=True)
        path = dir_path / f"{memory['id']}.json"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)
        os.replace(str(tmp), str(path))
