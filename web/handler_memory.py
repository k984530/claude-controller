"""
Memory 관련 HTTP 핸들러 Mixin

포함 엔드포인트:
  - GET    /api/memory              # 메모리 검색 (query, type, tags, project 파라미터)
  - GET    /api/memory/:id          # 메모리 상세
  - POST   /api/memory              # 메모리 추가
  - PUT    /api/memory/:id/update   # 메모리 수정 (POST로 처리)
  - DELETE /api/memory/:id          # 메모리 삭제
"""

import sys
from urllib.parse import parse_qs

from config import CONTROLLER_DIR, DATA_DIR

# memory 패키지를 import 경로에 추가
if str(CONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_DIR))

from memory.store import MemoryStore, MemoryType

# 모듈 수준 싱글턴
_memory_store = None

# 유효한 MemoryType 값 목록
_VALID_TYPES = [t.value for t in MemoryType]


def _get_store():
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore(str(DATA_DIR / "memory"))
    return _memory_store


class MemoryHandlerMixin:

    def _handle_list_memory(self, parsed):
        """GET /api/memory — 메모리 검색/목록

        쿼리 파라미터:
          - query: 키워드 검색어
          - type: 메모리 유형 필터 (decision, pattern, failure, context)
          - tags: 태그 필터 (쉼표 구분)
          - project: 프로젝트 스코프 필터
          - limit: 최대 반환 수 (기본 20)
        """
        qs = parse_qs(parsed.query)
        query = qs.get("query", [None])[0]
        type_str = qs.get("type", [None])[0]
        tags_str = qs.get("tags", [None])[0]
        project = qs.get("project", [None])[0]

        try:
            limit = int(qs.get("limit", [20])[0])
            if limit < 1:
                limit = 20
        except (ValueError, TypeError):
            limit = 20

        # type 유효성 검사
        mem_type = None
        if type_str:
            if type_str not in _VALID_TYPES:
                return self._error_response(
                    f"유효하지 않은 type: {type_str}. 가능한 값: {_VALID_TYPES}",
                    400, code="INVALID_PARAM")
            mem_type = MemoryType(type_str)

        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None

        store = _get_store()
        if query:
            results = store.search(
                query=query, memory_type=mem_type,
                tags=tags, project=project, limit=limit)
        else:
            results = store.list_all(memory_type=mem_type, limit=limit)
            # list_all은 project 필터가 없으므로 수동 필터
            if project:
                results = [m for m in results if not m.get("project") or m["project"] == project]
            if tags:
                tag_set = set(tags)
                results = [m for m in results if tag_set & set(m.get("tags", []))]

        self._json_response({"memories": results, "count": len(results)})

    def _handle_get_memory(self, mem_id):
        """GET /api/memory/:id — 메모리 상세"""
        mem = _get_store().get(mem_id)
        if mem is None:
            return self._error_response(
                "메모리를 찾을 수 없습니다", 404, code="MEMORY_NOT_FOUND")
        self._json_response(mem)

    def _handle_create_memory(self):
        """POST /api/memory — 메모리 추가

        요청 body:
          - type: string (필수) — decision, pattern, failure, context
          - title: string (필수)
          - content: string (필수)
          - tags: string[] (선택, 기본 [])
          - project: string (선택)
          - goal_id: string (선택)
        """
        body = self._read_body()

        # 필수 필드 검증
        type_str = body.get("type", "").strip()
        if not type_str:
            return self._error_response(
                "type 필드가 필요합니다", 400, code="MISSING_FIELD")
        if type_str not in _VALID_TYPES:
            return self._error_response(
                f"유효하지 않은 type: {type_str}. 가능한 값: {_VALID_TYPES}",
                400, code="INVALID_PARAM")

        title = body.get("title", "").strip()
        if not title:
            return self._error_response(
                "title 필드가 필요합니다", 400, code="MISSING_FIELD")

        content = body.get("content", "").strip()
        if not content:
            return self._error_response(
                "content 필드가 필요합니다", 400, code="MISSING_FIELD")

        tags = body.get("tags", [])
        if not isinstance(tags, list):
            return self._error_response(
                "tags는 문자열 배열이어야 합니다", 400, code="INVALID_PARAM")

        project = body.get("project")
        goal_id = body.get("goal_id")

        mem = _get_store().add(
            memory_type=MemoryType(type_str),
            title=title,
            content=content,
            tags=tags,
            project=project,
            goal_id=goal_id,
        )
        self._json_response(mem, 201)

    def _handle_update_memory(self, mem_id):
        """POST /api/memory/:id/update — 메모리 수정

        요청 body (모두 선택):
          - title: string
          - content: string
          - tags: string[]
          - project: string
        """
        store = _get_store()
        existing = store.get(mem_id)
        if existing is None:
            return self._error_response(
                "메모리를 찾을 수 없습니다", 404, code="MEMORY_NOT_FOUND")

        body = self._read_body()
        kwargs = {}

        if "title" in body:
            title = body["title"].strip() if isinstance(body["title"], str) else ""
            if not title:
                return self._error_response(
                    "title은 빈 문자열일 수 없습니다", 400, code="INVALID_PARAM")
            kwargs["title"] = title

        if "content" in body:
            content = body["content"].strip() if isinstance(body["content"], str) else ""
            if not content:
                return self._error_response(
                    "content는 빈 문자열일 수 없습니다", 400, code="INVALID_PARAM")
            kwargs["content"] = content

        if "tags" in body:
            if not isinstance(body["tags"], list):
                return self._error_response(
                    "tags는 문자열 배열이어야 합니다", 400, code="INVALID_PARAM")
            kwargs["tags"] = body["tags"]

        if "project" in body:
            kwargs["project"] = body["project"]

        if not kwargs:
            return self._error_response(
                "변경할 필드가 없습니다. title, content, tags, project 중 하나를 지정하세요.",
                400, code="NO_CHANGES")

        updated = store.update(mem_id, **kwargs)
        self._json_response(updated)

    def _handle_delete_memory(self, mem_id):
        """DELETE /api/memory/:id — 메모리 삭제"""
        deleted = _get_store().delete(mem_id)
        if not deleted:
            return self._error_response(
                "메모리를 찾을 수 없습니다", 404, code="MEMORY_NOT_FOUND")
        self._json_response({"deleted": True, "id": mem_id})
