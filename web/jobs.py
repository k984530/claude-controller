"""
Controller Service — Job 관리 및 서비스 제어 함수
"""

import json
import os
import re
import signal
import subprocess
import time

from config import LOGS_DIR, FIFO_PATH, SERVICE_SCRIPT, CONTROLLER_DIR
from utils import parse_meta_file, is_service_running


# ════════════════════════════════════════════════
#  에러 분류 — 원시 에러 텍스트를 사용자 친화적 메시지로 변환
# ════════════════════════════════════════════════

_ERROR_PATTERNS = [
    {
        "patterns": [r"rate.?limit", r"429", r"overloaded", r"too many requests", r"capacity"],
        "summary": "API 요청 한도 초과",
        "cause": "Claude API의 요청 제한에 도달했습니다. 단시간에 너무 많은 작업을 전송했을 수 있습니다.",
        "next_steps": ["잠시 후 다시 시도하세요 (1~2분 대기 권장)", "동시 실행 작업 수를 줄여보세요"],
    },
    {
        "patterns": [r"api.?key", r"unauthorized", r"401", r"authentication.*fail", r"invalid.*key", r"ANTHROPIC_API_KEY"],
        "summary": "API 인증 실패",
        "cause": "Claude API 키가 유효하지 않거나 설정되지 않았습니다.",
        "next_steps": ["ANTHROPIC_API_KEY 환경변수가 올바르게 설정되었는지 확인하세요", "API 키가 만료되지 않았는지 확인하세요"],
    },
    {
        "patterns": [r"permission.?denied", r"EACCES", r"Operation not permitted"],
        "summary": "파일 접근 권한 오류",
        "cause": "작업 대상 파일이나 디렉토리에 대한 읽기/쓰기 권한이 없습니다.",
        "next_steps": ["작업 디렉토리의 파일 권한을 확인하세요", "다른 프로세스가 파일을 잠그고 있지 않은지 확인하세요"],
    },
    {
        "patterns": [r"FIFO", r"Broken pipe", r"EPIPE", r"fifo.*not.*exist"],
        "summary": "서비스 통신 오류",
        "cause": "Controller 서비스와의 통신 파이프(FIFO)가 끊어졌습니다.",
        "next_steps": ["서비스를 재시작하세요", "서비스 상태를 확인하세요 (상단 연결 상태 참조)"],
    },
    {
        "patterns": [r"timed?\s*out", r"ETIMEDOUT", r"deadline.?exceeded", r"timeout"],
        "summary": "작업 시간 초과",
        "cause": "작업이 제한 시간 내에 완료되지 않았습니다. 프롬프트가 너무 복잡하거나 대상 파일이 너무 클 수 있습니다.",
        "next_steps": ["프롬프트를 더 작은 단위로 나눠서 시도하세요", "대상 범위를 줄여보세요 (특정 파일/함수 지정)"],
    },
    {
        "patterns": [r"ECONNREFUSED", r"ENOTFOUND", r"network", r"fetch.*fail", r"connection.*refused"],
        "summary": "네트워크 연결 오류",
        "cause": "외부 서비스에 연결할 수 없습니다. 네트워크가 불안정하거나 API 서버에 문제가 있을 수 있습니다.",
        "next_steps": ["인터넷 연결 상태를 확인하세요", "잠시 후 다시 시도하세요"],
    },
    {
        "patterns": [r"context.*(?:length|limit|window)", r"too.?long", r"max.*token", r"token.*limit", r"prompt.*too.*large"],
        "summary": "컨텍스트 길이 초과",
        "cause": "입력 프롬프트나 작업 대상 파일이 Claude의 처리 가능 범위를 초과했습니다.",
        "next_steps": ["프롬프트를 더 짧게 줄여보세요", "대상 파일 범위를 줄이세요 (특정 함수나 섹션만 지정)"],
    },
    {
        "patterns": [r"ENOSPC", r"no space", r"disk.*full"],
        "summary": "디스크 공간 부족",
        "cause": "서버 디스크에 여유 공간이 없어서 작업 결과를 저장할 수 없습니다.",
        "next_steps": ["불필요한 파일을 정리하세요", "'완료 삭제' 버튼으로 오래된 작업 로그를 제거하세요"],
    },
    {
        "patterns": [r"SIGKILL", r"killed", r"signal.*9", r"OOM", r"out of memory", r"ENOMEM"],
        "summary": "프로세스가 강제 종료됨",
        "cause": "작업 프로세스가 시스템에 의해 강제 종료되었습니다. 메모리 부족이 원인일 수 있습니다.",
        "next_steps": ["시스템 메모리 사용량을 확인하세요", "동시 실행 작업 수를 줄여보세요"],
    },
    {
        "patterns": [r"ENOENT", r"no such file", r"not found.*path", r"directory.*not.*exist"],
        "summary": "파일 또는 디렉토리를 찾을 수 없음",
        "cause": "작업에서 참조한 파일이나 디렉토리가 존재하지 않습니다.",
        "next_steps": ["작업 디렉토리(cwd) 경로가 올바른지 확인하세요", "대상 파일이 삭제되거나 이동되지 않았는지 확인하세요"],
    },
    {
        "patterns": [r"git.*conflict", r"merge conflict", r"CONFLICT"],
        "summary": "Git 충돌 발생",
        "cause": "작업 중 Git merge conflict가 발생했습니다.",
        "next_steps": ["충돌이 발생한 파일을 수동으로 해결하세요", "작업 전에 최신 코드를 pull하세요"],
    },
    {
        "patterns": [r"worktree.*(?:fail|error|lock)", r"already.*checked.*out"],
        "summary": "Git Worktree 오류",
        "cause": "격리 실행을 위한 Git worktree 생성에 실패했습니다.",
        "next_steps": ["기존 worktree가 정리되지 않았다면 'git worktree prune'을 실행하세요", "작업 디렉토리가 유효한 Git 저장소인지 확인하세요"],
    },
]


def classify_error(raw_text):
    """원시 에러 텍스트를 분류하여 사용자 친화적 메시지를 반환한다.

    Returns:
        dict: {"summary": str, "cause": str, "next_steps": list[str]}
        None이면 분류 불가 (에러가 아닌 경우).
    """
    if not raw_text:
        return None

    for rule in _ERROR_PATTERNS:
        for pattern in rule["patterns"]:
            if re.search(pattern, raw_text, re.IGNORECASE):
                return {
                    "summary": rule["summary"],
                    "cause": rule["cause"],
                    "next_steps": rule["next_steps"],
                }

    return {
        "summary": "작업이 실패했습니다",
        "cause": "예상하지 못한 오류가 발생했습니다.",
        "next_steps": ["아래 상세 로그를 확인하세요", "같은 프롬프트로 다시 실행해보세요"],
    }


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
            unmet = _check_dependencies(deps)
            if unmet:
                return _create_pending_job(prompt, cwd, job_id, images, session, deps)

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


# ════════════════════════════════════════════════
#  작업 의존성 DAG — pending 작업 관리
# ════════════════════════════════════════════════

def _check_dependencies(depends_on):
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


def _next_job_id_py():
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


def _create_pending_job(prompt, cwd, uuid, images, session, depends_on):
    """의존성이 충족되지 않은 작업을 pending 상태로 등록한다."""
    new_id = _next_job_id_py()
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

        unmet = _check_dependencies(depends_on)
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
