"""
Controller Service — 토큰 기반 인증 모듈

서버 시작 시 랜덤 토큰을 생성하여 파일에 저장하고 터미널에 출력한다.
모든 API 요청은 이 토큰을 Authorization 헤더로 포함해야 한다.
로컬 머신의 터미널을 볼 수 있는 사람만 토큰을 획득할 수 있으므로
CSRF, DNS Rebinding 등 원격 공격을 차단한다.
"""

import secrets
from pathlib import Path

from config import DATA_DIR

TOKEN_FILE = DATA_DIR / "auth_token"
_cached_token: str | None = None


def generate_token() -> str:
    """새 토큰을 생성하고 파일에 저장한다."""
    global _cached_token
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, "utf-8")
    # 토큰 파일 권한을 소유자만 읽기/쓰기로 제한
    TOKEN_FILE.chmod(0o600)
    _cached_token = token
    return token


def get_token() -> str:
    """현재 토큰을 반환한다. 없으면 생성한다."""
    global _cached_token
    if _cached_token:
        return _cached_token
    if TOKEN_FILE.exists():
        _cached_token = TOKEN_FILE.read_text("utf-8").strip()
        if _cached_token:
            return _cached_token
    return generate_token()


def verify_token(provided: str) -> bool:
    """제공된 토큰이 유효한지 검증한다. (타이밍 공격 방지를 위해 secrets.compare_digest 사용)"""
    expected = get_token()
    return secrets.compare_digest(provided, expected)
