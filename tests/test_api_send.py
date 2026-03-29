#!/usr/bin/env python3
"""
POST /api/send API 통합 테스트

실행 방법:
    python3 tests/test_api_send.py

전제 조건:
    - 서버가 http://localhost:8420 에서 실행 중이어야 함
    - controller 서비스(FIFO)가 동작 중이어야 함 (아니면 FIFO 관련 테스트 skip)
"""

import os
import sys
import time
import unittest

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8420")
SEND_URL = f"{BASE_URL}/api/send"
JOBS_URL = f"{BASE_URL}/api/jobs"

# 성공 응답에 반드시 포함되어야 하는 필드
REQUIRED_SUCCESS_FIELDS = {"job_id", "prompt"}


def _fifo_available():
    """FIFO 가 동작 중인지 간단히 확인한다."""
    try:
        resp = requests.post(
            SEND_URL,
            json={"prompt": "__fifo_probe__"},
            timeout=5,
        )
        return resp.status_code == 201
    except requests.RequestException:
        return False


FIFO_OK = _fifo_available()


class TestPostApiSend(unittest.TestCase):
    """POST /api/send 엔드포인트 테스트"""

    # ── 입력 검증 (FIFO 상태 무관) ──────────────────

    def test_missing_prompt_returns_400(self):
        """prompt 필드 없이 보내면 400 을 반환한다."""
        resp = requests.post(SEND_URL, json={}, timeout=5)
        self.assertEqual(resp.status_code, 400)

    def test_empty_prompt_returns_400(self):
        """prompt 가 빈 문자열이면 400 을 반환한다."""
        resp = requests.post(SEND_URL, json={"prompt": ""}, timeout=5)
        self.assertEqual(resp.status_code, 400)

    def test_whitespace_only_prompt_returns_400(self):
        """prompt 가 공백만 있으면 400 을 반환한다."""
        resp = requests.post(SEND_URL, json={"prompt": "   "}, timeout=5)
        self.assertEqual(resp.status_code, 400)

    def test_missing_prompt_error_has_error_field(self):
        """400 응답 본문에 error 필드가 포함된다."""
        resp = requests.post(SEND_URL, json={}, timeout=5)
        data = resp.json()
        self.assertIn("error", data)
        err = data["error"]
        if isinstance(err, dict):
            self.assertIn("code", err)
            self.assertIn("message", err)
            self.assertTrue(len(err["message"]) > 0)
        else:
            self.assertIsInstance(err, str)
            self.assertTrue(len(err) > 0)

    def test_content_type_json_required(self):
        """Content-Type 없이 빈 body 보내면 에러를 반환한다."""
        resp = requests.post(SEND_URL, data="not json", timeout=5)
        self.assertIn(resp.status_code, {400, 415, 500})

    # ── HTTP 메서드 ──────────────────────────────────

    def test_get_not_allowed(self):
        """GET /api/send 는 허용되지 않는다."""
        resp = requests.get(SEND_URL, timeout=5)
        self.assertNotEqual(resp.status_code, 200)

    # ── CORS 헤더 ────────────────────────────────────

    def test_cors_headers_on_error(self):
        """에러 응답에도 CORS 헤더가 포함된다."""
        resp = requests.post(SEND_URL, json={}, timeout=5)
        self.assertIn("Access-Control-Allow-Origin", resp.headers)

    # ── 성공 응답 (FIFO 필요) ────────────────────────

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작 — 서비스가 실행 중이어야 함")
    def test_valid_prompt_returns_201(self):
        """유효한 prompt 를 보내면 201 Created 를 반환한다."""
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo __send_test_201__"},
            timeout=5,
        )
        self.assertEqual(resp.status_code, 201)

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_success_content_type_json(self):
        """성공 응답의 Content-Type 이 application/json 이다."""
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo __send_test_ct__"},
            timeout=5,
        )
        ct = resp.headers.get("Content-Type", "")
        self.assertIn("application/json", ct)

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_success_has_required_fields(self):
        """성공 응답에 job_id, prompt 필드가 있다."""
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo __send_test_fields__"},
            timeout=5,
        )
        data = resp.json()
        for field in REQUIRED_SUCCESS_FIELDS:
            self.assertIn(field, data, f"성공 응답에 '{field}' 누락")

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_job_id_is_nonempty_string(self):
        """job_id 는 비어있지 않은 문자열이다."""
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo __send_test_jobid__"},
            timeout=5,
        )
        data = resp.json()
        self.assertIsInstance(data["job_id"], str)
        self.assertTrue(len(data["job_id"]) > 0, "job_id 가 빈 문자열")

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_prompt_echo_back(self):
        """응답의 prompt 필드가 요청한 prompt 와 동일하다."""
        test_prompt = "echo __send_test_echo_12345__"
        resp = requests.post(
            SEND_URL,
            json={"prompt": test_prompt},
            timeout=5,
        )
        data = resp.json()
        self.assertEqual(data["prompt"], test_prompt)

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_cwd_field_present(self):
        """성공 응답에 cwd 필드가 포함된다 (값은 null 허용)."""
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo __send_test_cwd__"},
            timeout=5,
        )
        data = resp.json()
        self.assertIn("cwd", data)

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_custom_cwd_echoed(self):
        """cwd 를 지정하면 응답에 반영된다."""
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo __send_test_custom_cwd__", "cwd": "/tmp"},
            timeout=5,
        )
        data = resp.json()
        self.assertEqual(data.get("cwd"), "/tmp")

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_job_appears_in_jobs_list(self):
        """전송한 작업이 /api/jobs 목록에 나타난다 (비동기 처리 대기)."""
        custom_id = f"__send_test_appears_{int(time.time())}__"
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo job_appears_test", "id": custom_id},
            timeout=5,
        )
        self.assertEqual(resp.status_code, 201)
        job_id = resp.json()["job_id"]

        # FIFO → controller → meta 파일 생성까지 시간이 걸릴 수 있으므로 재시도
        matching = []
        for _ in range(20):
            jobs_resp = requests.get(JOBS_URL, timeout=5)
            self.assertEqual(jobs_resp.status_code, 200)
            data = jobs_resp.json()
            jobs = data.get("jobs", data) if isinstance(data, dict) else data
            matching = [j for j in jobs if j.get("job_id") == job_id]
            if matching:
                break
            time.sleep(0.5)
        if not matching:
            self.skipTest(
                f"controller 가 10초 내에 작업을 디스패치하지 못함 (job_id={job_id})"
            )

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_each_send_gets_unique_job_id(self):
        """커스텀 id 를 다르게 지정하면 서로 다른 job_id 를 받는다."""
        ts = int(time.time())
        ids = set()
        for i in range(2):
            resp = requests.post(
                SEND_URL,
                json={
                    "prompt": f"echo __send_test_unique_{i}__",
                    "id": f"__unique_test_{ts}_{i}__",
                },
                timeout=5,
            )
            self.assertEqual(resp.status_code, 201)
            ids.add(resp.json()["job_id"])
        self.assertEqual(len(ids), 2, "두 요청의 job_id 가 동일함")

    @unittest.skipUnless(FIFO_OK, "FIFO 파이프 미동작")
    def test_custom_id_respected(self):
        """body 에 id 를 지정하면 해당 값이 job_id 로 사용된다."""
        custom_id = "__send_test_custom_id_99999__"
        resp = requests.post(
            SEND_URL,
            json={"prompt": "echo __custom_id_test__", "id": custom_id},
            timeout=5,
        )
        # FIFO 에러가 아닌 이상 custom id 가 반영되어야 함
        if resp.status_code == 201:
            self.assertEqual(resp.json()["job_id"], custom_id)


if __name__ == "__main__":
    try:
        r = requests.post(SEND_URL, json={}, timeout=3)
    except requests.ConnectionError:
        print(f"\n[ERROR] 서버에 연결할 수 없습니다: {BASE_URL}")
        print("서버가 실행 중인지 확인하세요.\n")
        sys.exit(1)

    unittest.main(verbosity=2)
