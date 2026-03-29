"""
Pipeline Engine — 자기 진화형 자동화

핵심 기능:
  1. 컨텍스트 주입 — 실행 전 git log + 이전 결과를 프롬프트에 자동 삽입
  2. 프롬프트 개선 — 연속 무변경 시 다른 관점으로 접근하도록 힌트 주입
  3. 파이프라인 체이닝 — 완료 시 다른 파이프라인 트리거

CRUD/유틸리티: pipeline_crud.py
결과 분류/컨텍스트: pipeline_classify.py, pipeline_context.py
"""

import fcntl
import time

from config import DATA_DIR
from jobs import send_to_fifo, get_job_result
from pipeline_classify import classify_result
from pipeline_context import get_git_snapshot, should_skip_dispatch, build_enriched_prompt
from pipeline_crud import (
    # 재수출: handler_crud.py 등 외부에서 pipeline 모듈을 통해 접근
    list_pipelines, get_pipeline, create_pipeline, delete_pipeline,  # noqa: F401
    modify_pipeline as update_pipeline,  # noqa: F401
    get_pipeline_status, get_pipeline_history, get_evolution_summary,  # noqa: F401
    # 내부 사용
    pipeline_lock, load_pipelines, save_pipelines, update_pipeline as _update_pipeline,
    resolve_job as _resolve_job, next_run_str as _next_run_str,
    parse_timestamp as _parse_timestamp, MAX_HISTORY as _MAX_HISTORY,
)


# ══════════════════════════════════════════════════════════════
#  핵심: dispatch + tick
# ══════════════════════════════════════════════════════════════

_AUTO_PAUSE_THRESHOLD = 5


def dispatch(pipe_id: str, force: bool = False) -> tuple[dict | None, str | None]:
    """작업을 FIFO로 전송한다. 컨텍스트 주입 + 적응형 인터벌 적용."""
    with pipeline_lock():
        pipelines = load_pipelines()
        pipe = None
        for p in pipelines:
            if p["id"] == pipe_id:
                pipe = p
                break
        if not pipe:
            return None, "파이프라인을 찾을 수 없습니다"
        if pipe["status"] != "active":
            return None, "파이프라인이 꺼져 있습니다"
        if pipe.get("job_id"):
            return {"action": "already_running", "job_id": pipe["job_id"]}, None

        if not force:
            skip, reason = should_skip_dispatch(pipe)
            if skip:
                interval_sec = pipe.get("interval_sec")
                if interval_sec:
                    pipe["next_run"] = _next_run_str(interval_sec)
                pipe["skip_count"] = pipe.get("skip_count", 0) + 1
                pipe["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                save_pipelines(pipelines)
                return {"action": "skipped", "reason": reason, "name": pipe["name"]}, None

            history = pipe.get("history", [])
            consecutive_idle = 0
            for h in reversed(history):
                cls = h.get("classification", "unknown")
                if cls in ("no_change", "unknown"):
                    consecutive_idle += 1
                else:
                    break
            if consecutive_idle >= _AUTO_PAUSE_THRESHOLD:
                pipe["status"] = "stopped"
                pipe["last_error"] = f"자동 일시정지: 연속 {consecutive_idle}회 무변경"
                pipe["next_run"] = None
                pipe["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                save_pipelines(pipelines)
                return {
                    "action": "auto_paused",
                    "reason": f"연속 {consecutive_idle}회 무변경 → 자동 일시정지",
                    "name": pipe["name"],
                }, None

        pipe["job_id"] = "__dispatching__"
        pipe["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_pipelines(pipelines)

    enriched_prompt = build_enriched_prompt(pipe)
    result, send_err = send_to_fifo(enriched_prompt, cwd=pipe["project_path"])

    if send_err:
        def clear_marker(p):
            p["job_id"] = None
            p["last_error"] = f"FIFO 전송 실패: {send_err}"
        _update_pipeline(pipe_id, clear_marker)
        return None, f"FIFO 전송 실패: {send_err}"

    job_id = result["job_id"]
    interval_sec = pipe.get("interval_sec")
    nr = _next_run_str(interval_sec) if interval_sec else None

    git_snapshot = get_git_snapshot(pipe["project_path"])

    def do_dispatch(p, _snapshot=git_snapshot):
        p["job_id"] = job_id
        p["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        p["last_error"] = None
        p["next_run"] = nr
        p["last_git_snapshot"] = _snapshot
    _update_pipeline(pipe_id, do_dispatch)

    return {
        "action": "dispatched",
        "job_id": job_id,
        "name": pipe["name"],
        "next_run": nr,
        "context_injected": bool(enriched_prompt != pipe["command"]),
    }, None


def tick(pipe_id: str) -> tuple[dict | None, str | None]:
    """active 파이프라인의 job 완료를 확인한다."""
    pipe, err = get_pipeline(pipe_id)
    if err:
        return None, err
    if pipe["status"] != "active":
        return {"action": "off"}, None

    job_id = pipe.get("job_id")
    if not job_id:
        if pipe.get("next_run") and _parse_timestamp(pipe["next_run"]) > time.time():
            remaining = int(_parse_timestamp(pipe["next_run"]) - time.time())
            return {"action": "waiting", "remaining_sec": remaining}, None
        return dispatch(pipe_id)

    if job_id == "__dispatching__":
        return {"action": "dispatching"}, None

    resolved_cache = pipe.get("resolved_job_id")
    result_text, result_err, resolved = _resolve_job(job_id, resolved_cache)

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

    # ── 완료: 히스토리 기록 + 적응형 인터벌 + 체이닝 ──
    summary = (result_text or "")[:500]
    classification = classify_result(result_text or "")

    cost_usd = None
    duration_ms = None
    if resolved:
        full_result, _ = get_job_result(resolved)
        if full_result:
            cost_usd = full_result.get("cost_usd")
            duration_ms = full_result.get("duration_ms")

    chain_target = pipe.get("on_complete")

    def complete(p, _s=summary, _c=classification,
                 _cost=cost_usd, _dur=duration_ms):
        p["last_result"] = _s
        p["run_count"] = p.get("run_count", 0) + 1
        p["job_id"] = None
        p.pop("resolved_job_id", None)

        history = p.get("history", [])
        history.append({
            "result": _s,
            "classification": _c,
            "cost_usd": _cost,
            "duration_ms": _dur,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
        p["history"] = history

        if p.get("interval_sec"):
            p["next_run"] = _next_run_str(p["interval_sec"])

    _update_pipeline(pipe_id, complete)

    chain_result = None
    if chain_target:
        chain_result, chain_err = dispatch(chain_target)
        if chain_err:
            chain_result = {"chain_error": chain_err}

    response = {
        "action": "completed",
        "run_count": pipe.get("run_count", 0) + 1,
        "classification": classification,
    }
    if chain_result:
        response["chain"] = chain_result

    return response, None


# ══════════════════════════════════════════════════════════════
#  액션 함수
# ══════════════════════════════════════════════════════════════

def run_next(pipe_id: str) -> tuple[dict | None, str | None]:
    """ON으로 켜고 즉시 dispatch (스킵 가드 우회)."""
    def activate(p):
        p["status"] = "active"
        p["job_id"] = None
        p["next_run"] = None
        p["last_error"] = None
    _update_pipeline(pipe_id, activate)
    return dispatch(pipe_id, force=True)


def stop_pipeline(pipe_id: str) -> tuple[dict | None, str | None]:
    """OFF로 끈다."""
    def stop(p):
        p["status"] = "stopped"
        p["job_id"] = None
        p["next_run"] = None
        p["last_error"] = None
    return _update_pipeline(pipe_id, stop)


def reset_phase(pipe_id: str, phase: str = None) -> tuple[dict | None, str | None]:
    """상태 초기화 후 즉시 실행."""
    return run_next(pipe_id)


# ══════════════════════════════════════════════════════════════
#  Tick All
# ══════════════════════════════════════════════════════════════

_TICK_ALL_LOCK = DATA_DIR / ".tick_all.lock"
_TICK_ALL_DEBOUNCE_SEC = 3


def tick_all() -> list[dict]:
    """모든 active 파이프라인을 tick한다. debounce 적용."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = open(_TICK_ALL_LOCK, "a+")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return [{"skip": True, "reason": "another tick_all in progress"}]

    try:
        fd.seek(0)
        last_tick_str = fd.read().strip()
        if last_tick_str:
            try:
                last_tick = float(last_tick_str)
                if time.time() - last_tick < _TICK_ALL_DEBOUNCE_SEC:
                    return [{"skip": True, "reason": "debounced"}]
            except ValueError:
                pass

        fd.seek(0)
        fd.truncate()
        fd.write(str(time.time()))
        fd.flush()

        results = []
        for p in load_pipelines():
            if p["status"] == "active":
                result, err = tick(p["id"])
                results.append({"pipeline_id": p["id"], "name": p["name"], "result": result, "error": err})
        return results
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
