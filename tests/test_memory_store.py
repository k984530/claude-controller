#!/usr/bin/env python3
"""
memory.store 모듈 단위 테스트 — MemoryStore, MemoryType
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))

from store import MemoryStore, MemoryType


class TestMemoryStore(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="memstore_test_")
        self.store = MemoryStore(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 기본 CRUD ──

    def test_add_and_get(self):
        mem = self.store.add(
            MemoryType.DECISION, "JWT 대신 세션", "세션 기반이 더 적합",
            tags=["auth", "session"],
        )
        self.assertIn("mem-", mem["id"])
        self.assertEqual(mem["type"], "decision")
        retrieved = self.store.get(mem["id"])
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["title"], "JWT 대신 세션")

    def test_get_nonexistent(self):
        self.assertIsNone(self.store.get("mem-does-not-exist"))

    def test_update(self):
        mem = self.store.add(
            MemoryType.PATTERN, "snake_case", "파이썬 네이밍",
            tags=["style"],
        )
        updated = self.store.update(mem["id"], title="snake_case 강제")
        self.assertEqual(updated["title"], "snake_case 강제")
        self.assertEqual(updated["content"], "파이썬 네이밍")

    def test_update_nonexistent(self):
        self.assertIsNone(self.store.update("mem-nope", title="x"))

    def test_delete(self):
        mem = self.store.add(
            MemoryType.FAILURE, "OOM", "메모리 초과",
            tags=["infra"],
        )
        self.assertTrue(self.store.delete(mem["id"]))
        self.assertIsNone(self.store.get(mem["id"]))

    def test_delete_nonexistent(self):
        self.assertFalse(self.store.delete("mem-nothing"))

    # ── 검색 ──

    def test_search_by_keyword(self):
        self.store.add(MemoryType.DECISION, "REST vs GraphQL", "REST 선택", tags=["api"])
        self.store.add(MemoryType.PATTERN, "리액트 훅", "커스텀 훅 패턴", tags=["frontend"])
        results = self.store.search("REST")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "REST vs GraphQL")

    def test_search_by_type(self):
        self.store.add(MemoryType.DECISION, "DB 선택", "PostgreSQL", tags=["db"])
        self.store.add(MemoryType.PATTERN, "코드 스타일", "black", tags=["style"])
        results = self.store.search("", memory_type=MemoryType.DECISION)
        types = [r["type"] for r in results]
        self.assertTrue(all(t == "decision" for t in types))

    def test_search_by_tags(self):
        self.store.add(MemoryType.CONTEXT, "API 구조", "RESTful", tags=["api", "backend"])
        self.store.add(MemoryType.CONTEXT, "UI 구조", "React", tags=["frontend"])
        results = self.store.search("", tags=["api"])
        self.assertEqual(len(results), 1)
        self.assertIn("api", results[0]["tags"])

    def test_search_empty_query(self):
        self.store.add(MemoryType.DECISION, "A", "a", tags=[])
        self.store.add(MemoryType.PATTERN, "B", "b", tags=[])
        results = self.store.search("")
        self.assertEqual(len(results), 2)

    def test_search_limit(self):
        for i in range(10):
            self.store.add(MemoryType.CONTEXT, f"Item {i}", f"content {i}", tags=[])
        results = self.store.search("", limit=3)
        self.assertEqual(len(results), 3)

    # ── list_all ──

    def test_list_all(self):
        self.store.add(MemoryType.DECISION, "A", "a", tags=[])
        self.store.add(MemoryType.FAILURE, "B", "b", tags=[])
        all_mems = self.store.list_all()
        self.assertEqual(len(all_mems), 2)

    def test_list_all_by_type(self):
        self.store.add(MemoryType.DECISION, "A", "a", tags=[])
        self.store.add(MemoryType.FAILURE, "B", "b", tags=[])
        only_decisions = self.store.list_all(memory_type=MemoryType.DECISION)
        self.assertEqual(len(only_decisions), 1)

    # ── get_relevant ──

    def test_get_relevant(self):
        self.store.add(MemoryType.DECISION, "인증 설계", "JWT 토큰 기반", tags=["auth"])
        self.store.add(MemoryType.PATTERN, "에러 핸들링", "중앙 집중 방식", tags=["error"])
        relevant = self.store.get_relevant("인증 관련 메모리")
        self.assertGreaterEqual(len(relevant), 1)

    # ── 접근 횟수 갱신 ──

    def test_access_count_increments(self):
        mem = self.store.add(MemoryType.CONTEXT, "Test", "content", tags=[])
        self.assertEqual(mem["access_count"], 0)
        retrieved = self.store.get(mem["id"])
        self.assertEqual(retrieved["access_count"], 1)
        retrieved2 = self.store.get(mem["id"])
        self.assertEqual(retrieved2["access_count"], 2)

    # ── 파일 시스템 ──

    def test_subdirectories_created(self):
        for sub in ("decisions", "patterns", "failures", "context"):
            self.assertTrue(os.path.isdir(os.path.join(self.tmpdir, sub)))

    def test_atomic_save(self):
        mem = self.store.add(MemoryType.DECISION, "Atomic", "test", tags=[])
        path = os.path.join(self.tmpdir, "decisions", f"{mem['id']}.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["title"], "Atomic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
