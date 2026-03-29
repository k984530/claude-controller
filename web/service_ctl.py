"""
Controller 서비스 시작/종료 및 정리

jobs.py에서 분리됨.
"""

import os
import signal
import subprocess
import time

from config import LOGS_DIR, SERVICE_SCRIPT, CONTROLLER_DIR
from utils import parse_meta_file, is_service_running


def start_controller_service():
    """컨트롤러 서비스를 백그라운드로 시작한다."""
    running, pid = is_service_running()
    if running:
        return True, pid

    if not SERVICE_SCRIPT.exists():
        return False, None

    log_file = LOGS_DIR / "service.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_fh = open(log_file, "a")
    try:
        subprocess.Popen(
            ["bash", str(SERVICE_SCRIPT), "start"],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(CONTROLLER_DIR),
        )
    finally:
        log_fh.close()

    for _ in range(30):
        time.sleep(0.1)
        running, pid = is_service_running()
        if running:
            return True, pid

    return False, None


def stop_controller_service():
    """컨트롤러 서비스를 종료한다."""
    running, pid = is_service_running()
    if not running:
        return False, "서비스가 실행 중이 아닙니다"

    try:
        os.kill(pid, signal.SIGTERM)
        return True, None
    except OSError as e:
        return False, f"종료 실패: {e}"


def cleanup_old_jobs(retention_days=30):
    """보존 기간이 지난 완료/실패 작업 파일을 삭제한다.

    Args:
        retention_days: 보존 기간 (일). 이 기간보다 오래된 done/failed 작업을 삭제.

    Returns:
        dict: 삭제 결과 (cleaned 수, skipped_running 수, freed_bytes 등)
    """
    if not LOGS_DIR.exists():
        return {"cleaned": 0, "skipped_running": 0, "freed_bytes": 0}

    cutoff_ts = time.time() - retention_days * 86400
    cleaned = 0
    skipped_running = 0
    freed_bytes = 0

    for mf in list(LOGS_DIR.glob("job_*.meta")):
        meta = parse_meta_file(mf)
        if not meta:
            continue

        status = meta.get("STATUS", "unknown")

        # running 상태는 건드리지 않음
        if status == "running":
            pid = meta.get("PID")
            if pid:
                try:
                    os.kill(int(pid), 0)
                    skipped_running += 1
                    continue
                except (ProcessLookupError, ValueError, OSError):
                    pass  # 프로세스 죽음 → 정리 대상
            else:
                skipped_running += 1
                continue

        # 파일 수정 시각 기준으로 보존 기간 확인
        try:
            mtime = mf.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff_ts:
            continue

        # job ID 추출 → 관련 파일 일괄 삭제
        job_id_str = mf.stem.replace("job_", "")  # job_123.meta → 123
        for suffix in (".meta", ".out", ".ext_id"):
            target = LOGS_DIR / f"job_{job_id_str}{suffix}"
            if target.exists():
                try:
                    freed_bytes += target.stat().st_size
                    target.unlink()
                except OSError:
                    pass
        cleaned += 1

    return {
        "cleaned": cleaned,
        "skipped_running": skipped_running,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1048576, 2),
        "retention_days": retention_days,
    }
