"""
Health Check — 서비스 상태 점검

handler.py의 _handle_health에서 분리.
서비스, FIFO, 작업, 디스크, 워치독 상태를 수집하여 반환한다.
"""

import json
import os
import shutil
import time
from datetime import datetime, timezone


def collect_health(config) -> tuple[dict, int]:
    """전체 헬스체크 정보를 수집한다.

    Args:
        config: config 모듈 (FIFO_PATH, LOGS_DIR, PID_FILE, CONTROLLER_DIR 필요)

    Returns:
        (payload dict, http_status_code)
    """
    from utils import is_service_running, parse_meta_file, correct_running_status

    # ── 서비스 상태 ──
    running, pid = is_service_running()
    uptime_seconds = None
    if running and config.PID_FILE.exists():
        try:
            uptime_seconds = int(time.time() - config.PID_FILE.stat().st_mtime)
        except OSError:
            pass

    # ── FIFO 상태 ──
    fifo_exists = config.FIFO_PATH.exists()
    fifo_writable = os.access(str(config.FIFO_PATH), os.W_OK) if fifo_exists else False

    # ── 작업 통계 (parse_meta_file + correct_running_status 사용) ──
    active, succeeded, failed, total = 0, 0, 0, 0
    if config.LOGS_DIR.exists():
        for mf in config.LOGS_DIR.glob("job_*.meta"):
            meta = parse_meta_file(mf)
            if not meta:
                continue
            total += 1
            status = correct_running_status(meta)
            if status == "running":
                active += 1
            elif status == "done":
                succeeded += 1
            elif status == "failed":
                failed += 1

    # ── 디스크 사용량 ──
    logs_size_bytes = 0
    if config.LOGS_DIR.exists():
        for f in config.LOGS_DIR.iterdir():
            try:
                logs_size_bytes += f.stat().st_size
            except OSError:
                pass

    disk_total, disk_used, disk_free = shutil.disk_usage("/")

    # ── 워치독 상태 ──
    wd_pid_file = config.CONTROLLER_DIR / "service" / "watchdog.pid"
    wd_state_file = config.CONTROLLER_DIR / "data" / "watchdog_state.json"
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

    payload = {
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
    }

    return payload, http_status
