"""
Controller Service — HTTP REST API 핸들러

보안 계층:
  1. Host 헤더 검증 — DNS Rebinding 방지
  2. Origin 검증 — CORS를 허용된 출처로 제한
  3. 토큰 인증 — API 요청마다 Authorization 헤더 필수

기반 Mixin (handler_base.py):
  - ResponseMixin       → JSON 응답, 에러, 본문 읽기
  - SecurityMixin       → Host/CORS/Auth 검증
  - StaticServeMixin    → 정적 파일 서빙, MIME 타입

핸들러 Mixin:
  - handler_jobs.py     → JobHandlerMixin
  - handler_sessions.py → SessionHandlerMixin
  - handler_fs.py       → FsHandlerMixin
  - handler_crud.py     → ProjectHandlerMixin, PipelineHandlerMixin
  - handler_misc.py     → MiscHandlerMixin (auth, stats, status, health, audit, webhook, cleanup)
"""

import http.server
import importlib
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, parse_qs

from config import UPLOADS_DIR
import jobs
import checkpoint
import projects as _projects_mod
import pipeline as _pipeline_mod
import webhook as _webhook_mod
import audit as _audit_mod
import suggestions as _suggestions_mod
import presets as _presets_mod
import goals as _goals_mod

from handler_base import ResponseMixin, SecurityMixin, StaticServeMixin
from handler_jobs import JobHandlerMixin
from handler_sessions import SessionHandlerMixin
from handler_fs import FsHandlerMixin
from handler_crud import ProjectHandlerMixin, PipelineHandlerMixin
from handler_suggestions import SuggestionHandlerMixin
from handler_presets import PresetHandlerMixin
from handler_goals import GoalHandlerMixin
from handler_misc import MiscHandlerMixin

# ── 정적 라우팅 테이블 (OCP: 라우트 추가 시 테이블에 행만 추가) ──

_GET_STATIC_ROUTES = {
    "/api/health": "_handle_health",
    "/api/auth/verify": "_handle_auth_verify",
    "/api/status": "_handle_status",
    "/api/config": "_handle_get_config",
    "/api/skills": "_handle_get_skills",
    "/api/recent-dirs": "_handle_get_recent_dirs",
    "/api/projects": "_handle_list_projects",
    "/api/presets": "_handle_list_presets",
    "/api/pipelines": "_handle_list_pipelines",
}

_GET_PARSED_ROUTES = {
    "/api/audit": "_handle_audit",
    "/api/stats": "_handle_stats",
    "/api/results": "_handle_results",
    "/api/suggestions": "_handle_list_suggestions",
    "/api/goals": "_handle_list_goals",
}

_POST_STATIC_ROUTES = {
    "/api/auth/verify": "_handle_auth_verify",
    "/api/send": "_handle_send",
    "/api/upload": "_handle_upload",
    "/api/service/start": "_handle_service_start",
    "/api/service/stop": "_handle_service_stop",
    "/api/config": "_handle_save_config",
    "/api/skills": "_handle_save_skills",
    "/api/recent-dirs": "_handle_save_recent_dirs",
    "/api/mkdir": "_handle_mkdir",
    "/api/projects": "_handle_add_project",
    "/api/projects/create": "_handle_create_project",
    "/api/suggestions/generate": "_handle_generate_suggestions",
    "/api/suggestions/clear": "_handle_clear_dismissed",
    "/api/presets": "_handle_create_preset",
    "/api/goals": "_handle_create_goal",
    "/api/pipelines": "_handle_create_pipeline",
    "/api/webhooks/test": "_handle_webhook_test",
    "/api/logs/cleanup": "_handle_logs_cleanup",
}

_DELETE_STATIC_ROUTES = {
    "/api/jobs": "_handle_delete_completed_jobs",
}

# ── 사전 컴파일된 파라미터 라우팅 테이블 ──
_GET_PARAM_ROUTES = [
    (re.compile(r"^/api/pipelines/([^/]+)/status$"), "_handle_pipeline_status"),
    (re.compile(r"^/api/pipelines/([^/]+)/history$"), "_handle_pipeline_history"),
    (re.compile(r"^/api/projects/([^/]+)/jobs$"), "_handle_project_jobs"),
    (re.compile(r"^/api/projects/([^/]+)$"), "_handle_get_project"),
    (re.compile(r"^/api/jobs/(\w+)/result$"), "_handle_job_result"),
    (re.compile(r"^/api/jobs/(\w+)/stream$"), "_handle_job_stream"),
    (re.compile(r"^/api/jobs/(\w+)/checkpoints$"), "_handle_job_checkpoints"),
    (re.compile(r"^/api/jobs/(\w+)/diff$"), "_handle_job_diff"),
    (re.compile(r"^/api/session/([a-f0-9-]+)/job$"), "_handle_job_by_session"),
    (re.compile(r"^/api/presets/([^/]+)$"), "_handle_get_preset"),
    (re.compile(r"^/api/goals/([^/]+)$"), "_handle_get_goal"),
]

_POST_PARAM_ROUTES = [
    (re.compile(r"^/api/suggestions/([^/]+)/apply$"), "_handle_apply_suggestion"),
    (re.compile(r"^/api/suggestions/([^/]+)/dismiss$"), "_handle_dismiss_suggestion"),
    (re.compile(r"^/api/pipelines/([^/]+)/run$"), "_handle_pipeline_run"),
    (re.compile(r"^/api/pipelines/([^/]+)/stop$"), "_handle_pipeline_stop"),
    (re.compile(r"^/api/pipelines/([^/]+)/update$"), "_handle_update_pipeline"),
    (re.compile(r"^/api/pipelines/([^/]+)/reset$"), "_handle_pipeline_reset"),
    (re.compile(r"^/api/projects/([^/]+)$"), "_handle_update_project"),
    (re.compile(r"^/api/jobs/(\w+)/rewind$"), "_handle_job_rewind"),
    (re.compile(r"^/api/presets/([^/]+)$"), "_handle_update_preset"),
    (re.compile(r"^/api/goals/([^/]+)/update$"), "_handle_update_goal"),
    (re.compile(r"^/api/goals/([^/]+)/execute$"), "_handle_execute_goal"),
]

_DELETE_PARAM_ROUTES = [
    (re.compile(r"^/api/suggestions/([^/]+)$"), "_handle_delete_suggestion"),
    (re.compile(r"^/api/pipelines/([^/]+)$"), "_handle_delete_pipeline"),
    (re.compile(r"^/api/projects/([^/]+)$"), "_handle_remove_project"),
    (re.compile(r"^/api/jobs/(\w+)$"), "_handle_delete_job"),
    (re.compile(r"^/api/presets/([^/]+)$"), "_handle_delete_preset"),
    (re.compile(r"^/api/goals/([^/]+)$"), "_handle_cancel_goal"),
]

# 핫 리로드 대상 모듈
_HOT_MODULES = [jobs, checkpoint, _projects_mod, _pipeline_mod, _webhook_mod, _audit_mod, _suggestions_mod, _presets_mod, _goals_mod]


def _hot_reload():
    for mod in _HOT_MODULES:
        try:
            importlib.reload(mod)
        except Exception as e:
            sys.stderr.write(f"  [HOT_RELOAD] {mod.__name__} 리로드 실패: {e}\n")


class ControllerHandler(
    JobHandlerMixin,
    SessionHandlerMixin,
    FsHandlerMixin,
    ProjectHandlerMixin,
    PipelineHandlerMixin,
    SuggestionHandlerMixin,
    PresetHandlerMixin,
    GoalHandlerMixin,
    MiscHandlerMixin,
    ResponseMixin,
    SecurityMixin,
    StaticServeMixin,
    http.server.BaseHTTPRequestHandler,
):
    """Controller REST API + 정적 파일 서빙 핸들러"""

    def log_message(self, format, *args):
        sys.stderr.write(f"  [{self.log_date_time_string()}] {format % args}\n")

    def send_response(self, code, message=None):
        self._response_code = code
        super().send_response(code, message)

    def _audit_log(self):
        if not hasattr(self, '_req_start'):
            return
        duration_ms = (time.time() - self._req_start) * 1000
        path = urlparse(self.path).path.rstrip("/") or "/"
        client_ip = self.client_address[0] if self.client_address else "unknown"
        status = getattr(self, '_response_code', 0)
        _audit_mod.log_api_call(self.command, path, client_ip, status, duration_ms)

    # ── Mixin 모듈 접근자 (리로드 후에도 최신 참조) ──

    def _jobs_mod(self):    return jobs
    def _ckpt_mod(self):    return checkpoint
    def _projects(self):    return _projects_mod
    def _pipeline(self):    return _pipeline_mod
    def _presets(self):     return _presets_mod

    # ════════════════════════════════════════════════
    #  HTTP 라우팅
    # ════════════════════════════════════════════════

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def _prepare_request(self):
        """공통 요청 전처리: 핫리로드, URL 파싱, 보안 검증. 실패 시 (None, None) 반환."""
        _hot_reload()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not self._check_host():
            return None, None
        if not self._check_auth(path):
            return None, None
        return path, parsed

    def _execute_request(self, dispatcher):
        """공통 요청 실행: 전처리 → 디스패치 → 에러 처리."""
        self._req_start = time.time()
        try:
            path, parsed = self._prepare_request()
            if path is None:
                return
            try:
                dispatcher(path, parsed)
            except json.JSONDecodeError:
                self._error_response("잘못된 JSON 요청 본문입니다", 400, code="INVALID_JSON")
            except (ValueError, TypeError) as e:
                msg = str(e) or "잘못된 요청입니다"
                status = 413 if "최대 크기" in msg else 400
                self._error_response(msg, status, code="INVALID_BODY")
            except Exception as e:
                sys.stderr.write(f"  [ERROR] {self.command} {path}: {e}\n")
                self._error_response("서버 내부 오류가 발생했습니다", 500, code="INTERNAL_ERROR")
        finally:
            self._audit_log()

    def do_GET(self):
        self._execute_request(self._dispatch_get)

    def do_POST(self):
        self._execute_request(self._dispatch_post)

    def do_DELETE(self):
        self._execute_request(self._dispatch_delete)

    def _dispatch_param_routes(self, path, routes):
        for pattern, method_name in routes:
            match = pattern.match(path)
            if match:
                getattr(self, method_name)(*match.groups())
                return True
        return False

    def _dispatch_get(self, path, parsed):
        # 정적 라우트 — 인자 없음
        method = _GET_STATIC_ROUTES.get(path)
        if method:
            return getattr(self, method)()

        # 정적 라우트 — parsed 전달
        method = _GET_PARSED_ROUTES.get(path)
        if method:
            return getattr(self, method)(parsed)

        # 쿼리 파라미터 추출이 필요한 라우트
        qs = parse_qs(parsed.query)
        if path == "/api/jobs":
            return self._handle_jobs(
                cwd_filter=qs.get("cwd", [None])[0],
                page=self._safe_int(qs.get("page", [1])[0], 1),
                limit=self._safe_int(qs.get("limit", [10])[0], 10),
            )
        if path == "/api/sessions":
            return self._handle_sessions(filter_cwd=qs.get("cwd", [None])[0])
        if path == "/api/dirs":
            return self._handle_dirs(qs.get("path", [os.path.expanduser("~")])[0])
        if path == "/api/find-dir":
            return self._handle_find_dir(qs.get("name", [""])[0].strip())
        if path == "/api/pipelines/evolution":
            return self._json_response(self._pipeline().get_evolution_summary())

        # 파라미터 라우트 (정규식 매칭)
        if self._dispatch_param_routes(path, _GET_PARAM_ROUTES):
            return

        if path.startswith("/uploads/"):
            return self._serve_file(UPLOADS_DIR / path[9:], UPLOADS_DIR)

        self._serve_static(parsed.path)

    def _dispatch_post(self, path, parsed):
        # 정적 라우트 — 인자 없음
        method = _POST_STATIC_ROUTES.get(path)
        if method:
            return getattr(self, method)()

        # 특수 라우트
        if path == "/api/pipelines/tick-all":
            return self._json_response(self._pipeline().tick_all())

        # 파라미터 라우트 (정규식 매칭)
        if self._dispatch_param_routes(path, _POST_PARAM_ROUTES):
            return

        self._error_response("알 수 없는 엔드포인트", 404, code="ENDPOINT_NOT_FOUND")

    def _dispatch_delete(self, path, _parsed=None):
        # 정적 라우트 — 인자 없음
        method = _DELETE_STATIC_ROUTES.get(path)
        if method:
            return getattr(self, method)()

        # 파라미터 라우트 (정규식 매칭)
        if self._dispatch_param_routes(path, _DELETE_PARAM_ROUTES):
            return

        self._error_response("알 수 없는 엔드포인트", 404, code="ENDPOINT_NOT_FOUND")

    # 얇은 핸들러 → handler_misc.py MiscHandlerMixin으로 분리됨
