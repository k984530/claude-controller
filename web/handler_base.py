"""
Controller Handler — 기반 Mixin 모듈

ControllerHandler에서 분리된 공통 기능:
  - ResponseMixin:     JSON 응답, 에러 응답, 요청 본문 읽기
  - SecurityMixin:     Host 검증, CORS, 토큰 인증
  - StaticServeMixin:  정적 파일/업로드 파일 서빙, MIME 타입
"""

import json
import os
from urllib.parse import urlparse, parse_qs

from config import (
    STATIC_DIR, UPLOADS_DIR,
    ALLOWED_ORIGINS, ALLOWED_HOSTS,
    AUTH_REQUIRED, AUTH_EXEMPT_PREFIXES, AUTH_EXEMPT_PATHS,
)
from auth import verify_token


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


class ResponseMixin:
    """JSON 응답·에러 응답·요청 본문 읽기 헬퍼."""

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

    def _read_body(self, allow_list=False):
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
        if not isinstance(data, dict) and not (allow_list and isinstance(data, list)):
            raise ValueError("요청 본문은 JSON 객체여야 합니다")
        return data

    @staticmethod
    def _safe_int(value, default=0):
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default


class SecurityMixin:
    """Host 검증, CORS, 토큰 인증 미들웨어."""

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


class StaticServeMixin:
    """정적 파일 서빙 + MIME 타입 처리."""

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

    def _serve_static(self, url_path):
        if url_path in ("/", ""):
            url_path = "/index.html"
        self._serve_file(STATIC_DIR / url_path.lstrip("/"), STATIC_DIR)
