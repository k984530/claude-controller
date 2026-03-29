"""
Controller Service — HTTP REST API 핸들러

보안 계층:
  1. Host 헤더 검증 — DNS Rebinding 방지
  2. Origin 검증 — CORS를 허용된 출처로 제한
  3. 토큰 인증 — API 요청마다 Authorization 헤더 필수

핸들러 구현은 Mixin 클래스로 분리:
  - handler_jobs.py     → JobHandlerMixin (작업 CRUD, 전송, 스트림)
  - handler_sessions.py → SessionHandlerMixin (세션 목록)
  - handler_fs.py       → FsHandlerMixin (설정, 디렉토리, 최근 경로)
"""

import http.server
import importlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from config import (
    STATIC_DIR, UPLOADS_DIR,
    ALLOWED_ORIGINS, ALLOWED_HOSTS,
    AUTH_REQUIRED, AUTH_EXEMPT_PREFIXES, AUTH_EXEMPT_PATHS,
)
from auth import verify_token
import jobs
import checkpoint
import projects as _projects_mod
import pipeline as _pipeline_mod
import personas as _personas_mod
import webhook as _webhook_mod
import audit as _audit_mod

from handler_jobs import JobHandlerMixin
from handler_sessions import SessionHandlerMixin
from handler_fs import FsHandlerMixin
from handler_goals import GoalHandlerMixin
from handler_memory import MemoryHandlerMixin

# HTTP 상태 → 기본 에러 코드 매핑
_STATUS_TO_CODE = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}

# 핫 리로드 대상 모듈
_HOT_MODULES = [jobs, checkpoint, _projects_mod, _pipeline_mod, _personas_mod, _webhook_mod, _audit_mod]


def _hot_reload():
    for mod in _HOT_MODULES:
        try:
            importlib.reload(mod)
        except Exception:
            pass


# MIME 타입 맵
MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".json": "application/json", ".xml": "application/xml",
    ".yaml": "text/yaml", ".yml": "text/yaml", ".toml": "text/plain",
    ".py": "text/x-python", ".js": "application/javascript",
    ".ts": "text/plain", ".jsx": "text/plain", ".tsx": "text/plain",
    ".html": "text/html", ".css": "text/css", ".scss": "text/plain",
    ".sh": "text/x-shellscript", ".bash": "text/x-shellscript",
    ".zsh": "text/plain", ".fish": "text/plain",
    ".c": "text/plain", ".cpp": "text/plain", ".h": "text/plain",
    ".hpp": "text/plain", ".java": "text/plain", ".kt": "text/plain",
    ".go": "text/plain", ".rs": "text/plain", ".rb": "text/plain",
    ".swift": "text/plain", ".m": "text/plain", ".r": "text/plain",
    ".sql": "text/plain", ".graphql": "text/plain",
    ".log": "text/plain", ".env": "text/plain",
    ".conf": "text/plain", ".ini": "text/plain", ".cfg": "text/plain",
    ".pdf": "application/pdf",
    ".doc": "application/msword", ".docx": "application/msword",
    ".xls": "application/vnd.ms-excel", ".xlsx": "application/vnd.ms-excel",
    ".pptx": "application/vnd.ms-powerpoint",
    ".zip": "application/zip", ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".svg": "image/svg+xml", ".ico": "image/x-icon",
}


class ControllerHandler(
    JobHandlerMixin,
    SessionHandlerMixin,
    FsHandlerMixin,
    GoalHandlerMixin,
    MemoryHandlerMixin,
    http.server.BaseHTTPRequestHandler,
):
    """Controller REST API + 정적 파일 서빙 핸들러"""

    def log_message(self, format, *args):
        sys.stderr.write(f"  [{self.log_date_time_string()}] {format % args}\n")

    def send_response(self, code, message=None):
        self._response_code = code
        super().send_response(code, message)

    def _audit_log(self):
        """감사 로그 기록 — do_GET/POST/DELETE의 finally에서 호출."""
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
    #  보안 미들웨어
    # ════════════════════════════════════════════════

    def _get_origin(self):
        return self.headers.get("Origin", "")

    def _set_cors_headers(self):
        origin = self._get_origin()
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif not origin:
            self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Credentials", "true")

    def _check_host(self) -> bool:
        host = self.headers.get("Host", "")
        hostname = host.split(":")[0] if ":" in host else host
        if hostname not in ALLOWED_HOSTS:
            self._send_forbidden("잘못된 Host 헤더")
            return False
        return True

    def _check_auth(self, path: str) -> bool:
        if not AUTH_REQUIRED:
            return True
        if path in AUTH_EXEMPT_PATHS:
            return True
        for prefix in AUTH_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return True
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if verify_token(token):
                return True
        # EventSource는 커스텀 헤더를 보낼 수 없으므로 query param도 확인
        qs = parse_qs(urlparse(self.path).query)
        token_param = qs.get("token", [None])[0]
        if token_param and verify_token(token_param):
            return True
        self._send_unauthorized()
        return False

    def _send_forbidden(self, message="Forbidden"):
        body = json.dumps({"error": {"code": "FORBIDDEN", "message": message}}, ensure_ascii=False).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_unauthorized(self):
        body = json.dumps({"error": {"code": "AUTH_REQUIRED", "message": "인증이 필요합니다. Authorization 헤더에 토큰을 포함하세요."}}, ensure_ascii=False).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", "Bearer")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ════════════════════════════════════════════════
    #  공통 응답 헬퍼
    # ════════════════════════════════════════════════

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._set_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error_response(self, message, status=400, code=None):
        if code is None:
            code = _STATUS_TO_CODE.get(status, "UNKNOWN_ERROR")
        self._json_response({"error": {"code": code, "message": message}}, status)

    _MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return {}
        if length <= 0:
            return {}
        if length > self._MAX_BODY_SIZE:
            raise ValueError(
                f"요청 본문이 최대 크기를 초과합니다 (최대 {self._MAX_BODY_SIZE // (1024 * 1024)}MB)")
        raw = self.rfile.read(length)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("요청 본문은 JSON 객체여야 합니다")
        return data

    def _serve_file(self, file_path, base_dir):
        try:
            resolved = file_path.resolve()
            base_resolved = str(base_dir.resolve()) + os.sep
            if not str(resolved).startswith(base_resolved):
                return self._error_response("접근 거부", 403, code="ACCESS_DENIED")
        except (ValueError, OSError):
            return self._error_response("잘못된 경로", 400, code="INVALID_PATH")

        if not resolved.exists() or not resolved.is_file():
            return self._error_response("파일을 찾을 수 없습니다", 404, code="FILE_NOT_FOUND")

        ext = resolved.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        if mime.startswith("text/") or mime in ("application/json", "application/javascript"):
            mime += "; charset=utf-8"

        try:
            data = resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self._set_cors_headers()
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._error_response("파일 읽기 실패", 500, code="FILE_READ_ERROR")

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
        if path == "/api/personas":
            return self._json_response(self._personas().list_personas())
        if path == "/api/pipelines":
            return self._handle_list_pipelines()
        if path == "/api/pipelines/evolution":
            return self._json_response(self._pipeline().get_evolution_summary())
        if path == "/api/goals":
            return self._handle_list_goals(parsed)
        if path == "/api/memory":
            return self._handle_list_memory(parsed)

        match = re.match(r"^/api/goals/([^/]+)$", path)
        if match:
            return self._handle_get_goal(match.group(1))
        match = re.match(r"^/api/memory/([^/]+)$", path)
        if match:
            return self._handle_get_memory(match.group(1))
        match = re.match(r"^/api/personas/([^/]+)$", path)
        if match:
            return self._handle_get_persona(match.group(1))
        match = re.match(r"^/api/pipelines/([^/]+)/status$", path)
        if match:
            return self._handle_pipeline_status(match.group(1))
        match = re.match(r"^/api/pipelines/([^/]+)/history$", path)
        if match:
            return self._handle_pipeline_history(match.group(1))
        match = re.match(r"^/api/projects/([^/]+)/jobs$", path)
        if match:
            return self._handle_project_jobs(match.group(1))
        match = re.match(r"^/api/projects/([^/]+)$", path)
        if match:
            return self._handle_get_project(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)/result$", path)
        if match:
            return self._handle_job_result(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)/stream$", path)
        if match:
            return self._handle_job_stream(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)/checkpoints$", path)
        if match:
            return self._handle_job_checkpoints(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)/diff$", path)
        if match:
            return self._handle_job_diff(match.group(1))
        match = re.match(r"^/api/session/([a-f0-9-]+)/job$", path)
        if match:
            return self._handle_job_by_session(match.group(1))
        match = re.match(r"^/uploads/(.+)$", path)
        if match:
            return self._serve_file(UPLOADS_DIR / match.group(1), UPLOADS_DIR)

        self._serve_static(parsed.path)

    @staticmethod
    def _safe_int(value, default=0):
        """query string 값을 안전하게 int로 변환한다. 실패 시 default 반환."""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

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
        if path == "/api/goals":
            return self._handle_create_goal()
        if path == "/api/memory":
            return self._handle_create_memory()

        match = re.match(r"^/api/goals/([^/]+)/update$", path)
        if match:
            return self._handle_update_goal(match.group(1))
        match = re.match(r"^/api/goals/([^/]+)/approve$", path)
        if match:
            return self._handle_approve_goal(match.group(1))
        match = re.match(r"^/api/memory/([^/]+)/update$", path)
        if match:
            return self._handle_update_memory(match.group(1))
        match = re.match(r"^/api/personas/([^/]+)/update$", path)
        if match:
            return self._handle_update_persona(match.group(1))
        match = re.match(r"^/api/pipelines/([^/]+)/run$", path)
        if match:
            return self._handle_pipeline_run(match.group(1))
        match = re.match(r"^/api/pipelines/([^/]+)/stop$", path)
        if match:
            return self._handle_pipeline_stop(match.group(1))
        match = re.match(r"^/api/pipelines/([^/]+)/update$", path)
        if match:
            return self._handle_update_pipeline(match.group(1))
        match = re.match(r"^/api/pipelines/([^/]+)/reset$", path)
        if match:
            return self._handle_pipeline_reset(match.group(1))
        match = re.match(r"^/api/projects/([^/]+)$", path)
        if match:
            return self._handle_update_project(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)/rewind$", path)
        if match:
            return self._handle_job_rewind(match.group(1))

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
        match = re.match(r"^/api/goals/([^/]+)$", path)
        if match:
            return self._handle_cancel_goal(match.group(1))
        match = re.match(r"^/api/memory/([^/]+)$", path)
        if match:
            return self._handle_delete_memory(match.group(1))
        match = re.match(r"^/api/personas/([^/]+)$", path)
        if match:
            return self._handle_delete_persona(match.group(1))
        match = re.match(r"^/api/pipelines/([^/]+)$", path)
        if match:
            return self._handle_delete_pipeline(match.group(1))
        match = re.match(r"^/api/projects/([^/]+)$", path)
        if match:
            return self._handle_remove_project(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)$", path)
        if match:
            return self._handle_delete_job(match.group(1))
        if path == "/api/jobs":
            return self._handle_delete_completed_jobs()

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

        # period 파라미터: day, week, month, all (기본값)
        period = qs.get("period", ["all"])[0]
        now = time.time()

        period_map = {"day": 86400, "week": 604800, "month": 2592000}
        if period in period_map:
            from_ts = now - period_map[period]
        elif period == "all":
            from_ts = None
        else:
            # from/to 커스텀 범위 지원 (ISO 날짜 또는 Unix timestamp)
            from_ts = self._parse_ts(qs.get("from", [None])[0])

        to_ts = self._parse_ts(qs.get("to", [None])[0]) or now

        self._json_response(self._jobs_mod().get_stats(from_ts=from_ts, to_ts=to_ts))

    @staticmethod
    def _parse_ts(value):
        """문자열을 Unix timestamp로 변환. ISO 날짜 또는 숫자 문자열 지원."""
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
        from config import FIFO_PATH
        running, _ = is_service_running()
        self._json_response({"running": running, "fifo": str(FIFO_PATH)})

    def _handle_health(self):
        from utils import is_service_running
        from config import FIFO_PATH, LOGS_DIR, PID_FILE, SESSIONS_DIR

        # ── 서비스 상태 ──
        running, pid = is_service_running()
        uptime_seconds = None
        if running and PID_FILE.exists():
            try:
                uptime_seconds = int(time.time() - PID_FILE.stat().st_mtime)
            except OSError:
                pass

        # ── FIFO 상태 ──
        fifo_exists = FIFO_PATH.exists()
        fifo_writable = False
        if fifo_exists:
            fifo_writable = os.access(str(FIFO_PATH), os.W_OK)

        # ── 작업 통계 (meta 파일 직접 스캔 — get_all_jobs()보다 가볍다) ──
        active = 0
        succeeded = 0
        failed = 0
        total = 0
        if LOGS_DIR.exists():
            for mf in LOGS_DIR.glob("job_*.meta"):
                total += 1
                try:
                    content = mf.read_text()
                    for line in content.splitlines():
                        if line.startswith("STATUS="):
                            val = line[7:].strip().strip("'\"")
                            if val == "running":
                                active += 1
                            elif val == "done":
                                succeeded += 1
                            elif val == "failed":
                                failed += 1
                            break
                except OSError:
                    pass

        # ── 디스크 사용량 ──
        logs_size_bytes = 0
        if LOGS_DIR.exists():
            for f in LOGS_DIR.iterdir():
                try:
                    logs_size_bytes += f.stat().st_size
                except OSError:
                    pass

        disk_total, disk_used, disk_free = shutil.disk_usage("/")

        # ── 워치독 상태 ──
        from config import CONTROLLER_DIR as _cdir
        wd_pid_file = _cdir / "service" / "watchdog.pid"
        wd_state_file = _cdir / "data" / "watchdog_state.json"
        wd_running = False
        wd_info = {}
        if wd_pid_file.exists():
            try:
                wd_pid = int(wd_pid_file.read_text().strip())
                os.kill(wd_pid, 0)
                wd_running = True
            except (ValueError, OSError):
                pass
        if wd_state_file.exists():
            try:
                wd_info = json.loads(wd_state_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # ── 전체 상태 판정 ──
        if running and fifo_exists and fifo_writable:
            status = "healthy"
        elif running:
            status = "degraded"
        else:
            status = "unhealthy"

        http_status = 503 if status == "unhealthy" else 200

        self._json_response({
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": {
                "running": running,
                "pid": pid,
                "uptime_seconds": uptime_seconds,
            },
            "fifo": {
                "exists": fifo_exists,
                "writable": fifo_writable,
            },
            "jobs": {
                "active": active,
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
            },
            "disk": {
                "logs_size_mb": round(logs_size_bytes / (1024 * 1024), 2),
                "disk_free_gb": round(disk_free / (1024 ** 3), 2),
            },
            "watchdog": {
                "running": wd_running,
                "restart_count": wd_info.get("restart_count", 0),
                "last_restart": wd_info.get("last_restart", ""),
                "status": wd_info.get("status", "unknown"),
            },
        }, http_status)

    # ── 감사 로그 ──

    def _handle_audit(self, parsed):
        """감사 로그 검색 — GET /api/audit?from=...&to=...&method=...&path=...&ip=...&status=...&limit=...&offset=..."""
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

    # ── 웹훅 ──

    def _handle_webhook_test(self):
        """설정된 webhook_url로 테스트 페이로드를 전송한다."""
        result = _webhook_mod.deliver_webhook("test-0000", "done")
        if result is None:
            return self._error_response(
                "webhook_url이 설정되지 않았습니다. 설정에서 URL을 지정하세요.",
                400, code="WEBHOOK_NOT_CONFIGURED")
        # 테스트 전송의 중복방지 마커 제거
        marker = _webhook_mod._WEBHOOK_SENT_DIR / "test-0000_done"
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass
        self._json_response(result)

    def _handle_logs_cleanup(self):
        """보존 기간이 지난 완료/실패 작업 파일을 삭제한다."""
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

    # ── 프로젝트 (얇은 위임) ──

    def _handle_list_projects(self):
        self._json_response(self._projects().list_projects())

    def _handle_get_project(self, project_id):
        project, err = self._projects().get_project(project_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(project)

    def _handle_project_jobs(self, project_id):
        project, err = self._projects().get_project(project_id)
        if err:
            return self._error_response(err, 404, code="PROJECT_NOT_FOUND")
        jobs = self._jobs_mod().get_all_jobs(cwd_filter=project["path"])
        self._json_response({"project": project, "jobs": jobs})

    def _handle_add_project(self):
        body = self._read_body()
        path = body.get("path", "").strip()
        if not path:
            return self._error_response("path 필드가 필요합니다", code="MISSING_FIELD")
        project, err = self._projects().add_project(
            path, name=body.get("name", "").strip(), description=body.get("description", "").strip())
        if err:
            self._error_response(err, 409, code="ALREADY_EXISTS")
        else:
            self._json_response(project, 201)

    def _handle_create_project(self):
        body = self._read_body()
        path = body.get("path", "").strip()
        if not path:
            return self._error_response("path 필드가 필요합니다", code="MISSING_FIELD")
        project, err = self._projects().create_project(
            path, name=body.get("name", "").strip(),
            description=body.get("description", "").strip(),
            init_git=body.get("init_git", True))
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(project, 201)

    def _handle_update_project(self, project_id):
        body = self._read_body()
        project, err = self._projects().update_project(
            project_id, name=body.get("name"), description=body.get("description"))
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(project)

    def _handle_remove_project(self, project_id):
        project, err = self._projects().remove_project(project_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response({"removed": True, "project": project})

    # ── 파이프라인 (얇은 위임) ──

    def _handle_list_pipelines(self):
        self._json_response(self._pipeline().list_pipelines())

    def _handle_pipeline_status(self, pipe_id):
        result, err = self._pipeline().get_pipeline_status(pipe_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(result)

    def _handle_pipeline_history(self, pipe_id):
        result, err = self._pipeline().get_pipeline_history(pipe_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(result)

    def _handle_create_pipeline(self):
        body = self._read_body()
        path = body.get("project_path", "").strip()
        command = body.get("command", "").strip()
        if not path or not command:
            return self._error_response("project_path와 command 필드가 필요합니다", code="MISSING_FIELD")
        result, err = self._pipeline().create_pipeline(
            path, command=command,
            interval=body.get("interval", "").strip(),
            name=body.get("name", "").strip(),
            on_complete=body.get("on_complete", "").strip())
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result, 201)

    def _handle_pipeline_run(self, pipe_id):
        body = self._read_body()
        if body.get("force"):
            result, err = self._pipeline().force_run(pipe_id)
        else:
            result, err = self._pipeline().run_next(pipe_id)
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    def _handle_pipeline_stop(self, pipe_id):
        result, err = self._pipeline().stop_pipeline(pipe_id)
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    def _handle_update_pipeline(self, pipe_id):
        body = self._read_body()
        result, err = self._pipeline().update_pipeline(
            pipe_id,
            command=body.get("command"),
            interval=body.get("interval"),
            name=body.get("name"),
            on_complete=body.get("on_complete"),
        )
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    def _handle_pipeline_reset(self, pipe_id):
        body = self._read_body()
        result, err = self._pipeline().reset_phase(pipe_id, phase=body.get("phase"))
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    # ── Persona 핸들러 ──

    def _handle_get_persona(self, persona_id):
        result, err = self._personas().get_persona(persona_id)
        if err:
            self._error_response(err, 404, code="PERSONA_NOT_FOUND")
        else:
            self._json_response(result)

    def _handle_create_persona(self):
        body = self._read_body()
        name = body.get("name", "").strip()
        if not name:
            return self._error_response("name 필드가 필요합니다", code="MISSING_FIELD")
        result, err = self._personas().create_persona(
            name=name,
            role=body.get("role", "custom"),
            description=body.get("description", ""),
            system_prompt=body.get("system_prompt", ""),
            icon=body.get("icon", "user"),
            color=body.get("color", "#6366f1"),
        )
        self._json_response(result, 201)

    def _handle_update_persona(self, persona_id):
        body = self._read_body()
        result, err = self._personas().update_persona(persona_id, body)
        if err:
            status = 403 if "내장" in err else 404
            self._error_response(err, status)
        else:
            self._json_response(result)

    def _handle_delete_persona(self, persona_id):
        result, err = self._personas().delete_persona(persona_id)
        if err:
            status = 403 if "내장" in err else 404
            self._error_response(err, status)
        else:
            self._json_response({"deleted": True, "persona": result})

    def _handle_delete_pipeline(self, pipe_id):
        result, err = self._pipeline().delete_pipeline(pipe_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response({"deleted": True, "pipeline": result})

    def _serve_static(self, url_path):
        if url_path in ("/", ""):
            url_path = "/index.html"
        self._serve_file(STATIC_DIR / url_path.lstrip("/"), STATIC_DIR)
