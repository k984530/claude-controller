"""
Controller Service — Job 관리 및 서비스 제어 함수
"""

import json
import os
import time

from config import LOGS_DIR, FIFO_PATH
from utils import parse_meta_file
from error_classify import classify_error
from job_deps import check_dependencies, create_pending_job

# 재수출: handler_jobs.py가 self._jobs_mod()를 통해 접근 (핫 리로드 지원)
from job_deps import dispatch_pending_jobs  # noqa: F401
from service_ctl import start_controller_service, stop_controller_service, cleanup_old_jobs  # noqa: F401


def get_all_jobs(cwd_filter=None):
    """logs/ 디렉토리의 모든 .meta 파일을 파싱하여 작업 목록을 반환한다.

    Args:
        cwd_filter: 지정하면 해당 경로(또는 하위)에서 실행된 작업만 반환한다.
    """
    jobs = []
    if not LOGS_DIR.exists():
        return jobs

    # cwd_filter 정규화
    if cwd_filter:
        cwd_filter = os.path.normpath(os.path.expanduser(cwd_filter))

    meta_files = sorted(LOGS_DIR.glob("job_*.meta"),
                        key=lambda f: int(f.stem.split("_")[1]),
                        reverse=True)
    for mf in meta_files:
        meta = parse_meta_file(mf)
        if not meta:
            continue

        # cwd 필터 적용
        if cwd_filter:
            job_cwd = meta.get("CWD", "")
            if job_cwd:
                job_cwd_norm = os.path.normpath(job_cwd)
                if not (job_cwd_norm == cwd_filter or job_cwd_norm.startswith(cwd_filter + os.sep)):
                    continue
            else:
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

        # 의존성 정보 추출
        deps_str = meta.get("DEPENDS_ON", "")
        depends_on = [d.strip() for d in deps_str.split(",") if d.strip()] if deps_str else None

        job_entry = {
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
            "depends_on":  depends_on,
        }
        if meta.get("STATUS") == "failed" and result_text:
            job_entry["user_error"] = classify_error(result_text)
        jobs.append(job_entry)
    return jobs


def get_stats(from_ts=None, to_ts=None):
    """기간 내 작업 통계를 집계하여 반환한다.

    Args:
        from_ts: 시작 시각 (Unix timestamp). None이면 제한 없음.
        to_ts:   종료 시각 (Unix timestamp). None이면 현재 시각.
    """
    if to_ts is None:
        to_ts = time.time()

    total = 0
    running = 0
    done = 0
    failed = 0
    total_cost = 0.0
    total_duration = 0.0
    cost_count = 0
    duration_count = 0
    by_cwd = {}

    if not LOGS_DIR.exists():
        return _build_stats_response(
            total, running, done, failed,
            total_cost, cost_count, total_duration, duration_count, by_cwd,
            from_ts, to_ts,
        )

    for mf in LOGS_DIR.glob("job_*.meta"):
        meta = parse_meta_file(mf)
        if not meta:
            continue

        # 기간 필터: CREATED_AT 파싱
        created_at = meta.get("CREATED_AT", "")
        if created_at:
            try:
                ts = float(created_at) if created_at.replace(".", "").isdigit() else time.mktime(time.strptime(created_at, "%Y-%m-%d %H:%M:%S"))
            except (ValueError, OverflowError):
                ts = 0
        else:
            # CREATED_AT이 없으면 파일 mtime 사용
            try:
                ts = mf.stat().st_mtime
            except OSError:
                ts = 0

        if from_ts and ts < from_ts:
            continue
        if ts > to_ts:
            continue

        total += 1
        status = meta.get("STATUS", "unknown")

        # 실행 중이지만 프로세스가 죽은 경우 보정
        if status == "running" and meta.get("PID"):
            try:
                os.kill(int(meta["PID"]), 0)
            except (ProcessLookupError, ValueError, OSError):
                status = "done"

        if status == "running":
            running += 1
        elif status == "done":
            done += 1
        elif status == "failed":
            failed += 1

        # cwd별 카운트
        cwd = meta.get("CWD", "") or "unknown"
        if cwd not in by_cwd:
            by_cwd[cwd] = {"total": 0, "done": 0, "failed": 0}
        by_cwd[cwd]["total"] += 1
        if status == "done":
            by_cwd[cwd]["done"] += 1
        elif status == "failed":
            by_cwd[cwd]["failed"] += 1

        # 완료/실패 작업에서 비용·소요시간 추출
        if status in ("done", "failed"):
            job_id_str = meta.get("JOB_ID", "")
            out_file = LOGS_DIR / f"job_{job_id_str}.out"
            cost, dur = _extract_cost_duration(out_file)
            if cost is not None:
                total_cost += cost
                cost_count += 1
            if dur is not None:
                total_duration += dur
                duration_count += 1

    return _build_stats_response(
        total, running, done, failed,
        total_cost, cost_count, total_duration, duration_count, by_cwd,
        from_ts, to_ts,
    )


def _extract_cost_duration(out_file):
    """out 파일에서 cost_usd와 duration_ms를 추출한다."""
    if not out_file.exists():
        return None, None
    cost = None
    dur = None
    try:
        with open(out_file, "r") as f:
            for line in f:
                if '"type":"result"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "result":
                        cost = obj.get("total_cost_usd")
                        dur = obj.get("duration_ms")
                except json.JSONDecodeError:
                    continue
        # fallback: 전체 파일이 단일 JSON인 경우
        if cost is None:
            try:
                data = json.loads(out_file.read_text())
                cost = data.get("total_cost_usd")
                dur = data.get("duration_ms")
            except (json.JSONDecodeError, OSError):
                pass
    except OSError:
        pass
    return cost, dur


def _build_stats_response(total, running, done, failed,
                          total_cost, cost_count, total_duration, duration_count,
                          by_cwd, from_ts, to_ts):
    completed = done + failed
    success_rate = round(done / completed, 4) if completed > 0 else None
    avg_duration_ms = round(total_duration / duration_count, 1) if duration_count > 0 else None

    return {
        "period": {
            "from": from_ts,
            "to": to_ts,
        },
        "jobs": {
            "total": total,
            "running": running,
            "done": done,
            "failed": failed,
        },
        "success_rate": success_rate,
        "cost": {
            "total_usd": round(total_cost, 4) if cost_count > 0 else None,
            "jobs_with_cost": cost_count,
        },
        "duration": {
            "avg_ms": avg_duration_ms,
            "jobs_with_duration": duration_count,
        },
        "by_cwd": by_cwd,
    }


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
            resp = {
                "status":      meta.get("STATUS", "unknown"),
                "result":      result_data.get("result"),
                "cost_usd":    result_data.get("total_cost_usd"),
                "duration_ms": result_data.get("duration_ms"),
                "session_id":  result_data.get("session_id"),
                "is_error":    result_data.get("is_error", False),
            }
            if resp["is_error"] or meta.get("STATUS") == "failed":
                resp["user_error"] = classify_error(result_data.get("result", ""))
            return resp, None

        try:
            data = json.loads(content)
            resp = {
                "status":      meta.get("STATUS", "unknown"),
                "result":      data.get("result"),
                "cost_usd":    data.get("total_cost_usd"),
                "duration_ms": data.get("duration_ms"),
                "session_id":  data.get("session_id"),
                "is_error":    data.get("is_error", False),
            }
            if resp["is_error"] or meta.get("STATUS") == "failed":
                resp["user_error"] = classify_error(data.get("result", ""))
            return resp, None
        except json.JSONDecodeError:
            pass

        return {"status": meta.get("STATUS", "unknown"), "result": content[:2000]}, None
    except OSError as e:
        return None, f"결과 파싱 실패: {e}"


def send_to_fifo(prompt, cwd=None, job_id=None, images=None, session=None, reuse_worktree=None, depends_on=None):
    """FIFO 파이프에 JSON 메시지를 전송한다.

    Args:
        depends_on: 선행 작업 job_id 목록. 지정하면 모든 선행 작업이 완료될 때까지
                    pending 상태로 대기하다가 자동 디스패치된다.
    """
    if not job_id:
        job_id = f"{int(time.time())}-web-{os.getpid()}-{id(prompt) % 10000}"

    # 의존성이 있는 경우 → 선행 작업 완료 여부 확인
    if depends_on:
        deps = [str(d).strip() for d in depends_on if str(d).strip()]
        if deps:
            unmet = check_dependencies(deps)
            if unmet:
                return create_pending_job(prompt, cwd, job_id, images, session, deps)

    if not FIFO_PATH.exists():
        return None, "FIFO 파이프가 존재하지 않습니다. 서비스가 실행 중인지 확인하세요."

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


