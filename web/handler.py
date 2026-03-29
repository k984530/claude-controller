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
  - handler_goals.py    → GoalHandlerMixin
  - handler_crud.py     → ProjectHandlerMixin, PipelineHandlerMixin, PersonaHandlerMixin
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
from auth import verify_token
import jobs
import checkpoint
import projects as _projects_mod
import pipeline as _pipeline_mod
import personas as _personas_mod
import webhook as _webhook_mod
import audit as _audit_mod

from handler_base import ResponseMixin, SecurityMixin, StaticServeMixin
from handler_jobs import JobHandlerMixin
from handler_sessions import SessionHandlerMixin
from handler_fs import FsHandlerMixin
from handler_goals import GoalHandlerMixin
from handler_crud import ProjectHandlerMixin, PipelineHandlerMixin, PersonaHandlerMixin

# ── 사전 컴파일된 파라미터 라우팅 테이블 ──
_GET_PARAM_ROUTES = [
    (re.compile(r"^/api/goals/([^/]+)$"), "_handle_get_goal"),
    (re.compile(r"^/api/personas/([^/]+)$"), "_handle_get_persona"),
    (re.compile(r"^/api/pipelines/([^/]+)/status$"), "_handle_pipeline_status"),
    (re.compile(r"^/api/pipelines/([^/]+)/history$"), "_handle_pipeline_history"),
    (re.compile(r"^/api/projects/([^/]+)/jobs$"), "_handle_project_jobs"),
    (re.compile(r"^/api/projects/([^/]+)$"), "_handle_get_project"),
    (re.compile(r"^/api/jobs/(\w+)/result$"), "_handle_job_result"),
    (re.compile(r"^/api/jobs/(\w+)/stream$"), "_handle_job_stream"),
    (re.compile(r"^/api/jobs/(\w+)/checkpoints$"), "_handle_job_checkpoints"),
    (re.compile(r"^/api/jobs/(\w+)/diff$"), "_handle_job_diff"),
    (re.compile(r"^/api/session/([a-f0-9-]+)/job$"), "_handle_job_by_session"),
]

_POST_PARAM_ROUTES = [
    (re.compile(r"^/api/goals/([^/]+)/update$"), "_handle_update_goal"),
    (re.compile(r"^/api/goals/([^/]+)/approve$"), "_handle_approve_goal"),
    (re.compile(r"^/api/goals/([^/]+)/plan$"), "_handle_plan_goal"),
    (re.compile(r"^/api/goals/([^/]+)/execute$"), "_handle_execute_goal"),
    (re.compile(r"^/api/personas/([^/]+)/update$"), "_handle_update_persona"),
    (re.compile(r"^/api/pipelines/([^/]+)/run$"), "_handle_pipeline_run"),
    (re.compile(r"^/api/pipelines/([^/]+)/stop$"), "_handle_pipeline_stop"),
    (re.compile(r"^/api/pipelines/([^/]+)/update$"), "_handle_update_pipeline"),
    (re.compile(r"^/api/pipelines/([^/]+)/reset$"), "_handle_pipeline_reset"),
    (re.compile(r"^/api/projects/([^/]+)$"), "_handle_update_project"),
    (re.compile(r"^/api/jobs/(\w+)/rewind$"), "_handle_job_rewind"),
]

_DELETE_PARAM_ROUTES = [
    (re.compile(r"^/api/goals/([^/]+)$"), "_handle_cancel_goal"),
    (re.compile(r"^/api/personas/([^/]+)$"), "_handle_delete_persona"),
    (re.compile(r"^/api/pipelines/([^/]+)$"), "_handle_delete_pipeline"),
    (re.compile(r"^/api/projects/([^/]+)$"), "_handle_remove_project"),
    (re.compile(r"^/api/jobs/(\w+)$"), "_handle_delete_job"),
]

# 핫 리로드 대상 모듈
_HOT_MODULES = [jobs, checkpoint, _projects_mod, _pipeline_mod, _personas_mod, _webhook_mod, _audit_mod]


def _hot_reload():
    for mod in _HOT_MODULES:
        try:
            importlib.reload(mod)
        except Exception:
            pass


class ControllerHandler(
    JobHandlerMixin,
    SessionHandlerMixin,
    FsHandlerMixin,
    GoalHandlerMixin,
    ProjectHandlerMixin,
    PipelineHandlerMixin,
    PersonaHandlerMixin,
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
    def _personas(self):    return _personas_mod

    # ════════════════════════════════════════════════
    #  HTTP 라우팅
    # ════════════════════════════════════════════════

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        self._req_start = time.time()
        try:
            self._do_get_inner()
        finally:
            self._audit_log()

    def _do_get_inner(self):
        _hot_reload()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not self._check_host():
            return
        if not self._check_auth(path):
            return

        try:
            self._dispatch_get(path, parsed)
        except (ValueError, TypeError) as e:
            msg = str(e) or "잘못된 요청 파라미터입니다"
            self._error_response(msg, 400, code="INVALID_PARAM")
        except Exception as e:
            sys.stderr.write(f"  [ERROR] GET {path}: {e}\n")
            self._error_response("서버 내부 오류가 발생했습니다", 500, code="INTERNAL_ERROR")

    def _dispatch_param_routes(self, path, routes):
        for pattern, method_name in routes:
            match = pattern.match(path)
            if match:
                getattr(self, method_name)(*match.groups())
                return True
        return False

    def _dispatch_get(self, path, parsed):
        if path == "/api/health":
            return self._handle_health()
        if path == "/api/audit":
            return self._handle_audit(parsed)
        if path == "/api/auth/verify":
            return self._handle_auth_verify()
        if path == "/api/status":
            return self._handle_status()
        if path == "/api/stats":
            return self._handle_stats(parsed)
        if path == "/api/jobs":
            qs = parse_qs(parsed.query)
            return self._handle_jobs(
                cwd_filter=qs.get("cwd", [None])[0],
                page=self._safe_int(qs.get("page", [1])[0], 1),
                limit=self._safe_int(qs.get("limit", [10])[0], 10),
            )
        if path == "/api/sessions":
            qs = parse_qs(parsed.query)
            return self._handle_sessions(filter_cwd=qs.get("cwd", [None])[0])
        if path == "/api/config":
            return self._handle_get_config()
        if path == "/api/recent-dirs":
            return self._handle_get_recent_dirs()
        if path == "/api/dirs":
            qs = parse_qs(parsed.query)
            return self._handle_dirs(qs.get("path", [os.path.expanduser("~")])[0])
        if path == "/api/projects":
            return self._handle_list_projects()
        if path == "/api/goals":
            return self._handle_list_goals(parsed)
        if path == "/api/personas":
            return self._json_response(self._personas().list_personas())
        if path == "/api/pipelines":
            return self._handle_list_pipelines()
        if path == "/api/pipelines/evolution":
            return self._json_response(self._pipeline().get_evolution_summary())

        if self._dispatch_param_routes(path, _GET_PARAM_ROUTES):
            return

        if path.startswith("/uploads/"):
            return self._serve_file(UPLOADS_DIR / path[9:], UPLOADS_DIR)

        self._serve_static(parsed.path)

    def do_POST(self):
        self._req_start = time.time()
        try:
            self._do_post_inner()
        finally:
            self._audit_log()

    def _do_post_inner(self):
        _hot_reload()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not self._check_host():
            return
        if not self._check_auth(path):
            return

        try:
            self._dispatch_post(path, parsed)
        except json.JSONDecodeError:
            self._error_response("잘못된 JSON 요청 본문입니다", 400, code="INVALID_JSON")
        except ValueError as e:
            msg = str(e) or "잘못된 요청 본문입니다"
            status = 413 if "최대 크기" in msg else 400
            self._error_response(msg, status, code="INVALID_BODY")
        except Exception as e:
            sys.stderr.write(f"  [ERROR] POST {path}: {e}\n")
            self._error_response("서버 내부 오류가 발생했습니다", 500, code="INTERNAL_ERROR")

    def _dispatch_post(self, path, parsed):
        if path == "/api/auth/verify":
            return self._handle_auth_verify()
        if path == "/api/send":
            return self._handle_send()
        if path == "/api/upload":
            return self._handle_upload()
        if path == "/api/service/start":
            return self._handle_service_start()
        if path == "/api/service/stop":
            return self._handle_service_stop()
        if path == "/api/config":
            return self._handle_save_config()
        if path == "/api/recent-dirs":
            return self._handle_save_recent_dirs()
        if path == "/api/mkdir":
            return self._handle_mkdir()
        if path == "/api/projects":
            return self._handle_add_project()
        if path == "/api/projects/create":
            return self._handle_create_project()
        if path == "/api/goals":
            return self._handle_create_goal()
        if path == "/api/personas":
            return self._handle_create_persona()
        if path == "/api/pipelines":
            return self._handle_create_pipeline()
        if path == "/api/pipelines/tick-all":
            return self._json_response(self._pipeline().tick_all())
        if path == "/api/webhooks/test":
            return self._handle_webhook_test()
        if path == "/api/logs/cleanup":
            return self._handle_logs_cleanup()

        if self._dispatch_param_routes(path, _POST_PARAM_ROUTES):
            return

        self._error_response("알 수 없는 엔드포인트", 404, code="ENDPOINT_NOT_FOUND")

    def do_DELETE(self):
        self._req_start = time.time()
        try:
            self._do_delete_inner()
        finally:
            self._audit_log()

    def _do_delete_inner(self):
        _hot_reload()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not self._check_host():
            return
        if not self._check_auth(path):
            return

        try:
            self._dispatch_delete(path)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            msg = str(e) or "잘못된 요청입니다"
            self._error_response(msg, 400, code="INVALID_REQUEST")
        except Exception as e:
            sys.stderr.write(f"  [ERROR] DELETE {path}: {e}\n")
            self._error_response("서버 내부 오류가 발생했습니다", 500, code="INTERNAL_ERROR")

    def _dispatch_delete(self, path):
        if path == "/api/jobs":
            return self._handle_delete_completed_jobs()

        if self._dispatch_param_routes(path, _DELETE_PARAM_ROUTES):
            return

        self._error_response("알 수 없는 엔드포인트", 404, code="ENDPOINT_NOT_FOUND")

    # ════════════════════════════════════════════════
    #  얇은 핸들러 (라우팅과 함께 유지)
    # ════════════════════════════════════════════════

    def _handle_auth_verify(self):
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if verify_token(token):
                return self._json_response({"valid": True})
        self._json_response({"valid": False}, 401)

    def _handle_stats(self, parsed):
        qs = parse_qs(parsed.query)
        period = qs.get("period", ["all"])[0]
        now = time.time()

        period_map = {"day": 86400, "week": 604800, "month": 2592000}
        if period in period_map:
            from_ts = now - period_map[period]
        elif period == "all":
            from_ts = None
        else:
            from_ts = self._parse_ts(qs.get("from", [None])[0])

        to_ts = self._parse_ts(qs.get("to", [None])[0]) or now
        self._json_response(self._jobs_mod().get_stats(from_ts=from_ts, to_ts=to_ts))

    @staticmethod
    def _parse_ts(value):
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return time.mktime(time.strptime(value, fmt))
            except ValueError:
                continue
        return None

    def _handle_status(self):
        from utils import is_service_running
        from config import FIFO_PATH, CONTROLLER_DIR
        running, _ = is_service_running()
        self._json_response({
            "running": running,
            "fifo": str(FIFO_PATH),
            "controller_dir": str(CONTROLLER_DIR),
        })

    def _handle_health(self):
        import config as _cfg
        from health import collect_health
        payload, http_status = collect_health(_cfg)
        self._json_response(payload, http_status)

    def _handle_audit(self, parsed):
        qs = parse_qs(parsed.query)
        result = _audit_mod.search_audit(
            from_ts=self._parse_ts(qs.get("from", [None])[0]),
            to_ts=self._parse_ts(qs.get("to", [None])[0]),
            method=qs.get("method", [None])[0],
            path_contains=qs.get("path", [None])[0],
            ip=qs.get("ip", [None])[0],
            status=qs.get("status", [None])[0],
            limit=min(self._safe_int(qs.get("limit", [100])[0], 100), 1000),
            offset=self._safe_int(qs.get("offset", [0])[0], 0),
        )
        self._json_response(result)

    def _handle_webhook_test(self):
        result = _webhook_mod.deliver_webhook("test-0000", "done")
        if result is None:
            return self._error_response(
                "webhook_url이 설정되지 않았습니다. 설정에서 URL을 지정하세요.",
                400, code="WEBHOOK_NOT_CONFIGURED")
        marker = _webhook_mod._WEBHOOK_SENT_DIR / "test-0000_done"
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass
        self._json_response(result)

    def _handle_logs_cleanup(self):
        body = self._read_body() or {}
        retention_days = body.get("retention_days", 30)
        try:
            retention_days = int(retention_days)
            if retention_days < 1:
                retention_days = 1
        except (ValueError, TypeError):
            retention_days = 30
        result = self._jobs_mod().cleanup_old_jobs(retention_days=retention_days)
        self._json_response(result)
