"""
작업 의존성 DAG — pending 작업 관리

jobs.py에서 분리됨.
선행 작업이 완료될 때까지 대기하는 pending 작업을 등록하고,
의존성이 충족되면 FIFO로 디스패치한다.
"""

import json
import os
import re
import time

from config import LOGS_DIR, FIFO_PATH
from utils import parse_meta_file


def check_dependencies(depends_on):
    """의존성 목록에서 아직 완료되지 않은 작업 ID를 반환한다."""
    unmet = []
    for dep_id in depends_on:
        meta_file = LOGS_DIR / f"job_{dep_id}.meta"
        if not meta_file.exists():
            unmet.append(dep_id)
            continue
        meta = parse_meta_file(meta_file)
        if meta.get("STATUS") != "done":
            unmet.append(dep_id)
    return unmet


def _next_job_id():
    """Python에서 job counter를 원자적으로 증가시킨다 (쉘 호환 mkdir 스핀락)."""
    counter_file = LOGS_DIR / ".job_counter"
    lock_dir = LOGS_DIR / ".job_counter.lock"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    waited = 0
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            time.sleep(0.01)
            waited += 1
            if waited > 500:
                try:
                    lock_dir.rmdir()
                except OSError:
                    pass
                waited = 0

    try:
        current = 0
        if counter_file.exists():
            try:
                current = int(counter_file.read_text().strip())
            except (ValueError, OSError):
                pass
        next_id = current + 1
        counter_file.write_text(str(next_id))
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass

    return next_id


def _sanitize_meta_value(value: str) -> str:
    """meta 파일에 기록할 값에서 개행·제어문자를 제거하여 필드 인젝션을 방지한다."""
    return re.sub(r'[\x00-\x1f\x7f]', '', value)


def create_pending_job(prompt, cwd, uuid, images, session, depends_on):
    """의존성이 충족되지 않은 작업을 pending 상태로 등록한다."""
    new_id = _next_job_id()
    meta_file = LOGS_DIR / f"job_{new_id}.meta"
    pending_file = LOGS_DIR / f"job_{new_id}.pending"

    safe_prompt = _sanitize_meta_value(prompt[:500].replace("'", "\\'"))
    safe_uuid = _sanitize_meta_value(str(uuid or ''))
    safe_cwd = _sanitize_meta_value(str(cwd or ''))
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    deps_str = _sanitize_meta_value(",".join(depends_on))

    content = (
        f"JOB_ID={new_id}\n"
        f"STATUS=pending\n"
        f"PID=\n"
        f"PROMPT='{safe_prompt}'\n"
        f"CREATED_AT='{ts}'\n"
        f"SESSION_ID=\n"
        f"UUID={safe_uuid}\n"
        f"CWD='{safe_cwd}'\n"
        f"DEPENDS_ON={deps_str}\n"
    )

    # FIFO에 보낼 페이로드를 .pending 파일에 저장
    payload = {"id": uuid, "prompt": prompt, "pending_job_id": str(new_id)}
    if cwd:
        payload["cwd"] = cwd
    if images:
        payload["images"] = images
    if session:
        payload["session"] = session

    # 원자적 쓰기
    tmp = meta_file.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(content)
    os.rename(str(tmp), str(meta_file))
    pending_file.write_text(json.dumps(payload, ensure_ascii=False))

    return {
        "job_id": str(new_id),
        "prompt": prompt,
        "cwd": cwd,
        "status": "pending",
        "depends_on": depends_on,
    }, None


def dispatch_pending_jobs():
    """pending 상태의 작업 중 의존성이 충족된 것을 FIFO로 디스패치한다.

    Returns:
        list[str]: 디스패치된 job_id 목록
    """
    if not LOGS_DIR.exists() or not FIFO_PATH.exists():
        return []

    dispatched = []
    for mf in sorted(LOGS_DIR.glob("job_*.meta")):
        meta = parse_meta_file(mf)
        if not meta or meta.get("STATUS") != "pending":
            continue

        deps_str = meta.get("DEPENDS_ON", "")
        if not deps_str:
            continue

        depends_on = [d.strip() for d in deps_str.split(",") if d.strip()]

        # 선행 작업 중 실패한 것이 있으면 이 작업도 실패 처리
        any_failed = False
        for dep_id in depends_on:
            dep_meta_file = LOGS_DIR / f"job_{dep_id}.meta"
            if dep_meta_file.exists():
                dep_meta = parse_meta_file(dep_meta_file)
                if dep_meta.get("STATUS") == "failed":
                    any_failed = True
                    break

        job_id = meta.get("JOB_ID", "")
        if any_failed:
            _mark_pending_failed(job_id)
            dispatched.append(job_id)
            continue

        unmet = check_dependencies(depends_on)
        if unmet:
            continue

        # 모든 의존성 충족 → FIFO로 전송
        pending_file = LOGS_DIR / f"job_{job_id}.pending"
        if not pending_file.exists():
            continue

        try:
            payload = json.loads(pending_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        try:
            fd = os.open(str(FIFO_PATH), os.O_WRONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            pending_file.unlink(missing_ok=True)
            dispatched.append(job_id)
        except OSError:
            continue

    return dispatched


def _mark_pending_failed(job_id):
    """선행 작업 실패로 인해 pending 작업을 failed로 전환한다."""
    meta_file = LOGS_DIR / f"job_{job_id}.meta"
    pending_file = LOGS_DIR / f"job_{job_id}.pending"
    if meta_file.exists():
        content = meta_file.read_text()
        content = content.replace("STATUS=pending", "STATUS=failed")
        tmp = meta_file.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(content)
        os.rename(str(tmp), str(meta_file))
    pending_file.unlink(missing_ok=True)
