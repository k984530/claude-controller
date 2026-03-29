"""
감사 로그 — 모든 API 호출을 타임스탬프·IP와 함께 기록하고 조회 API를 제공한다.

저장 형식: JSONL (한 줄에 하나의 JSON 객체)
저장 위치: data/audit.log
필드: ts, time, method, path, ip, status, duration_ms
"""

import json
import time
from config import DATA_DIR

AUDIT_LOG_FILE = DATA_DIR / "audit.log"
_ROTATED_FILE = DATA_DIR / "audit.log.1"

# 최대 로그 파일 크기 (10 MB) — 초과 시 .1로 로테이션
MAX_AUDIT_SIZE = 10 * 1024 * 1024

# 기록 제외 경로 (정적 파일, 페이지 요청)
_EXCLUDE_PREFIXES = ("/static/", "/uploads/")
_EXCLUDE_PATHS = {"/", "/index.html", "/favicon.ico"}


def log_api_call(method, path, client_ip, status, duration_ms):
    """API 호출 한 건을 감사 로그에 기록한다.

    정적 파일 요청과 페이지 로드는 제외되며, /api/ 경로만 기록된다.
    POSIX O_APPEND 모드의 원자적 쓰기를 활용하여 ThreadingHTTPServer에서 안전하다.
    """
    if path in _EXCLUDE_PATHS:
        return
    for prefix in _EXCLUDE_PREFIXES:
        if path.startswith(prefix):
            return

    entry = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "method": method,
        "path": path,
        "ip": client_ip,
        "status": status,
        "duration_ms": round(duration_ms, 1),
    }

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # 크기 기반 로테이션: 최대 1세대만 유지
        if AUDIT_LOG_FILE.exists():
            try:
                if AUDIT_LOG_FILE.stat().st_size > MAX_AUDIT_SIZE:
                    AUDIT_LOG_FILE.rename(_ROTATED_FILE)
            except OSError:
                pass
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def search_audit(from_ts=None, to_ts=None, method=None, path_contains=None,
                 ip=None, status=None, limit=100, offset=0):
    """감사 로그를 조건에 맞게 검색한다.

    Args:
        from_ts: 시작 시간 (Unix timestamp)
        to_ts: 끝 시간 (Unix timestamp)
        method: HTTP 메서드 필터 (GET, POST, DELETE)
        path_contains: 경로 부분 문자열 필터
        ip: IP 주소 필터
        status: HTTP 상태 코드 필터
        limit: 반환 최대 건수 (기본 100)
        offset: 건너뛸 건수

    Returns:
        dict: {"entries": [...], "total": int, "limit": int, "offset": int}
    """
    if not AUDIT_LOG_FILE.exists():
        return {"entries": [], "total": 0, "limit": limit, "offset": offset}

    results = []
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("ts", 0)
            if from_ts is not None and ts < from_ts:
                continue
            if to_ts is not None and ts > to_ts:
                continue
            if method and entry.get("method") != method.upper():
                continue
            if path_contains and path_contains not in entry.get("path", ""):
                continue
            if ip and entry.get("ip") != ip:
                continue
            if status is not None:
                try:
                    if entry.get("status") != int(status):
                        continue
                except (ValueError, TypeError):
                    continue

            results.append(entry)

    # 최신 순으로 정렬
    results.sort(key=lambda e: e.get("ts", 0), reverse=True)
    total = len(results)
    entries = results[offset:offset + limit]

    return {
        "entries": entries,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
