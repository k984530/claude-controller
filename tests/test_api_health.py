#!/usr/bin/env python3
"""
GET /api/health API 통합 테스트

실행 방법:
    python3 -m unittest tests.test_api_health -v

전제 조건:
    - 서버가 http://localhost:8420 에서 실행 중이어야 함
"""

import json
import os
import sys
import unittest
import urllib.request
import urllib.error

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8420")
HEALTH_URL = f"{BASE_URL}/api/health"

# /api/health 응답의 최상위 필수 키
TOP_LEVEL_KEYS = {"status", "timestamp", "service", "fifo", "jobs", "disk", "watchdog"}

# 각 섹션의 하위 필수 키
SERVICE_KEYS = {"running", "pid", "uptime_seconds"}
FIFO_KEYS = {"exists", "writable"}
JOBS_KEYS = {"active", "total", "succeeded", "failed"}
DISK_KEYS = {"logs_size_mb", "disk_free_gb"}
WATCHDOG_KEYS = {"running", "restart_count", "last_restart", "status"}


def _fetch(url, method="GET", timeout=5):
    """urllib 기반 HTTP 요청 헬퍼. (status_code, headers, body_dict) 반환."""
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body) if body else {}
            return resp.status, dict(resp.headers), data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {"error": body}
        return e.code, dict(e.headers), data


class TestGetApiHealth(unittest.TestCase):
    """GET /api/health 엔드포인트 테스트"""

    @classmethod
    def setUpClass(cls):
        """서버 연결 및 엔드포인트 존재 확인 — 실패하면 전체 skip."""
        try:
            status, _, _ = _fetch(HEALTH_URL)
        except (urllib.error.URLError, OSError):
            raise unittest.SkipTest(
                f"서버에 연결할 수 없습니다: {BASE_URL}"
            )
        if status == 404:
            raise unittest.SkipTest(
                "/api/health 엔드포인트가 존재하지 않습니다 — 서버 재시작 필요"
            )

    # ── 기본 응답 ────────────────────────────────────

    def test_returns_200_or_503(self):
        """health 엔드포인트는 200 (healthy/degraded) 또는 503 (unhealthy) 을 반환한다."""
        status, _, _ = _fetch(HEALTH_URL)
        self.assertIn(status, {200, 503})

    def test_content_type_is_json(self):
        """응답 Content-Type 이 application/json 이다."""
        _, headers, _ = _fetch(HEALTH_URL)
        ct = headers.get("Content-Type", headers.get("content-type", ""))
        self.assertIn("application/json", ct)

    # ── 최상위 키 구조 ──────────────────────────────

    def test_top_level_keys_present(self):
        """응답에 7개 최상위 키가 모두 존재한다."""
        _, _, data = _fetch(HEALTH_URL)
        for key in TOP_LEVEL_KEYS:
            self.assertIn(key, data, f"최상위 키 '{key}' 누락")

    def test_status_value_valid(self):
        """status 는 healthy, degraded, unhealthy 중 하나다."""
        _, _, data = _fetch(HEALTH_URL)
        self.assertIn(data["status"], {"healthy", "degraded", "unhealthy"})

    def test_timestamp_is_iso_format(self):
        """timestamp 는 ISO 8601 형식 문자열이다."""
        _, _, data = _fetch(HEALTH_URL)
        ts = data["timestamp"]
        self.assertIsInstance(ts, str)
        # ISO 형식 기본 검증: 'T' 구분자 포함, 최소 길이
        self.assertIn("T", ts, "timestamp에 'T' 구분자 없음")
        self.assertGreaterEqual(len(ts), 19, "timestamp 길이가 너무 짧음")

    # ── service 섹션 ─────────────────────────────────

    def test_service_keys(self):
        """service 섹션에 running, pid, uptime_seconds 키가 있다."""
        _, _, data = _fetch(HEALTH_URL)
        svc = data["service"]
        for key in SERVICE_KEYS:
            self.assertIn(key, svc, f"service.{key} 누락")

    def test_service_running_is_bool(self):
        """service.running 은 bool 타입이다."""
        _, _, data = _fetch(HEALTH_URL)
        self.assertIsInstance(data["service"]["running"], bool)

    def test_service_pid_type(self):
        """service.pid 는 int 또는 None 이다."""
        _, _, data = _fetch(HEALTH_URL)
        pid = data["service"]["pid"]
        self.assertTrue(
            pid is None or isinstance(pid, int),
            f"pid 타입이 예상과 다름: {type(pid)}"
        )

    # ── fifo 섹션 ────────────────────────────────────

    def test_fifo_keys(self):
        """fifo 섹션에 exists, writable 키가 있다."""
        _, _, data = _fetch(HEALTH_URL)
        fifo = data["fifo"]
        for key in FIFO_KEYS:
            self.assertIn(key, fifo, f"fifo.{key} 누락")

    def test_fifo_values_are_bool(self):
        """fifo.exists, fifo.writable 은 bool 타입이다."""
        _, _, data = _fetch(HEALTH_URL)
        fifo = data["fifo"]
        self.assertIsInstance(fifo["exists"], bool)
        self.assertIsInstance(fifo["writable"], bool)

    # ── jobs 섹션 ────────────────────────────────────

    def test_jobs_keys(self):
        """jobs 섹션에 active, total, succeeded, failed 키가 있다."""
        _, _, data = _fetch(HEALTH_URL)
        jobs = data["jobs"]
        for key in JOBS_KEYS:
            self.assertIn(key, jobs, f"jobs.{key} 누락")

    def test_jobs_values_are_non_negative_int(self):
        """jobs 의 모든 값은 0 이상의 정수다."""
        _, _, data = _fetch(HEALTH_URL)
        jobs = data["jobs"]
        for key in JOBS_KEYS:
            val = jobs[key]
            self.assertIsInstance(val, int, f"jobs.{key} 은 int 이어야 함")
            self.assertGreaterEqual(val, 0, f"jobs.{key} 은 0 이상이어야 함")

    def test_jobs_total_gte_sum_of_parts(self):
        """jobs.total >= (active + succeeded + failed) 이다."""
        _, _, data = _fetch(HEALTH_URL)
        j = data["jobs"]
        self.assertGreaterEqual(
            j["total"],
            j["active"] + j["succeeded"] + j["failed"],
            "total 이 하위 항목 합보다 작음"
        )

    # ── disk 섹션 ────────────────────────────────────

    def test_disk_keys(self):
        """disk 섹션에 logs_size_mb, disk_free_gb 키가 있다."""
        _, _, data = _fetch(HEALTH_URL)
        disk = data["disk"]
        for key in DISK_KEYS:
            self.assertIn(key, disk, f"disk.{key} 누락")

    def test_disk_values_are_non_negative_numbers(self):
        """disk 값들은 0 이상의 숫자다."""
        _, _, data = _fetch(HEALTH_URL)
        disk = data["disk"]
        for key in DISK_KEYS:
            val = disk[key]
            self.assertIsInstance(val, (int, float), f"disk.{key} 은 숫자여야 함")
            self.assertGreaterEqual(val, 0, f"disk.{key} 은 0 이상이어야 함")

    # ── watchdog 섹션 ────────────────────────────────

    def test_watchdog_keys(self):
        """watchdog 섹션에 running, restart_count, last_restart, status 키가 있다."""
        _, _, data = _fetch(HEALTH_URL)
        wd = data["watchdog"]
        for key in WATCHDOG_KEYS:
            self.assertIn(key, wd, f"watchdog.{key} 누락")

    def test_watchdog_running_is_bool(self):
        """watchdog.running 은 bool 타입이다."""
        _, _, data = _fetch(HEALTH_URL)
        self.assertIsInstance(data["watchdog"]["running"], bool)

    def test_watchdog_restart_count_is_int(self):
        """watchdog.restart_count 는 0 이상의 정수다."""
        _, _, data = _fetch(HEALTH_URL)
        rc = data["watchdog"]["restart_count"]
        self.assertIsInstance(rc, int)
        self.assertGreaterEqual(rc, 0)

    # ── HTTP 메서드 ──────────────────────────────────

    def test_post_not_allowed(self):
        """POST /api/health 는 허용되지 않는다."""
        status, _, _ = _fetch(HEALTH_URL, method="POST")
        self.assertNotEqual(status, 200)

    # ── CORS ─────────────────────────────────────────

    def test_cors_header_present(self):
        """응답에 Access-Control-Allow-Origin 헤더가 포함된다."""
        _, headers, _ = _fetch(HEALTH_URL)
        cors = headers.get(
            "Access-Control-Allow-Origin",
            headers.get("access-control-allow-origin", "")
        )
        self.assertTrue(len(cors) > 0, "CORS 헤더 누락")

    # ── 상태-HTTP 코드 일관성 ────────────────────────

    def test_unhealthy_returns_503(self):
        """status 가 'unhealthy' 이면 HTTP 503 이다."""
        status_code, _, data = _fetch(HEALTH_URL)
        if data.get("status") == "unhealthy":
            self.assertEqual(status_code, 503)

    def test_healthy_or_degraded_returns_200(self):
        """status 가 'healthy' 또는 'degraded' 이면 HTTP 200 이다."""
        status_code, _, data = _fetch(HEALTH_URL)
        if data.get("status") in {"healthy", "degraded"}:
            self.assertEqual(status_code, 200)

    # ── 인증 면제 ────────────────────────────────────

    def test_no_auth_required(self):
        """health 엔드포인트는 인증 없이도 접근 가능하다."""
        # 의도적으로 Authorization 헤더 없이 요청
        status, _, _ = _fetch(HEALTH_URL)
        self.assertIn(status, {200, 503}, "인증 없이도 200/503 반환해야 함")


if __name__ == "__main__":
    unittest.main(verbosity=2)
