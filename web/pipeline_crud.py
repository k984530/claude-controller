"""
Pipeline CRUD + 유틸리티

pipeline.py에서 분리:
  - 파일 I/O: _load_pipelines, _save_pipelines, _pipeline_lock
  - CRUD: list/get/create/update/delete
  - 유틸리티: _parse_interval, _parse_timestamp, _next_run_str, _resolve_job 등
  - 상태 조회: get_pipeline_status, get_pipeline_history, get_evolution_summary
"""

import fcntl
import json
import os
import re
import time
from contextlib import contextmanager

from config import DATA_DIR, LOGS_DIR
from jobs import get_job_result
from utils import parse_meta_file, generate_id

PIPELINES_FILE = DATA_DIR / "pipelines.json"

# 히스토리 최대 보관 수
MAX_HISTORY = 10


# ══════════════════════════════════════════════════════════════
#  파일 I/O + 잠금
# ══════════════════════════════════════════════════════════════

_LOCK_FILE = DATA_DIR / "pipelines.lock"


@contextmanager
def pipeline_lock():
    """pipelines.json에 대한 파일 수준 배타적 잠금."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


# 제거된 기능의 잔여 필드 — 로드 시 자동 삭제
_DEPRECATED_FIELDS = {"effective_interval_sec", "adaptive_multiplier", "skip_count"}


def load_pipelines() -> list[dict]:
    try:
        if PIPELINES_FILE.exists():
            pipes = json.loads(PIPELINES_FILE.read_text("utf-8"))
            dirty = False
            for p in pipes:
                for field in _DEPRECATED_FIELDS:
                    if field in p:
                        del p[field]
                        dirty = True
            if dirty:
                save_pipelines(pipes)
            return pipes
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_pipelines(pipelines: list[dict]):
    """원자적 쓰기 + 파이프라인 수 감소 안전장치."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing_count = 0
    backup_path = PIPELINES_FILE.with_suffix(".bak")
    if PIPELINES_FILE.exists():
        try:
            existing = json.loads(PIPELINES_FILE.read_text("utf-8"))
            existing_count = len(existing)
        except (json.JSONDecodeError, OSError):
            pass

        if existing_count > 0 and len(pipelines) < existing_count:
            import shutil
            import sys
            shutil.copy2(PIPELINES_FILE, backup_path)
            print(
                f"[pipeline] WARNING: 파이프라인 수 감소 {existing_count} → {len(pipelines)}, "
                f"백업 저장: {backup_path}",
                file=sys.stderr,
            )

    tmp = PIPELINES_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(pipelines, ensure_ascii=False, indent=2), "utf-8"
    )
    tmp.rename(PIPELINES_FILE)


# ══════════════════════════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════════════════════════

def parse_interval(interval: str | None) -> int | None:
    if not interval:
        return None
    m = re.match(r"^(\d+)\s*(s|m|h)$", interval.strip())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    return val * {"s": 1, "m": 60, "h": 3600}[unit]


def uuid_to_job_id(uuid: str) -> str | None:
    if not LOGS_DIR.exists():
        return None
    for mf in sorted(LOGS_DIR.glob("job_*.meta"), reverse=True):
        meta = parse_meta_file(mf)
        if meta and meta.get("UUID") == uuid:
            return meta.get("JOB_ID")
    return None


_UUID_RESOLVE_TIMEOUT = 300


def resolve_job(job_id: str, resolved_cache: str = None) -> tuple[str | None, str | None, str]:
    """job 결과 조회. 반환: (result_text, error, resolved_id)"""
    resolved = resolved_cache or uuid_to_job_id(job_id) or job_id
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


def parse_timestamp(ts: str) -> float:
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0


def next_run_str(interval_sec: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + interval_sec))


def update_pipeline(pipe_id: str, updater):
    """lock 안에서 파이프라인을 찾아 updater 콜백을 실행하고 저장한다."""
    with pipeline_lock():
        pipelines = load_pipelines()
        for p in pipelines:
            if p["id"] == pipe_id:
                updater(p)
                p["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                save_pipelines(pipelines)
                return p, None
    return None, "파이프라인을 찾을 수 없습니다"


# ══════════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════════

def list_pipelines() -> list[dict]:
    return load_pipelines()


def get_pipeline(pipe_id: str) -> tuple[dict | None, str | None]:
    for p in load_pipelines():
        if p["id"] == pipe_id:
            return p, None
    return None, "파이프라인을 찾을 수 없습니다"


def create_pipeline(
    project_path: str, command: str, interval: str = "",
    name: str = "", on_complete: str = "", skill_ids: list | None = None,
) -> tuple[dict | None, str | None]:
    project_path = os.path.abspath(os.path.expanduser(project_path))
    if not command.strip():
        return None, "명령어(command)를 입력하세요"
    if not name:
        name = os.path.basename(project_path)

    interval_sec = parse_interval(interval) if interval else None
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    pipe = {
        "id": generate_id("pipe"),
        "name": name,
        "project_path": project_path,
        "command": command,
        "skill_ids": skill_ids or [],
        "interval": interval or None,
        "interval_sec": interval_sec,
        "status": "active",
        "job_id": None,
        "next_run": None,
        "last_run": None,
        "last_result": None,
        "last_error": None,
        "run_count": 0,
        "history": [],
        "on_complete": on_complete or None,
        "created_at": now,
        "updated_at": now,
    }
    with pipeline_lock():
        pipelines = load_pipelines()
        pipelines.append(pipe)
        save_pipelines(pipelines)
    return pipe, None


def modify_pipeline(
    pipe_id: str, command: str = None, interval: str = None,
    name: str = None, on_complete: str = None, skill_ids: list | None = None,
) -> tuple[dict | None, str | None]:
    def updater(p):
        if command is not None:
            p["command"] = command
        if name is not None:
            p["name"] = name
        if on_complete is not None:
            p["on_complete"] = on_complete if on_complete else None
        if skill_ids is not None:
            p["skill_ids"] = skill_ids
        if interval is not None:
            if interval == "":
                p["interval"] = None
                p["interval_sec"] = None
                p["next_run"] = None
            else:
                new_sec = parse_interval(interval)
                p["interval"] = interval
                p["interval_sec"] = new_sec
                if p.get("status") == "active" and not p.get("job_id") and new_sec:
                    p["next_run"] = next_run_str(new_sec)
    return update_pipeline(pipe_id, updater)


def delete_pipeline(pipe_id: str) -> tuple[dict | None, str | None]:
    with pipeline_lock():
        pipelines = load_pipelines()
        for i, p in enumerate(pipelines):
            if p["id"] == pipe_id:
                removed = pipelines.pop(i)
                save_pipelines(pipelines)
                return removed, None
    return None, "파이프라인을 찾을 수 없습니다"


# ══════════════════════════════════════════════════════════════
#  상태 조회
# ══════════════════════════════════════════════════════════════

def get_pipeline_status(pipe_id: str) -> tuple[dict | None, str | None]:
    pipe, err = get_pipeline(pipe_id)
    if err:
        return None, err

    job_status = None
    if pipe.get("job_id"):
        resolved = pipe.get("resolved_job_id") or uuid_to_job_id(pipe["job_id"]) or pipe["job_id"]
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
        remaining_sec = max(0, int(parse_timestamp(pipe["next_run"]) - time.time()))

    history = pipe.get("history", [])
    total_cost = sum(h.get("cost_usd", 0) or 0 for h in history)
    classifications = [h.get("classification", "unknown") for h in history]

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
        "on_complete": pipe.get("on_complete"),
        "history_count": len(history),
        "total_cost_usd": round(total_cost, 4) if total_cost else None,
        "classifications": classifications[-5:],
        "created_at": pipe["created_at"],
        "updated_at": pipe["updated_at"],
    }, None


def get_pipeline_history(pipe_id: str) -> tuple[dict | None, str | None]:
    pipe, err = get_pipeline(pipe_id)
    if err:
        return None, err
    history = pipe.get("history", [])
    return {
        "id": pipe["id"],
        "name": pipe["name"],
        "run_count": pipe.get("run_count", 0),
        "total_cost_usd": round(sum(h.get("cost_usd", 0) or 0 for h in history), 4),
        "entries": list(reversed(history)),
    }, None


def get_evolution_summary() -> dict:
    """전체 파이프라인 시스템의 자기 진화 상태를 요약한다."""
    pipelines = load_pipelines()
    active = [p for p in pipelines if p["status"] == "active"]
    total_runs = sum(p.get("run_count", 0) for p in pipelines)
    total_cost = 0
    all_classifications = {"has_change": 0, "no_change": 0, "unknown": 0}

    for p in pipelines:
        for h in p.get("history", []):
            cost = h.get("cost_usd")
            if cost:
                total_cost += cost
            cls = h.get("classification", "unknown")
            all_classifications[cls] = all_classifications.get(cls, 0) + 1

    total_classified = sum(all_classifications.values())
    efficiency = (
        round(all_classifications["has_change"] / total_classified * 100, 1)
        if total_classified > 0 else 0
    )

    auto_paused = [
        {"name": p["name"], "reason": p.get("last_error", "")}
        for p in pipelines
        if p["status"] == "stopped" and (p.get("last_error") or "").startswith("자동 일시정지")
    ]

    total_skips = sum(p.get("skip_count", 0) for p in pipelines)

    return {
        "active_count": len(active),
        "total_pipelines": len(pipelines),
        "total_runs": total_runs,
        "total_skips": total_skips,
        "total_cost_usd": round(total_cost, 4),
        "classifications": all_classifications,
        "efficiency_pct": efficiency,
        "auto_paused": auto_paused,
    }
