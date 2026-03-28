"""
Pipeline Engine — on/off 자동화

상태: active / stopped
  active + job_id → 작업 실행 중
  active + !job_id → 대기 중 (next_run 카운트다운)
  stopped → 꺼짐

저장: data/pipelines.json
"""

import json
import os
import re
import time
from pathlib import Path

from config import DATA_DIR, LOGS_DIR
from jobs import send_to_fifo, get_job_result
from utils import parse_meta_file

PIPELINES_FILE = DATA_DIR / "pipelines.json"


# ══════════════════════════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════════════════════════

def _load_pipelines() -> list[dict]:
    try:
        if PIPELINES_FILE.exists():
            return json.loads(PIPELINES_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_pipelines(pipelines: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PIPELINES_FILE.write_text(
        json.dumps(pipelines, ensure_ascii=False, indent=2), "utf-8"
    )


def _generate_id() -> str:
    return f"pipe-{int(time.time())}-{os.getpid() % 10000}"


def _parse_interval(interval: str | None) -> int | None:
    if not interval:
        return None
    m = re.match(r"^(\d+)\s*(s|m|h)$", interval.strip())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    return val * {"s": 1, "m": 60, "h": 3600}[unit]


def _uuid_to_job_id(uuid: str) -> str | None:
    if not LOGS_DIR.exists():
        return None
    for mf in sorted(LOGS_DIR.glob("job_*.meta"), reverse=True):
        meta = parse_meta_file(mf)
        if meta and meta.get("UUID") == uuid:
            return meta.get("JOB_ID")
    return None


_UUID_RESOLVE_TIMEOUT = 300


def _resolve_job(job_id: str, resolved_cache: str = None) -> tuple[str | None, str | None, str]:
    """job 결과 조회. 반환: (result_text, error, resolved_id)"""
    resolved = resolved_cache or _uuid_to_job_id(job_id) or job_id
    result, err = get_job_result(resolved)
    if err:
        if "-web-" in job_id:
            try:
                if time.time() - int(job_id.split("-")[0]) > _UUID_RESOLVE_TIMEOUT:
                    return None, "작업 유실", resolved
            except (ValueError, IndexError):
                pass
            return None, "running", resolved
        return None, err, resolved
    if result and result.get("status") == "running":
        return None, "running", resolved
    if result:
        return result.get("result", ""), None, resolved
    return None, "결과 없음", resolved


def _update_pipeline(pipe_id: str, updater):
    pipelines = _load_pipelines()
    for p in pipelines:
        if p["id"] == pipe_id:
            updater(p)
            p["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save_pipelines(pipelines)
            return p, None
    return None, "파이프라인을 찾을 수 없습니다"


def _parse_timestamp(ts: str) -> float:
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0


def _next_run_str(interval_sec: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + interval_sec))


# ══════════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════════

def list_pipelines() -> list[dict]:
    return _load_pipelines()


def get_pipeline(pipe_id: str) -> tuple[dict | None, str | None]:
    for p in _load_pipelines():
        if p["id"] == pipe_id:
            return p, None
    return None, "파이프라인을 찾을 수 없습니다"


def create_pipeline(project_path: str, command: str, interval: str = "", name: str = "") -> tuple[dict | None, str | None]:
    project_path = os.path.abspath(os.path.expanduser(project_path))
    if not command.strip():
        return None, "명령어(command)를 입력하세요"
    if not name:
        name = os.path.basename(project_path)

    interval_sec = _parse_interval(interval) if interval else None
    pipelines = _load_pipelines()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    pipe = {
        "id": _generate_id(),
        "name": name,
        "project_path": project_path,
        "command": command,
        "interval": interval or None,
        "interval_sec": interval_sec,
        "status": "active",
        "job_id": None,
        "next_run": None,
        "last_run": None,
        "last_result": None,
        "last_error": None,
        "run_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    pipelines.append(pipe)
    _save_pipelines(pipelines)
    return pipe, None


def update_pipeline(pipe_id: str, command: str = None, interval: str = None, name: str = None) -> tuple[dict | None, str | None]:
    def updater(p):
        if command is not None:
            p["command"] = command
        if name is not None:
            p["name"] = name
        if interval is not None:
            if interval == "":
                p["interval"] = None
                p["interval_sec"] = None
            else:
                p["interval"] = interval
                p["interval_sec"] = _parse_interval(interval)
    return _update_pipeline(pipe_id, updater)


def delete_pipeline(pipe_id: str) -> tuple[dict | None, str | None]:
    pipelines = _load_pipelines()
    for i, p in enumerate(pipelines):
        if p["id"] == pipe_id:
            removed = pipelines.pop(i)
            _save_pipelines(pipelines)
            return removed, None
    return None, "파이프라인을 찾을 수 없습니다"


# ══════════════════════════════════════════════════════════════
#  핵심: dispatch + tick
# ══════════════════════════════════════════════════════════════

def dispatch(pipe_id: str) -> tuple[dict | None, str | None]:
    """작업을 FIFO로 전송하고 next_run을 설정한다."""
    pipe, err = get_pipeline(pipe_id)
    if err:
        return None, err
    if pipe["status"] != "active":
        return None, "파이프라인이 꺼져 있습니다"

    result, send_err = send_to_fifo(pipe["command"], cwd=pipe["project_path"])
    if send_err:
        return None, f"FIFO 전송 실패: {send_err}"

    job_id = result["job_id"]
    nr = _next_run_str(pipe["interval_sec"]) if pipe.get("interval_sec") else None

    def do_dispatch(p):
        p["job_id"] = job_id
        p["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        p["last_error"] = None
        p["next_run"] = nr
    _update_pipeline(pipe_id, do_dispatch)

    return {"action": "dispatched", "job_id": job_id, "name": pipe["name"], "next_run": nr}, None


def tick(pipe_id: str) -> tuple[dict | None, str | None]:
    """active 파이프라인의 job 완료를 확인한다."""
    pipe, err = get_pipeline(pipe_id)
    if err:
        return None, err
    if pipe["status"] != "active":
        return {"action": "off"}, None

    job_id = pipe.get("job_id")
    if not job_id:
        # job 없음 → next_run 확인 후 dispatch
        if pipe.get("next_run") and _parse_timestamp(pipe["next_run"]) > time.time():
            remaining = int(_parse_timestamp(pipe["next_run"]) - time.time())
            return {"action": "waiting", "remaining_sec": remaining}, None
        return dispatch(pipe_id)

    # job 실행 중 → 완료 확인
    resolved_cache = pipe.get("resolved_job_id")
    result_text, result_err, resolved = _resolve_job(job_id, resolved_cache)

    # UUID 해석 결과 캐싱
    if resolved != job_id and not resolved_cache:
        def cache(p, _r=resolved):
            p["resolved_job_id"] = _r
        _update_pipeline(pipe_id, cache)

    if result_err == "running":
        return {"action": "running", "job_id": resolved}, None

    if result_err:
        def set_err(p, _e=result_err):
            p["last_error"] = _e
            p["job_id"] = None
            p.pop("resolved_job_id", None)
        _update_pipeline(pipe_id, set_err)
        return {"action": "error", "error": result_err}, None

    # 완료
    summary = (result_text or "")[:200]
    def complete(p, _s=summary):
        p["last_result"] = _s
        p["run_count"] = p.get("run_count", 0) + 1
        p["job_id"] = None
        p.pop("resolved_job_id", None)
    _update_pipeline(pipe_id, complete)

    return {"action": "completed", "run_count": pipe.get("run_count", 0) + 1}, None


# ══════════════════════════════════════════════════════════════
#  액션 함수
# ══════════════════════════════════════════════════════════════

def run_next(pipe_id: str) -> tuple[dict | None, str | None]:
    """ON으로 켜고 즉시 dispatch."""
    def activate(p):
        p["status"] = "active"
        p["job_id"] = None
        p["next_run"] = None
        p["last_error"] = None
    _update_pipeline(pipe_id, activate)
    return dispatch(pipe_id)


def force_run(pipe_id: str) -> tuple[dict | None, str | None]:
    return run_next(pipe_id)


def stop_pipeline(pipe_id: str) -> tuple[dict | None, str | None]:
    """OFF로 끈다."""
    def stop(p):
        p["status"] = "stopped"
        p["job_id"] = None
        p["next_run"] = None
        p["last_error"] = None
    return _update_pipeline(pipe_id, stop)


def reset_phase(pipe_id: str, phase: str = None) -> tuple[dict | None, str | None]:
    return run_next(pipe_id)


def get_pipeline_status(pipe_id: str) -> tuple[dict | None, str | None]:
    pipe, err = get_pipeline(pipe_id)
    if err:
        return None, err

    job_status = None
    if pipe.get("job_id"):
        resolved = pipe.get("resolved_job_id") or _uuid_to_job_id(pipe["job_id"]) or pipe["job_id"]
        result, _ = get_job_result(resolved)
        if result:
            job_status = {
                "job_id": resolved,
                "status": result.get("status"),
                "cost_usd": result.get("cost_usd"),
                "duration_ms": result.get("duration_ms"),
            }

    remaining_sec = None
    if pipe.get("next_run"):
        remaining_sec = max(0, int(_parse_timestamp(pipe["next_run"]) - time.time()))

    return {
        "id": pipe["id"],
        "name": pipe["name"],
        "project_path": pipe["project_path"],
        "command": pipe["command"],
        "interval": pipe.get("interval"),
        "status": pipe["status"],
        "job_id": pipe.get("job_id"),
        "job_status": job_status,
        "next_run": pipe.get("next_run"),
        "remaining_sec": remaining_sec,
        "last_run": pipe.get("last_run"),
        "last_result": pipe.get("last_result"),
        "last_error": pipe.get("last_error"),
        "run_count": pipe.get("run_count", 0),
        "created_at": pipe["created_at"],
        "updated_at": pipe["updated_at"],
    }, None


# ══════════════════════════════════════════════════════════════
#  Tick All
# ══════════════════════════════════════════════════════════════

def tick_all() -> list[dict]:
    results = []
    for p in _load_pipelines():
        if p["status"] == "active":
            result, err = tick(p["id"])
            results.append({"pipeline_id": p["id"], "name": p["name"], "result": result, "error": err})
    return results
