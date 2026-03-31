"""
Controller Service — Webhook 전달 모듈

작업 완료/실패 시 등록된 URL로 결과를 POST한다.
bash(lib/jobs.sh)에서 직접 호출 가능:
  python3 /path/to/webhook.py <job_id> <status>
"""

import hashlib
import hmac
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


# ── 경로 설정 ────────────────────────────────
# CLI 단독 실행(if __name__)과 모듈 임포트 양쪽을 지원한다.
# 모듈 임포트 시에는 config.py의 상수를 사용하고,
# CLI 단독 실행 시에는 __file__ 기준으로 경로를 계산한다.

_WEB_DIR = Path(__file__).resolve().parent

try:
    from config import DATA_DIR, LOGS_DIR, SETTINGS_FILE
    from utils import parse_meta_file, parse_job_output
except ImportError:
    # CLI 단독 실행 시 fallback
    sys.path.insert(0, str(_WEB_DIR))
    _CONTROLLER_DIR = _WEB_DIR.parent
    DATA_DIR = _CONTROLLER_DIR / "data"
    LOGS_DIR = _CONTROLLER_DIR / "logs"
    SETTINGS_FILE = DATA_DIR / "settings.json"
    from utils import parse_meta_file, parse_job_output

_WEBHOOK_SENT_DIR = DATA_DIR / "webhook_sent"


def _load_settings():
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _build_payload(job_id, status):
    """작업의 메타 + 결과를 읽어서 웹훅 페이로드를 생성한다."""
    meta_file = LOGS_DIR / f"job_{job_id}.meta"
    out_file = LOGS_DIR / f"job_{job_id}.out"

    meta = parse_meta_file(meta_file) if meta_file.exists() else {}
    parsed = parse_job_output(out_file)

    return {
        "event": f"job.{status}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job": {
            "job_id": job_id,
            "status": status,
            "prompt": meta.get("PROMPT", ""),
            "cwd": meta.get("CWD") or None,
            "created_at": meta.get("CREATED_AT", ""),
            "session_id": parsed["session_id"] or meta.get("SESSION_ID") or None,
            "result": parsed["result"],
            "cost_usd": parsed["cost_usd"],
            "duration_ms": parsed["duration_ms"],
            "is_error": parsed["is_error"],
        },
    }


def _sign_payload(payload_bytes, secret):
    """HMAC-SHA256 서명을 생성한다."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def deliver_webhook(job_id, status):
    """설정에 webhook_url이 있으면 결과를 POST한다.

    Returns:
        dict | None: 전송 결과 또는 None (미설정/중복)
    """
    settings = _load_settings()
    webhook_url = (settings.get("webhook_url") or "").strip()
    if not webhook_url:
        return None

    # 이벤트 필터: webhook_events가 설정되어 있으면 해당 이벤트만 전송
    webhook_events = settings.get("webhook_events", "done,failed")
    allowed_events = {e.strip() for e in webhook_events.split(",")}
    if status not in allowed_events:
        return None

    # 중복 전송 방지
    _WEBHOOK_SENT_DIR.mkdir(parents=True, exist_ok=True)
    sent_marker = _WEBHOOK_SENT_DIR / f"{job_id}_{status}"
    if sent_marker.exists():
        return None

    payload = _build_payload(job_id, status)
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Controller-Webhook/1.0",
    }

    # HMAC 서명
    webhook_secret = (settings.get("webhook_secret") or "").strip()
    if webhook_secret:
        sig = _sign_payload(payload_bytes, webhook_secret)
        headers["X-Webhook-Signature"] = f"sha256={sig}"

    try:
        req = urllib.request.Request(
            webhook_url, data=payload_bytes, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_status = resp.status

        # 성공 마커 기록
        sent_marker.write_text(str(int(time.time())))

        return {
            "delivered": True,
            "url": webhook_url,
            "status_code": resp_status,
            "event": payload["event"],
        }
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {
            "delivered": False,
            "url": webhook_url,
            "error": str(e),
            "event": payload["event"],
        }


def cleanup_test_marker():
    """테스트 웹훅 전송 마커를 삭제한다. deliver_webhook 테스트 후 호출."""
    marker = _WEBHOOK_SENT_DIR / "test-0000_done"
    if marker.exists():
        try:
            marker.unlink()
        except OSError:
            pass


def cleanup_sent_markers(max_age_seconds=86400):
    """오래된 전송 마커를 정리한다 (기본 24시간)."""
    if not _WEBHOOK_SENT_DIR.exists():
        return
    now = time.time()
    for f in _WEBHOOK_SENT_DIR.iterdir():
        try:
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink()
        except OSError:
            pass


# CLI 진입점: python3 webhook.py <job_id> <status>
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <job_id> <done|failed>", file=sys.stderr)
        sys.exit(1)

    _job_id = sys.argv[1]
    _status = sys.argv[2]

    if _status not in ("done", "failed"):
        print(f"Invalid status: {_status}", file=sys.stderr)
        sys.exit(1)

    result = deliver_webhook(_job_id, _status)
    if result:
        print(json.dumps(result, ensure_ascii=False))

    # 작업 완료 후 DAG 의존성 체인 처리
    try:
        from job_deps import dispatch_pending_jobs
        dispatched = dispatch_pending_jobs()
        if dispatched:
            print(f"DAG dispatch: {dispatched}", file=sys.stderr)
    except Exception as e:
        print(f"DAG dispatch error: {e}", file=sys.stderr)
