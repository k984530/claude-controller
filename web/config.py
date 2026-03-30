"""
Controller Service — 경로 및 설정 상수
"""

import os
from pathlib import Path

# ══════════════════════════════════════════════════════════════
#  경로 설정 — web/ 안에 위치하므로 parent = controller/
# ══════════════════════════════════════════════════════════════

WEB_DIR = Path(__file__).resolve().parent
CONTROLLER_DIR = WEB_DIR.parent
STATIC_DIR = WEB_DIR / "static"
FIFO_PATH = CONTROLLER_DIR / "queue" / "controller.pipe"
PID_FILE = CONTROLLER_DIR / "service" / "controller.pid"
LOGS_DIR = CONTROLLER_DIR / "logs"
UPLOADS_DIR = CONTROLLER_DIR / "uploads"
DATA_DIR = CONTROLLER_DIR / "data"
RECENT_DIRS_FILE = DATA_DIR / "recent_dirs.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SKILLS_FILE = DATA_DIR / "skills.json"
GOALS_DIR = DATA_DIR / "goals"
PRESETS_FILE = DATA_DIR / "presets.json"
SERVICE_SCRIPT = CONTROLLER_DIR / "service" / "controller.sh"
SESSIONS_DIR = CONTROLLER_DIR / "sessions"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

PORT = int(os.environ.get("PORT", 8420))

# ══════════════════════════════════════════════════════════════
#  보안 설정
# ══════════════════════════════════════════════════════════════

# 허용된 Origin 목록 (CORS)
# 환경변수 ALLOWED_ORIGINS로 오버라이드 가능 (쉼표 구분)
_DEFAULT_ORIGINS = [
    "http://localhost:8420",
    "https://localhost:8420",
]
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in
    os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
] or _DEFAULT_ORIGINS

# 허용된 Host 헤더 (DNS Rebinding 방지)
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"}

# 토큰 인증 필수 여부
# false: CORS + Host 검증만으로 보안 (기본값, 자동 연결에 적합)
# true: 모든 API 요청에 Authorization: Bearer <token> 필수
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "false").lower() == "true"

# 인증 면제 경로 (AUTH_REQUIRED=true일 때만 적용)
AUTH_EXEMPT_PREFIXES = ("/static/", "/uploads/", "/api/auth/")
AUTH_EXEMPT_PATHS = {"/", "/index.html", "/styles.css", "/app.js", "/api/health"}

# 앱 실행 시 브라우저에서 열 공개 URL
# 환경변수 PUBLIC_URL로 오버라이드 가능
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://localhost:8420")

# SSL 인증서 경로 (mkcert 생성 파일)
SSL_CERT = os.environ.get("SSL_CERT", str(CONTROLLER_DIR / "certs" / "localhost+1.pem"))
SSL_KEY = os.environ.get("SSL_KEY", str(CONTROLLER_DIR / "certs" / "localhost+1-key.pem"))
