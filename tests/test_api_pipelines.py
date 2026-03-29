#!/usr/bin/env python3
"""
GET /api/pipelines API 통합 테스트

실행 방법:
    python3 tests/test_api_pipelines.py

전제 조건:
    - 서버가 http://localhost:8420 에서 실행 중이어야 함
"""

import json
import os
import sys
import unittest

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8420")
PIPELINES_URL = f"{BASE_URL}/api/pipelines"

# 파이프라인 항목에 반드시 존재해야 하는 필드
REQUIRED_FIELDS = {"id", "name", "status", "command", "interval"}

# 허용되는 status 값
VALID_STATUSES = {"active", "stopped"}


class TestGetApiPipelines(unittest.TestCase):
    """GET /api/pipelines 엔드포인트 테스트"""

    # ── 기본 응답 검증 ──────────────────────────────

    def test_status_code_200(self):
        """GET /api/pipelines 는 200 OK 를 반환한다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        self.assertEqual(resp.status_code, 200)

    def test_content_type_json(self):
        """응답 Content-Type 이 application/json 이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        ct = resp.headers.get("Content-Type", "")
        self.assertIn("application/json", ct)

    def test_response_is_json_array(self):
        """응답 본문이 JSON 배열이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        self.assertIsInstance(data, list)

    # ── 항목 스키마 검증 ─────────────────────────────

    def test_items_have_required_fields(self):
        """각 파이프라인 항목에 id, name, status, command, interval 필드가 존재한다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 스키마 검증 불가")
        for item in data:
            for field in REQUIRED_FIELDS:
                self.assertIn(
                    field, item,
                    f"항목에 '{field}' 필드가 없음: {list(item.keys())}"
                )

    def test_id_is_nonempty_string(self):
        """id 는 비어있지 않은 문자열이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        for item in data:
            self.assertIsInstance(item["id"], str)
            self.assertTrue(len(item["id"]) > 0, "id 가 빈 문자열")

    def test_name_is_string(self):
        """name 은 문자열이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        for item in data:
            self.assertIsInstance(item["name"], str)

    def test_status_values_are_valid(self):
        """status 는 허용된 값(active/stopped) 중 하나이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        for item in data:
            self.assertIn(
                item["status"], VALID_STATUSES,
                f"예상하지 못한 status: '{item['status']}'"
            )

    def test_command_is_string(self):
        """command 는 문자열이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        for item in data:
            self.assertIsInstance(item["command"], str)

    def test_interval_is_string(self):
        """interval 은 문자열이다 (예: '30m', '1h')."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        for item in data:
            self.assertIsInstance(item["interval"], str)
            self.assertTrue(len(item["interval"]) > 0, "interval 이 빈 문자열")

    # ── 선택적 필드 타입 검증 ────────────────────────

    def test_numeric_fields_types(self):
        """interval_sec, run_count 는 정수이다 (있는 경우)."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        item = data[0]
        for field in ("interval_sec", "run_count"):
            if field in item and item[field] is not None:
                self.assertIsInstance(
                    item[field], int,
                    f"{field} 이(가) int 가 아님: {type(item[field]).__name__}"
                )

    def test_timestamp_fields_types(self):
        """created_at, updated_at, next_run, last_run 은 문자열 또는 null 이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        item = data[0]
        for field in ("created_at", "updated_at", "next_run", "last_run"):
            if field in item and item[field] is not None:
                self.assertIsInstance(
                    item[field], str,
                    f"{field} 이(가) str 이 아님: {type(item[field]).__name__}"
                )

    def test_history_is_list(self):
        """history 필드가 있으면 리스트이다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 검증 불가")
        item = data[0]
        if "history" in item:
            self.assertIsInstance(item["history"], list)

    # ── 개별 파이프라인 조회 ─────────────────────────

    def test_pipeline_status_endpoint(self):
        """GET /api/pipelines/:id/status 가 개별 파이프라인 정보를 반환한다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        data = resp.json()
        if not data:
            self.skipTest("파이프라인이 없어 개별 조회 불가")
        pipe_id = data[0]["id"]
        status_resp = requests.get(
            f"{PIPELINES_URL}/{pipe_id}/status", timeout=5
        )
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertIsInstance(status_data, dict)
        self.assertEqual(status_data.get("id"), pipe_id)

    def test_nonexistent_pipeline_returns_404(self):
        """존재하지 않는 파이프라인 ID 는 404 를 반환한다."""
        resp = requests.get(
            f"{PIPELINES_URL}/pipe-nonexistent-99999/status", timeout=5
        )
        self.assertEqual(resp.status_code, 404)

    # ── CORS 헤더 ────────────────────────────────────

    def test_cors_headers_present(self):
        """응답에 CORS 관련 헤더가 포함된다."""
        resp = requests.get(PIPELINES_URL, timeout=5)
        self.assertIn("Access-Control-Allow-Origin", resp.headers)

    # ── HTTP 메서드 ──────────────────────────────────

    def test_delete_not_on_list(self):
        """DELETE /api/pipelines 는 허용되지 않는다 (개별 삭제만 가능)."""
        resp = requests.delete(PIPELINES_URL, timeout=5)
        self.assertNotEqual(resp.status_code, 200)


if __name__ == "__main__":
    try:
        r = requests.get(PIPELINES_URL, timeout=3)
    except requests.ConnectionError:
        print(f"\n[ERROR] 서버에 연결할 수 없습니다: {BASE_URL}")
        print("서버가 실행 중인지 확인하세요.\n")
        sys.exit(1)

    unittest.main(verbosity=2)
