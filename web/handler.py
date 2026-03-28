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
import sys
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

from handler_jobs import JobHandlerMixin
from handler_sessions import SessionHandlerMixin
from handler_fs import FsHandlerMixin

# 핫 리로드 대상 모듈
_HOT_MODULES = [jobs, checkpoint, _projects_mod, _pipeline_mod]


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
    http.server.BaseHTTPRequestHandler,
):
    """Controller REST API + 정적 파일 서빙 핸들러"""

    def log_message(self, format, *args):
        sys.stderr.write(f"  [{self.log_date_time_string()}] {format % args}\n")

    # ── Mixin 모듈 접근자 (리로드 후에도 최신 참조) ──

    def _jobs_mod(self):    return jobs
    def _ckpt_mod(self):    return checkpoint
    def _projects(self):    return _projects_mod
    def _pipeline(self):    return _pipeline_mod

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
        self._send_unauthorized()
        return False

    def _send_forbidden(self, message="Forbidden"):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_unauthorized(self):
        body = json.dumps({"error": "인증이 필요합니다. Authorization 헤더에 토큰을 포함하세요."}, ensure_ascii=False).encode("utf-8")
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

    def _error_response(self, message, status=400):
        self._json_response({"error": message}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _serve_file(self, file_path, base_dir):
        try:
            resolved = file_path.resolve()
            if not str(resolved).startswith(str(base_dir.resolve())):
                return self._error_response("접근 거부", 403)
        except (ValueError, OSError):
            return self._error_response("잘못된 경로", 400)

        if not resolved.exists() or not resolved.is_file():
            return self._error_response("파일을 찾을 수 없습니다", 404)

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
            self._error_response("파일 읽기 실패", 500)

    # ════════════════════════════════════════════════
    #  HTTP 라우팅
    # ════════════════════════════════════════════════

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        _hot_reload()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not self._check_host():
            return
        if not self._check_auth(path):
            return

        if path == "/api/auth/verify":
            return self._handle_auth_verify()
        if path == "/api/status":
            return self._handle_status()
        if path == "/api/jobs":
            return self._handle_jobs()
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
        if path == "/api/pipelines":
            return self._handle_list_pipelines()

        match = re.match(r"^/api/pipelines/([^/]+)/status$", path)
        if match:
            return self._handle_pipeline_status(match.group(1))
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
        match = re.match(r"^/api/session/([a-f0-9-]+)/job$", path)
        if match:
            return self._handle_job_by_session(match.group(1))
        match = re.match(r"^/uploads/(.+)$", path)
        if match:
            return self._serve_file(UPLOADS_DIR / match.group(1), UPLOADS_DIR)

        self._serve_static(parsed.path)

    def do_POST(self):
        _hot_reload()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not self._check_host():
            return
        if not self._check_auth(path):
            return

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
        if path == "/api/pipelines":
            return self._handle_create_pipeline()
        if path == "/api/pipelines/tick-all":
            return self._json_response(self._pipeline().tick_all())

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

        self._error_response("알 수 없는 엔드포인트", 404)

    def do_DELETE(self):
        _hot_reload()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not self._check_host():
            return
        if not self._check_auth(path):
            return

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

        self._error_response("알 수 없는 엔드포인트", 404)

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

    def _handle_status(self):
        from utils import is_service_running
        from config import FIFO_PATH
        running, _ = is_service_running()
        self._json_response({"running": running, "fifo": str(FIFO_PATH)})

    # ── 프로젝트 (얇은 위임) ──

    def _handle_list_projects(self):
        self._json_response(self._projects().list_projects())

    def _handle_get_project(self, project_id):
        project, err = self._projects().get_project(project_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(project)

    def _handle_add_project(self):
        body = self._read_body()
        path = body.get("path", "").strip()
        if not path:
            return self._error_response("path 필드가 필요합니다")
        project, err = self._projects().add_project(
            path, name=body.get("name", "").strip(), description=body.get("description", "").strip())
        if err:
            self._error_response(err, 409)
        else:
            self._json_response(project, 201)

    def _handle_create_project(self):
        body = self._read_body()
        path = body.get("path", "").strip()
        if not path:
            return self._error_response("path 필드가 필요합니다")
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

    def _handle_create_pipeline(self):
        body = self._read_body()
        path = body.get("project_path", "").strip()
        command = body.get("command", "").strip()
        if not path or not command:
            return self._error_response("project_path와 command 필드가 필요합니다")
        result, err = self._pipeline().create_pipeline(
            path, command=command,
            interval=body.get("interval", "").strip(),
            name=body.get("name", "").strip())
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
