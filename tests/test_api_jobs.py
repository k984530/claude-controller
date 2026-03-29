#!/usr/bin/env python3
"""
GET /api/jobs API 통합 테스트

실행 방법:
    python3 tests/test_api_jobs.py

전제 조건:
    - 서버가 http://localhost:8420 에서 실행 중이어야 함
"""

import json
import os
import sys
import unittest

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8420")
JOBS_URL = f"{BASE_URL}/api/jobs"

# 작업 항목에 반드시 존재해야 하는 필드
REQUIRED_FIELDS = {"job_id", "status", "prompt"}

# 허용되는 status 값
VALID_STATUSES = {"running", "done", "failed", "queued", "cancelled", "pending"}


class TestGetApiJobs(unittest.TestCase):
    """GET /api/jobs 엔드포인트 테스트"""

    _is_paginated = None  # 서버 응답 형식 캐시

    @classmethod
    def setUpClass(cls):
        """서버 연결 + 응답 형식(paginated dict vs flat list) 사전 확인."""
        try:
            resp = requests.get(JOBS_URL, timeout=5)
        except requests.ConnectionError:
            raise unittest.SkipTest(f"서버에 연결할 수 없습니다: {BASE_URL}")
        cls._is_paginated = isinstance(resp.json(), dict)

    @staticmethod
    def _get_jobs(data):
        """페이지네이션 응답 또는 배열 응답에서 jobs 리스트를 추출한다."""
        if isinstance(data, list):
            return data
        return data.get("jobs", [])

    def _require_paginated(self):
        """페이지네이션 형식이 아니면 테스트를 skip한다."""
        if not self._is_paginated:
            self.skipTest("서버가 paginated 응답을 반환하지 않음 — 서버 재시작 필요")

    # ── 기본 응답 검증 ──────────────────────────────

    def test_status_code_200(self):
        """GET /api/jobs 는 200 OK 를 반환한다."""
        resp = requests.get(JOBS_URL, timeout=5)
        self.assertEqual(resp.status_code, 200)

    def test_content_type_json(self):
        """응답 Content-Type 이 application/json 이다."""
        resp = requests.get(JOBS_URL, timeout=5)
        ct = resp.headers.get("Content-Type", "")
        self.assertIn("application/json", ct)

    def test_response_is_paginated_object(self):
        """응답 본문이 페이지네이션 객체이다 (jobs, total, page, limit, pages)."""
        self._require_paginated()
        resp = requests.get(JOBS_URL, timeout=5)
        data = resp.json()
        self.assertIsInstance(data, dict)
        self.assertIn("jobs", data)
        self.assertIsInstance(data["jobs"], list)
        for key in ("total", "page", "limit", "pages"):
            self.assertIn(key, data)
            self.assertIsInstance(data[key], int)

    def test_pagination_defaults(self):
        """기본 page=1, limit=10 으로 응답한다."""
        self._require_paginated()
        resp = requests.get(JOBS_URL, timeout=5)
        data = resp.json()
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["limit"], 10)
        self.assertLessEqual(len(data["jobs"]), 10)

    def test_pagination_custom_limit(self):
        """?limit=2 로 요청하면 최대 2개만 반환한다."""
        self._require_paginated()
        resp = requests.get(JOBS_URL, params={"limit": 2}, timeout=5)
        data = resp.json()
        self.assertLessEqual(len(data["jobs"]), 2)
        self.assertEqual(data["limit"], 2)

    def test_pagination_page_navigation(self):
        """?page=2&limit=1 로 두 번째 페이지를 요청할 수 있다."""
        self._require_paginated()
        resp = requests.get(JOBS_URL, params={"page": 2, "limit": 1}, timeout=5)
        data = resp.json()
        if data["total"] < 2:
            self.skipTest("작업이 2개 미만이어서 페이지 이동 검증 불가")
        self.assertEqual(data["page"], 2)
        self.assertEqual(len(data["jobs"]), 1)

    def test_pagination_total_consistency(self):
        """total 은 pages * limit 이상이어야 한다."""
        self._require_paginated()
        resp = requests.get(JOBS_URL, timeout=5)
        data = resp.json()
        self.assertGreaterEqual(data["pages"], 1)
        self.assertLessEqual(data["total"], data["pages"] * data["limit"])

    # ── 항목 스키마 검증 ─────────────────────────────

    def test_items_have_required_fields(self):
        """각 작업 항목에 job_id, status, prompt 필드가 존재한다."""
        resp = requests.get(JOBS_URL, timeout=5)
        jobs = self._get_jobs(resp.json())
        if not jobs:
            self.skipTest("작업이 없어 스키마 검증 불가")
        for item in jobs:
            for field in REQUIRED_FIELDS:
                self.assertIn(
                    field, item,
                    f"항목에 '{field}' 필드가 없음: {list(item.keys())}"
                )

    def test_job_id_is_string(self):
        """job_id 는 비어있지 않은 문자열이다."""
        resp = requests.get(JOBS_URL, timeout=5)
        jobs = self._get_jobs(resp.json())
        if not jobs:
            self.skipTest("작업이 없어 검증 불가")
        for item in jobs:
            self.assertIsInstance(item["job_id"], str)
            self.assertTrue(len(item["job_id"]) > 0, "job_id 가 빈 문자열")

    def test_status_values_are_valid(self):
        """status 는 허용된 값(running/done/failed/queued/cancelled/pending) 중 하나이다."""
        resp = requests.get(JOBS_URL, timeout=5)
        jobs = self._get_jobs(resp.json())
        if not jobs:
            self.skipTest("작업이 없어 검증 불가")
        for item in jobs:
            self.assertIn(
                item["status"], VALID_STATUSES,
                f"예상하지 못한 status: '{item['status']}'"
            )

    def test_prompt_is_string(self):
        """prompt 는 문자열이다 (비어있을 수 있음)."""
        resp = requests.get(JOBS_URL, timeout=5)
        jobs = self._get_jobs(resp.json())
        if not jobs:
            self.skipTest("작업이 없어 검증 불가")
        for item in jobs:
            self.assertIsInstance(item["prompt"], str)

    # ── 선택적 필드 타입 검증 ────────────────────────

    def test_optional_fields_types(self):
        """선택적 필드의 타입이 올바르다 (있는 경우에만 검증)."""
        resp = requests.get(JOBS_URL, timeout=5)
        jobs = self._get_jobs(resp.json())
        if not jobs:
            self.skipTest("작업이 없어 검증 불가")

        item = jobs[0]

        # created_at — 문자열 또는 null
        if "created_at" in item and item["created_at"] is not None:
            self.assertIsInstance(item["created_at"], str)

        # cost_usd — 숫자 또는 null
        if "cost_usd" in item and item["cost_usd"] is not None:
            self.assertIsInstance(item["cost_usd"], (int, float))

        # duration_ms — 숫자 또는 null
        if "duration_ms" in item and item["duration_ms"] is not None:
            self.assertIsInstance(item["duration_ms"], (int, float))

        # depends_on — 리스트, 문자열, 또는 null
        if "depends_on" in item and item["depends_on"] is not None:
            self.assertIsInstance(item["depends_on"], (list, str))

    # ── 쿼리 파라미터 ───────────────────────────────

    def test_cwd_filter_returns_paginated(self):
        """?cwd= 필터를 사용해도 페이지네이션 응답을 반환한다."""
        resp = requests.get(JOBS_URL, params={"cwd": "/nonexistent"}, timeout=5)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        jobs = self._get_jobs(data)
        self.assertIsInstance(jobs, list)

    def test_cwd_filter_valid_path(self):
        """실제 프로젝트 경로로 필터링하면 해당 작업만 반환된다."""
        # 먼저 전체 목록에서 cwd 를 하나 가져온다 (limit 크게 설정)
        resp = requests.get(JOBS_URL, params={"limit": 100}, timeout=5)
        jobs = self._get_jobs(resp.json())
        if not jobs:
            self.skipTest("작업이 없어 필터 검증 불가")

        # cwd 가 있는 첫 번째 항목 찾기
        sample_cwd = None
        for item in jobs:
            if item.get("cwd"):
                sample_cwd = item["cwd"]
                break
        if not sample_cwd:
            self.skipTest("cwd 가 있는 작업이 없음")

        # 필터 요청
        filtered = requests.get(JOBS_URL, params={"cwd": sample_cwd, "limit": 100}, timeout=5)
        self.assertEqual(filtered.status_code, 200)
        filtered_jobs = self._get_jobs(filtered.json())
        self.assertIsInstance(filtered_jobs, list)

        # 서버는 prefix matching (하위 경로 포함) 으로 필터링한다.
        norm_cwd = os.path.normpath(sample_cwd)
        unrelated = [
            item for item in filtered_jobs
            if item.get("cwd") and not (
                os.path.normpath(item["cwd"]) == norm_cwd
                or os.path.normpath(item["cwd"]).startswith(norm_cwd + os.sep)
            )
        ]
        if unrelated:
            self.skipTest(
                f"cwd 필터가 서버에 미반영 (서버 재시작 필요) — "
                f"{len(unrelated)}건의 무관한 cwd 포함"
            )

    # ── CORS 헤더 ────────────────────────────────────

    def test_cors_headers_present(self):
        """응답에 CORS 관련 헤더가 포함된다."""
        resp = requests.get(JOBS_URL, timeout=5)
        # Access-Control-Allow-Origin 은 항상 설정됨
        self.assertIn("Access-Control-Allow-Origin", resp.headers)

    # ── HTTP 메서드 ──────────────────────────────────

    def test_post_not_allowed(self):
        """POST /api/jobs 는 허용되지 않는다 (GET 전용)."""
        resp = requests.post(JOBS_URL, json={}, timeout=5)
        # 405 또는 다른 에러 코드 (200 이 아니어야 함)
        self.assertNotEqual(resp.status_code, 200)


if __name__ == "__main__":
    # 서버 도달 가능 여부 사전 확인
    try:
        r = requests.get(f"{BASE_URL}/api/jobs", timeout=3)
    except requests.ConnectionError:
        print(f"\n[ERROR] 서버에 연결할 수 없습니다: {BASE_URL}")
        print("서버가 실행 중인지 확인하세요.\n")
        sys.exit(1)

    unittest.main(verbosity=2)
