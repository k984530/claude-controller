"""
Controller Service — Job 관리 및 서비스 제어 함수
"""

import json
import os
import signal
import subprocess
import time

from config import LOGS_DIR, FIFO_PATH, SERVICE_SCRIPT, CONTROLLER_DIR
from utils import parse_meta_file, is_service_running


def get_all_jobs():
    """logs/ 디렉토리의 모든 .meta 파일을 파싱하여 작업 목록을 반환한다."""
    jobs = []
    if not LOGS_DIR.exists():
        return jobs

    meta_files = sorted(LOGS_DIR.glob("job_*.meta"),
                        key=lambda f: int(f.stem.split("_")[1]),
                        reverse=True)
    for mf in meta_files:
        meta = parse_meta_file(mf)
        if not meta:
            continue

        if meta.get("STATUS") == "running" and meta.get("PID"):
            try:
                os.kill(int(meta["PID"]), 0)
            except (ProcessLookupError, ValueError, OSError):
                meta["STATUS"] = "done"

        # 실행 중인 작업의 session_id 조기 추출 시도
        if not meta.get("SESSION_ID") and meta.get("STATUS") == "running":
            out_file_early = LOGS_DIR / f"job_{meta.get('JOB_ID', '')}.out"
            if out_file_early.exists():
                try:
                    with open(out_file_early, "r") as ef:
                        for eline in ef:
                            try:
                                eobj = json.loads(eline.strip())
                                sid_early = eobj.get("session_id")
                                if sid_early:
                                    meta["SESSION_ID"] = sid_early
                                    break
                            except json.JSONDecodeError:
                                continue
                except OSError:
                    pass

        result_text = None
        cost_usd = None
        duration_ms = None
        job_id_str = meta.get("JOB_ID", "")
        if meta.get("STATUS") in ("done", "failed"):
            out_file = LOGS_DIR / f"job_{job_id_str}.out"
            if out_file.exists():
                try:
                    with open(out_file, "r") as f:
                        for line in f:
                            try:
                                obj = json.loads(line.strip())
                                if obj.get("type") == "result":
                                    result_text = obj.get("result", "")
                                    cost_usd = obj.get("total_cost_usd")
                                    duration_ms = obj.get("duration_ms")
                                if not meta.get("SESSION_ID") and obj.get("session_id"):
                                    meta["SESSION_ID"] = obj["session_id"]
                            except json.JSONDecodeError:
                                continue
                    if result_text is None:
                        try:
                            data = json.loads(out_file.read_text())
                            result_text = data.get("result", "")
                            cost_usd = data.get("total_cost_usd")
                            duration_ms = data.get("duration_ms")
                            if not meta.get("SESSION_ID") and data.get("session_id"):
                                meta["SESSION_ID"] = data["session_id"]
                        except (json.JSONDecodeError, OSError):
                            pass
                except OSError:
                    pass

        jobs.append({
            "job_id":      job_id_str,
            "status":      meta.get("STATUS", "unknown"),
            "session_id":  meta.get("SESSION_ID", "") or None,
            "prompt":      meta.get("PROMPT", ""),
            "created_at":  meta.get("CREATED_AT", ""),
            "uuid":        meta.get("UUID", "") or None,
            "cwd":         meta.get("CWD", "") or None,
            "result":      result_text,
            "cost_usd":    cost_usd,
            "duration_ms": duration_ms,
        })
    return jobs


def get_job_result(job_id):
    """작업 결과(.out 파일)에서 result 필드를 추출한다."""
    out_file = LOGS_DIR / f"job_{job_id}.out"
    meta_file = LOGS_DIR / f"job_{job_id}.meta"

    if not meta_file.exists():
        return None, "작업을 찾을 수 없습니다"

    meta = parse_meta_file(meta_file)
    if meta.get("STATUS") == "running":
        # 프로세스가 실제로 살아있는지 확인 — meta가 running이지만 PID가 죽었으면 done 처리
        pid = meta.get("PID")
        if pid:
            try:
                os.kill(int(pid), 0)
            except (ProcessLookupError, ValueError, OSError):
                meta["STATUS"] = "done"
        if meta.get("STATUS") == "running":
            return {"status": "running", "result": None}, None

    if not out_file.exists():
        return None, "출력 파일이 없습니다"

    try:
        with open(out_file, "r") as f:
            content = f.read()

        result_data = None
        for line in content.strip().split("\n"):
            try:
                obj = json.loads(line)
                if obj.get("type") == "result":
                    result_data = obj
            except json.JSONDecodeError:
                continue

        if result_data:
            return {
                "status":      meta.get("STATUS", "unknown"),
                "result":      result_data.get("result"),
                "cost_usd":    result_data.get("total_cost_usd"),
                "duration_ms": result_data.get("duration_ms"),
                "session_id":  result_data.get("session_id"),
                "is_error":    result_data.get("is_error", False),
            }, None

        try:
            data = json.loads(content)
            return {
                "status":      meta.get("STATUS", "unknown"),
                "result":      data.get("result"),
                "cost_usd":    data.get("total_cost_usd"),
                "duration_ms": data.get("duration_ms"),
                "session_id":  data.get("session_id"),
                "is_error":    data.get("is_error", False),
            }, None
        except json.JSONDecodeError:
            pass

        return {"status": meta.get("STATUS", "unknown"), "result": content[:2000]}, None
    except OSError as e:
        return None, f"결과 파싱 실패: {e}"


def send_to_fifo(prompt, cwd=None, job_id=None, images=None, session=None, reuse_worktree=None):
    """FIFO 파이프에 JSON 메시지를 전송한다."""
    if not FIFO_PATH.exists():
        return None, "FIFO 파이프가 존재하지 않습니다. 서비스가 실행 중인지 확인하세요."

    if not job_id:
        job_id = f"{int(time.time())}-web-{os.getpid()}-{id(prompt) % 10000}"

    payload = {"id": job_id, "prompt": prompt}
    if cwd:
        payload["cwd"] = cwd
    if images:
        payload["images"] = images
    if session:
        payload["session"] = session
    if reuse_worktree:
        payload["reuse_worktree"] = reuse_worktree

    try:
        fd = os.open(str(FIFO_PATH), os.O_WRONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return {"job_id": job_id, "prompt": prompt, "cwd": cwd}, None
    except OSError as e:
        return None, f"FIFO 전송 실패: {e}"


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
