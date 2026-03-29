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


# 경로 설정 — web/ 기준
_WEB_DIR = Path(__file__).resolve().parent
_CONTROLLER_DIR = _WEB_DIR.parent
_DATA_DIR = _CONTROLLER_DIR / "data"
_SETTINGS_FILE = _DATA_DIR / "settings.json"
_LOGS_DIR = _CONTROLLER_DIR / "logs"
_WEBHOOK_SENT_DIR = _DATA_DIR / "webhook_sent"


def _load_settings():
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _build_payload(job_id, status):
    """작업의 메타 + 결과를 읽어서 웹훅 페이로드를 생성한다."""
    meta_file = _LOGS_DIR / f"job_{job_id}.meta"
    out_file = _LOGS_DIR / f"job_{job_id}.out"

    meta = {}
    if meta_file.exists():
        try:
            for line in meta_file.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    meta[k.strip()] = v.strip().strip("'\"")
        except OSError:
            pass

    # 결과 추출
    result_text = None
    cost_usd = None
    duration_ms = None
    session_id = None
    is_error = False

    if out_file.exists():
        try:
            for line in out_file.read_text().splitlines():
                if '"type":"result"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "result":
                        result_text = obj.get("result")
                        cost_usd = obj.get("total_cost_usd")
                        duration_ms = obj.get("duration_ms")
                        session_id = obj.get("session_id")
                        is_error = obj.get("is_error", False)
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    return {
        "event": f"job.{status}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job": {
            "job_id": job_id,
            "status": status,
            "prompt": meta.get("PROMPT", ""),
            "cwd": meta.get("CWD") or None,
            "created_at": meta.get("CREATED_AT", ""),
            "session_id": session_id or meta.get("SESSION_ID") or None,
            "result": result_text,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "is_error": is_error,
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


# ════════════════════════════════════════════════
#  DAG 디스패치 — 작업 완료 시 후속 pending 작업 자동 실행
# ════════════════════════════════════════════════

def _dispatch_pending_after_completion():
    """작업 완료 후 의존성이 충족된 pending 작업을 디스패치한다."""
    try:
        sys.path.insert(0, str(_WEB_DIR))
        from jobs import dispatch_pending_jobs
        dispatched = dispatch_pending_jobs()
        if dispatched:
            print(f"DAG dispatch: {dispatched}", file=sys.stderr)
    except Exception as e:
        print(f"DAG dispatch error: {e}", file=sys.stderr)


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
    _dispatch_pending_after_completion()
