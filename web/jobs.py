"""
Controller Service — Job 관리 및 서비스 제어 함수
"""

import json
import os
import time

from config import LOGS_DIR, FIFO_PATH
from utils import parse_meta_file, is_pid_alive, correct_running_status, parse_job_output
from error_classify import classify_error
from job_deps import check_dependencies, create_pending_job

# 재수출: handler_jobs.py가 self._jobs_mod()를 통해 접근 (핫 리로드 지원)
from job_deps import dispatch_pending_jobs  # noqa: F401
from service_ctl import start_controller_service, stop_controller_service, cleanup_old_jobs  # noqa: F401


def iter_job_metas(cwd_filter=None):
    """logs/ 디렉토리의 .meta 파일을 순회하며 (meta_dict, meta_file) 쌍을 yield한다.

    상태 보정(correct_running_status)이 적용된 meta를 반환한다.
    cwd_filter가 지정되면 해당 경로(또는 하위)에서 실행된 작업만 반환한다.
    """
    if not LOGS_DIR.exists():
        return

    norm_filter = os.path.normpath(os.path.expanduser(cwd_filter)) if cwd_filter else None

    meta_files = sorted(LOGS_DIR.glob("job_*.meta"),
                        key=lambda f: int(f.stem.split("_")[1]),
                        reverse=True)
    for mf in meta_files:
        meta = parse_meta_file(mf)
        if not meta:
            continue

        if norm_filter:
            job_cwd = meta.get("CWD", "")
            if not job_cwd:
                continue
            job_cwd_norm = os.path.normpath(job_cwd)
            if not (job_cwd_norm == norm_filter or job_cwd_norm.startswith(norm_filter + os.sep)):
                continue

        meta["STATUS"] = correct_running_status(meta)
        yield meta, mf


def _build_job_entry(meta: dict) -> dict:
    """보정된 meta dict로부터 API 응답용 job entry를 조립한다."""
    job_id_str = meta.get("JOB_ID", "")
    out_file = LOGS_DIR / f"job_{job_id_str}.out"
    parsed_out = parse_job_output(out_file)

    # session_id 보완: meta에 없으면 out 파일에서 추출
    if not meta.get("SESSION_ID") and parsed_out.get("session_id"):
        meta["SESSION_ID"] = parsed_out["session_id"]

    is_terminal = meta.get("STATUS") in ("done", "failed")
    result_text = parsed_out["result"] if is_terminal else None
    cost_usd = parsed_out["cost_usd"] if is_terminal else None
    duration_ms = parsed_out["duration_ms"] if is_terminal else None

    # 의존성 정보 추출
    deps_str = meta.get("DEPENDS_ON", "")
    depends_on = [d.strip() for d in deps_str.split(",") if d.strip()] if deps_str else None

    entry = {
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
        "origin_type": meta.get("ORIGIN_TYPE") or None,
        "origin_id":   meta.get("ORIGIN_ID") or None,
        "origin_name": meta.get("ORIGIN_NAME") or None,
    }
    if meta.get("STATUS") == "failed" and result_text:
        entry["user_error"] = classify_error(result_text)
    return entry


def get_all_jobs(cwd_filter=None):
    """logs/ 디렉토리의 모든 .meta 파일을 파싱하여 작업 목록을 반환한다.

    Args:
        cwd_filter: 지정하면 해당 경로(또는 하위)에서 실행된 작업만 반환한다.
    """
    return [_build_job_entry(meta) for meta, _ in iter_job_metas(cwd_filter)]


def _parse_created_ts(meta: dict, meta_file) -> float:
    """meta의 CREATED_AT을 Unix timestamp로 파싱한다. 실패 시 파일 mtime 사용."""
    created_at = meta.get("CREATED_AT", "")
    if created_at:
        try:
            if created_at.replace(".", "").isdigit():
                return float(created_at)
            return time.mktime(time.strptime(created_at, "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            pass
    try:
        return meta_file.stat().st_mtime
    except OSError:
        return 0


def _accumulate_job_stats(meta, status, acc):
    """개별 작업의 통계를 누적기(acc)에 반영한다."""
    acc["total"] += 1
    if status in ("running", "done", "failed"):
        acc[status] += 1

    cwd = meta.get("CWD", "") or "unknown"
    if cwd not in acc["by_cwd"]:
        acc["by_cwd"][cwd] = {"total": 0, "done": 0, "failed": 0}
    acc["by_cwd"][cwd]["total"] += 1
    if status in ("done", "failed"):
        acc["by_cwd"][cwd][status] += 1

    if status in ("done", "failed"):
        job_id_str = meta.get("JOB_ID", "")
        out_file = LOGS_DIR / f"job_{job_id_str}.out"
        parsed_out = parse_job_output(out_file)
        if parsed_out["cost_usd"] is not None:
            acc["total_cost"] += parsed_out["cost_usd"]
            acc["cost_count"] += 1
        if parsed_out["duration_ms"] is not None:
            acc["total_duration"] += parsed_out["duration_ms"]
            acc["duration_count"] += 1


def get_stats(from_ts=None, to_ts=None):
    """기간 내 작업 통계를 집계하여 반환한다.

    Args:
        from_ts: 시작 시각 (Unix timestamp). None이면 제한 없음.
        to_ts:   종료 시각 (Unix timestamp). None이면 현재 시각.
    """
    if to_ts is None:
        to_ts = time.time()

    acc = {
        "total": 0, "running": 0, "done": 0, "failed": 0,
        "total_cost": 0.0, "total_duration": 0.0,
        "cost_count": 0, "duration_count": 0, "by_cwd": {},
    }

    if LOGS_DIR.exists():
        for mf in LOGS_DIR.glob("job_*.meta"):
            meta = parse_meta_file(mf)
            if not meta:
                continue
            ts = _parse_created_ts(meta, mf)
            if from_ts and ts < from_ts:
                continue
            if ts > to_ts:
                continue
            _accumulate_job_stats(meta, correct_running_status(meta), acc)

    return _build_stats_response(
        acc["total"], acc["running"], acc["done"], acc["failed"],
        acc["total_cost"], acc["cost_count"],
        acc["total_duration"], acc["duration_count"],
        acc["by_cwd"], from_ts, to_ts,
    )



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
    status = correct_running_status(meta)
    meta["STATUS"] = status

    if status == "running":
        return {"status": "running", "result": None}, None

    if not out_file.exists():
        return None, "출력 파일이 없습니다"

    parsed = parse_job_output(out_file)
    if parsed["result"] is not None:
        resp = {
            "status":      status,
            "result":      parsed["result"],
            "cost_usd":    parsed["cost_usd"],
            "duration_ms": parsed["duration_ms"],
            "session_id":  parsed["session_id"],
            "is_error":    parsed["is_error"],
        }
        if resp["is_error"] or status == "failed":
            resp["user_error"] = classify_error(parsed["result"] or "")
        return resp, None

    # fallback: 파싱 실패 시 원본 텍스트 일부 반환
    try:
        content = out_file.read_text()[:2000]
        return {"status": status, "result": content}, None
    except OSError as e:
        return None, f"결과 파싱 실패: {e}"


def send_to_fifo(prompt, cwd=None, job_id=None, images=None, session=None, reuse_worktree=None, depends_on=None, system_prompt=None, origin=None):
    """FIFO 파이프에 JSON 메시지를 전송한다.

    Args:
        depends_on: 선행 작업 job_id 목록. 지정하면 모든 선행 작업이 완료될 때까지
                    pending 상태로 대기하다가 자동 디스패치된다.
        system_prompt: 스킬 시스템 프롬프트. --append-system-prompt로 전달된다.
        origin: 작업 출처 정보 dict (type, id, name). 스킬/파이프라인/수동 구분.
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
    if system_prompt:
        payload["system_prompt"] = system_prompt
    if origin and isinstance(origin, dict):
        for k in ("type", "id", "name"):
            if origin.get(k):
                payload[f"origin_{k}"] = str(origin[k])

    try:
        fd = os.open(str(FIFO_PATH), os.O_WRONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return {"job_id": job_id, "prompt": prompt, "cwd": cwd}, None
    except OSError as e:
        return None, f"FIFO 전송 실패: {e}"


def get_results(origin_type=None, origin_id=None, limit=20):
    """완료된 작업을 origin(스킬/파이프라인/수동) 기준으로 그룹화하여 반환한다."""
    all_jobs = get_all_jobs()
    completed = [j for j in all_jobs if j.get("status") in ("done", "failed")]

    if origin_type:
        completed = [j for j in completed if j.get("origin_type") == origin_type]
    if origin_id:
        completed = [j for j in completed if j.get("origin_id") == origin_id]

    groups = {}
    for job in completed:
        otype = job.get("origin_type") or "manual"
        oid = job.get("origin_id") or ""
        key = f"{otype}:{oid}" if oid else otype

        if key not in groups:
            groups[key] = {
                "origin_type": otype,
                "origin_id": oid or None,
                "origin_name": job.get("origin_name") or oid,
                "total": 0,
                "done": 0,
                "failed": 0,
                "total_cost_usd": 0.0,
                "jobs": [],
            }
        g = groups[key]
        g["total"] += 1
        if job["status"] == "done":
            g["done"] += 1
        else:
            g["failed"] += 1
        if job.get("cost_usd"):
            g["total_cost_usd"] += job["cost_usd"]
        # 결과 요약: 전체 텍스트 대신 200자 이하로 축약
        entry = {k: v for k, v in job.items() if k != "result"}
        if job.get("result"):
            entry["result_summary"] = job["result"][:200]
        g["jobs"].append(entry)

    for g in groups.values():
        g["jobs"] = g["jobs"][:limit]
        g["total_cost_usd"] = round(g["total_cost_usd"], 4) if g["total_cost_usd"] else None

    sorted_groups = sorted(
        groups.values(),
        key=lambda g: g["jobs"][0]["created_at"] if g["jobs"] else "",
        reverse=True,
    )
    return {"origins": sorted_groups}


