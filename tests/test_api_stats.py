#!/usr/bin/env python3
"""
GET /api/stats API 통합 테스트

실행 방법:
    python3 -m unittest tests.test_api_stats -v

전제 조건:
    - 서버가 http://localhost:8420 에서 실행 중이어야 함
"""

import json
import os
import time
import unittest
import urllib.request
import urllib.error

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8420")
STATS_URL = f"{BASE_URL}/api/stats"

# /api/stats 응답의 최상위 필수 키
TOP_LEVEL_KEYS = {"period", "jobs", "success_rate", "cost", "duration", "by_cwd"}

# 하위 섹션 필수 키
PERIOD_KEYS = {"from", "to"}
JOBS_KEYS = {"total", "running", "done", "failed"}
COST_KEYS = {"total_usd", "jobs_with_cost"}
DURATION_KEYS = {"avg_ms", "jobs_with_duration"}

# 유효한 period 파라미터 값
VALID_PERIODS = ("day", "week", "month", "all")


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


class TestGetApiStats(unittest.TestCase):
    """GET /api/stats 엔드포인트 테스트"""

    @classmethod
    def setUpClass(cls):
        """서버 연결 및 엔드포인트 존재 확인 — 실패하면 전체 skip."""
        try:
            status, _, _ = _fetch(STATS_URL)
        except (urllib.error.URLError, OSError):
            raise unittest.SkipTest(
                f"서버에 연결할 수 없습니다: {BASE_URL}"
            )
        if status == 404:
            raise unittest.SkipTest(
                "/api/stats 엔드포인트가 존재하지 않습니다 — 서버 재시작 필요"
            )

    # ── 기본 응답 ────────────────────────────────────

    def test_returns_200(self):
        """기본 요청(period 없음)은 200을 반환한다."""
        status, _, _ = _fetch(STATS_URL)
        self.assertEqual(status, 200)

    def test_content_type_is_json(self):
        """응답 Content-Type 이 application/json 이다."""
        _, headers, _ = _fetch(STATS_URL)
        ct = headers.get("Content-Type", headers.get("content-type", ""))
        self.assertIn("application/json", ct)

    # ── 최상위 키 구조 ──────────────────────────────

    def test_top_level_keys_present(self):
        """응답에 6개 최상위 키가 모두 존재한다."""
        _, _, data = _fetch(STATS_URL)
        for key in TOP_LEVEL_KEYS:
            self.assertIn(key, data, f"최상위 키 '{key}' 누락")

    # ── period 섹션 ──────────────────────────────────

    def test_period_keys(self):
        """period 섹션에 from, to 키가 있다."""
        _, _, data = _fetch(STATS_URL)
        period = data["period"]
        for key in PERIOD_KEYS:
            self.assertIn(key, period, f"period.{key} 누락")

    def test_period_to_is_number(self):
        """period.to 는 숫자(Unix timestamp)다."""
        _, _, data = _fetch(STATS_URL)
        to_val = data["period"]["to"]
        self.assertIsInstance(to_val, (int, float), "period.to 는 숫자여야 함")
        self.assertGreater(to_val, 0, "period.to 는 양수여야 함")

    def test_period_from_is_null_for_all(self):
        """period=all 일 때 period.from 은 None 이다."""
        _, _, data = _fetch(f"{STATS_URL}?period=all")
        self.assertIsNone(data["period"]["from"], "period=all 일 때 from 은 null")

    def test_period_from_is_number_for_day(self):
        """period=day 일 때 period.from 은 숫자다."""
        _, _, data = _fetch(f"{STATS_URL}?period=day")
        from_val = data["period"]["from"]
        self.assertIsInstance(from_val, (int, float), "period=day 일 때 from 은 숫자")

    def test_period_day_range_is_86400(self):
        """period=day 일 때 to - from 이 약 86400초(±5초)다."""
        _, _, data = _fetch(f"{STATS_URL}?period=day")
        diff = data["period"]["to"] - data["period"]["from"]
        self.assertAlmostEqual(diff, 86400, delta=5,
                               msg="period=day 범위가 24시간이 아님")

    def test_period_week_range_is_604800(self):
        """period=week 일 때 to - from 이 약 604800초(±5초)다."""
        _, _, data = _fetch(f"{STATS_URL}?period=week")
        diff = data["period"]["to"] - data["period"]["from"]
        self.assertAlmostEqual(diff, 604800, delta=5,
                               msg="period=week 범위가 7일이 아님")

    def test_period_month_range_is_2592000(self):
        """period=month 일 때 to - from 이 약 2592000초(±5초)다."""
        _, _, data = _fetch(f"{STATS_URL}?period=month")
        diff = data["period"]["to"] - data["period"]["from"]
        self.assertAlmostEqual(diff, 2592000, delta=5,
                               msg="period=month 범위가 30일이 아님")

    # ── jobs 섹션 ────────────────────────────────────

    def test_jobs_keys(self):
        """jobs 섹션에 total, running, done, failed 키가 있다."""
        _, _, data = _fetch(STATS_URL)
        jobs = data["jobs"]
        for key in JOBS_KEYS:
            self.assertIn(key, jobs, f"jobs.{key} 누락")

    def test_jobs_values_are_non_negative_int(self):
        """jobs 의 모든 값은 0 이상의 정수다."""
        _, _, data = _fetch(STATS_URL)
        jobs = data["jobs"]
        for key in JOBS_KEYS:
            val = jobs[key]
            self.assertIsInstance(val, int, f"jobs.{key} 은 int 이어야 함")
            self.assertGreaterEqual(val, 0, f"jobs.{key} 은 0 이상이어야 함")

    def test_jobs_total_equals_sum(self):
        """jobs.total == running + done + failed 이다."""
        _, _, data = _fetch(STATS_URL)
        j = data["jobs"]
        expected = j["running"] + j["done"] + j["failed"]
        self.assertEqual(j["total"], expected,
                         f"total({j['total']}) != running+done+failed({expected})")

    # ── success_rate ─────────────────────────────────

    def test_success_rate_type(self):
        """success_rate 는 float 또는 None 이다."""
        _, _, data = _fetch(STATS_URL)
        sr = data["success_rate"]
        self.assertTrue(
            sr is None or isinstance(sr, (int, float)),
            f"success_rate 타입이 예상과 다름: {type(sr)}"
        )

    def test_success_rate_range(self):
        """success_rate 가 숫자이면 0 ~ 1 범위이다."""
        _, _, data = _fetch(STATS_URL)
        sr = data["success_rate"]
        if sr is not None:
            self.assertGreaterEqual(sr, 0, "success_rate < 0")
            self.assertLessEqual(sr, 1, "success_rate > 1")

    def test_success_rate_null_when_no_completed(self):
        """완료 작업이 0이면 success_rate 는 None 이다."""
        _, _, data = _fetch(STATS_URL)
        j = data["jobs"]
        completed = j["done"] + j["failed"]
        if completed == 0:
            self.assertIsNone(data["success_rate"],
                              "완료 작업 0인데 success_rate 가 null 이 아님")

    # ── cost 섹션 ────────────────────────────────────

    def test_cost_keys(self):
        """cost 섹션에 total_usd, jobs_with_cost 키가 있다."""
        _, _, data = _fetch(STATS_URL)
        cost = data["cost"]
        for key in COST_KEYS:
            self.assertIn(key, cost, f"cost.{key} 누락")

    def test_cost_total_usd_type(self):
        """cost.total_usd 는 숫자 또는 None 이다."""
        _, _, data = _fetch(STATS_URL)
        val = data["cost"]["total_usd"]
        self.assertTrue(
            val is None or isinstance(val, (int, float)),
            f"cost.total_usd 타입이 예상과 다름: {type(val)}"
        )

    def test_cost_jobs_with_cost_is_non_negative_int(self):
        """cost.jobs_with_cost 는 0 이상의 정수다."""
        _, _, data = _fetch(STATS_URL)
        val = data["cost"]["jobs_with_cost"]
        self.assertIsInstance(val, int)
        self.assertGreaterEqual(val, 0)

    def test_cost_null_when_no_cost_jobs(self):
        """jobs_with_cost 가 0이면 total_usd 는 None 이다."""
        _, _, data = _fetch(STATS_URL)
        cost = data["cost"]
        if cost["jobs_with_cost"] == 0:
            self.assertIsNone(cost["total_usd"],
                              "jobs_with_cost=0 인데 total_usd 가 null 이 아님")

    # ── duration 섹션 ────────────────────────────────

    def test_duration_keys(self):
        """duration 섹션에 avg_ms, jobs_with_duration 키가 있다."""
        _, _, data = _fetch(STATS_URL)
        dur = data["duration"]
        for key in DURATION_KEYS:
            self.assertIn(key, dur, f"duration.{key} 누락")

    def test_duration_avg_ms_type(self):
        """duration.avg_ms 는 숫자 또는 None 이다."""
        _, _, data = _fetch(STATS_URL)
        val = data["duration"]["avg_ms"]
        self.assertTrue(
            val is None or isinstance(val, (int, float)),
            f"duration.avg_ms 타입이 예상과 다름: {type(val)}"
        )

    def test_duration_jobs_with_duration_is_non_negative_int(self):
        """duration.jobs_with_duration 은 0 이상의 정수다."""
        _, _, data = _fetch(STATS_URL)
        val = data["duration"]["jobs_with_duration"]
        self.assertIsInstance(val, int)
        self.assertGreaterEqual(val, 0)

    # ── by_cwd 섹션 ──────────────────────────────────

    def test_by_cwd_is_dict(self):
        """by_cwd 는 dict 타입이다."""
        _, _, data = _fetch(STATS_URL)
        self.assertIsInstance(data["by_cwd"], dict)

    def test_by_cwd_values_structure(self):
        """by_cwd 의 각 값은 total, done, failed 키를 가진 dict 이다."""
        _, _, data = _fetch(STATS_URL)
        for cwd_path, counts in data["by_cwd"].items():
            self.assertIsInstance(counts, dict, f"by_cwd['{cwd_path}'] 이 dict 가 아님")
            for key in ("total", "done", "failed"):
                self.assertIn(key, counts, f"by_cwd['{cwd_path}'].{key} 누락")
                self.assertIsInstance(counts[key], int,
                                     f"by_cwd['{cwd_path}'].{key} 은 int 이어야 함")

    def test_by_cwd_total_consistency(self):
        """by_cwd 의 모든 total 합 == jobs.total 이다."""
        _, _, data = _fetch(STATS_URL)
        cwd_sum = sum(v["total"] for v in data["by_cwd"].values())
        self.assertEqual(cwd_sum, data["jobs"]["total"],
                         "by_cwd total 합이 jobs.total 과 불일치")

    # ── period 파라미터 유효성 ───────────────────────

    def test_all_valid_periods_return_200(self):
        """day, week, month, all 모두 200을 반환한다."""
        for period in VALID_PERIODS:
            with self.subTest(period=period):
                status, _, _ = _fetch(f"{STATS_URL}?period={period}")
                self.assertEqual(status, 200, f"period={period} 가 200 이 아님")

    def test_invalid_period_falls_back_to_all(self):
        """유효하지 않은 period 값은 all 로 fallback 한다 (from=null)."""
        status, _, data = _fetch(f"{STATS_URL}?period=invalid_xyz")
        self.assertEqual(status, 200)
        self.assertIsNone(data["period"]["from"],
                          "유효하지 않은 period 에서 from 이 null 이 아님")

    # ── 기간별 결과 단조성 ───────────────────────────

    def test_day_total_lte_all_total(self):
        """period=day 의 total 은 period=all 의 total 이하다."""
        _, _, day_data = _fetch(f"{STATS_URL}?period=day")
        _, _, all_data = _fetch(f"{STATS_URL}?period=all")
        self.assertLessEqual(
            day_data["jobs"]["total"],
            all_data["jobs"]["total"],
            "day total 이 all total 보다 클 수 없음"
        )

    # ── HTTP 메서드 ──────────────────────────────────

    def test_post_not_allowed(self):
        """POST /api/stats 는 허용되지 않는다."""
        status, _, _ = _fetch(STATS_URL, method="POST")
        self.assertNotEqual(status, 200)

    # ── CORS ─────────────────────────────────────────

    def test_cors_header_present(self):
        """응답에 Access-Control-Allow-Origin 헤더가 포함된다."""
        _, headers, _ = _fetch(STATS_URL)
        cors = headers.get(
            "Access-Control-Allow-Origin",
            headers.get("access-control-allow-origin", "")
        )
        self.assertTrue(len(cors) > 0, "CORS 헤더 누락")


if __name__ == "__main__":
    unittest.main(verbosity=2)
