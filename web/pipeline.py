"""
Pipeline Engine — 자기 진화형 자동화

핵심 기능:
  1. on/off 자동화 (기존)
  2. 컨텍스트 주입 — 실행 전 git log + 이전 결과를 프롬프트에 자동 삽입
  3. 결과 히스토리 — 최근 N개 결과 저장으로 패턴 감지
  4. 적응형 인터벌 — 결과 기반 실행 주기 자동 조절
  5. 파이프라인 체이닝 — 완료 시 다른 파이프라인 트리거

상태: active / stopped
저장: data/pipelines.json
"""

import fcntl
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager

from config import DATA_DIR, LOGS_DIR
from jobs import send_to_fifo, get_job_result
from utils import parse_meta_file

PIPELINES_FILE = DATA_DIR / "pipelines.json"

# 히스토리 최대 보관 수
_MAX_HISTORY = 10

# 적응형 인터벌 범위 (초)
_MIN_INTERVAL_SEC = 60       # 최소 1분
_MAX_INTERVAL_SEC = 14400    # 최대 4시간 (이전: 1시간 — 너무 보수적)


# ══════════════════════════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════════════════════════

_LOCK_FILE = DATA_DIR / "pipelines.lock"


@contextmanager
def _pipeline_lock():
    """pipelines.json에 대한 파일 수준 배타적 잠금.

    동시에 여러 스레드/프로세스가 load→modify→save 하면 뒤쪽 쓰기가
    앞쪽 변경을 덮어쓴다. flock으로 직렬화하여 데이터 유실을 방지한다.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def _load_pipelines() -> list[dict]:
    try:
        if PIPELINES_FILE.exists():
            return json.loads(PIPELINES_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_pipelines(pipelines: list[dict]):
    """원자적 쓰기: temp 파일에 쓴 뒤 rename으로 교체.

    안전장치: 기존 파이프라인 수보다 줄어들면 백업 생성 + 경고 로그.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 안전장치: 파이프라인 수 감소 감지
    existing_count = 0
    backup_path = PIPELINES_FILE.with_suffix(".bak")
    if PIPELINES_FILE.exists():
        try:
            existing = json.loads(PIPELINES_FILE.read_text("utf-8"))
            existing_count = len(existing)
        except (json.JSONDecodeError, OSError):
            pass

        if existing_count > 0 and len(pipelines) < existing_count:
            # 백업 생성 후 경고 (삭제 API 호출이 아닌 비정상 감소 방지)
            import shutil
            shutil.copy2(PIPELINES_FILE, backup_path)
            import sys
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


_id_counter = 0

def _generate_id() -> str:
    global _id_counter
    _id_counter += 1
    return f"pipe-{int(time.time())}-{os.getpid() % 10000}-{_id_counter}"


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
    with _pipeline_lock():
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
#  Pre-dispatch 스킵 가드 — 변경 없으면 실행 자체를 건너뜀
# ══════════════════════════════════════════════════════════════

def _get_git_head_sha(project_path: str) -> str:
    """프로젝트의 현재 HEAD SHA를 반환한다."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def _get_git_dirty_hash(project_path: str) -> str:
    """uncommitted 변경사항의 해시를 반환한다 (변경 없으면 빈 문자열)."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            cwd=project_path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            import hashlib
            return hashlib.md5(result.stdout.encode()).hexdigest()[:12]
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def _should_skip_dispatch(pipe: dict) -> tuple[bool, str]:
    """Pre-dispatch 스킵 판단. 반환: (skip 여부, 사유).

    스킵 조건:
    1. git HEAD와 dirty hash가 이전 실행과 동일 (코드 변경 없음)
    2. 이전 결과가 no_change이고 연속 무변경 3회 이상
    """
    project_path = pipe["project_path"]

    # 현재 git 상태 스냅샷
    head_sha = _get_git_head_sha(project_path)
    dirty_hash = _get_git_dirty_hash(project_path)
    current_snapshot = f"{head_sha}:{dirty_hash}"

    # 이전 실행 시 git 스냅샷과 비교
    last_snapshot = pipe.get("last_git_snapshot", "")

    if not last_snapshot or current_snapshot != last_snapshot:
        return False, ""  # 코드 변경 있음 → 실행

    # 코드 변경 없음 + 이전 결과 확인
    history = pipe.get("history", [])
    if not history:
        return False, ""  # 히스토리 없음 → 첫 실행이므로 허용

    # 최근 연속 무변경/unknown 횟수
    consecutive_idle = 0
    for h in reversed(history):
        cls = h.get("classification", "unknown")
        if cls in ("no_change", "unknown"):
            consecutive_idle += 1
        else:
            break

    if consecutive_idle >= 2:
        return True, f"git 변경 없음 + 연속 {consecutive_idle}회 무변경"

    return False, ""


# ══════════════════════════════════════════════════════════════
#  컨텍스트 주입 — 프롬프트를 풍부하게 만든다
# ══════════════════════════════════════════════════════════════

def _get_git_context(project_path: str, max_commits: int = 5) -> str:
    """프로젝트의 최근 git 변경사항을 요약한다."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{max_commits}", "--no-decorate"],
            cwd=project_path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def _get_git_diff_stat(project_path: str) -> str:
    """현재 uncommitted 변경사항의 stat을 가져온다."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def _build_enriched_prompt(pipe: dict) -> str:
    """파이프라인의 원본 command에 컨텍스트를 주입한 프롬프트를 생성한다."""
    command = pipe["command"]
    project_path = pipe["project_path"]
    sections = []

    # 1. Git 컨텍스트
    git_log = _get_git_context(project_path)
    git_diff = _get_git_diff_stat(project_path)
    if git_log:
        sections.append(f"[최근 커밋]\n{git_log}")
    if git_diff:
        sections.append(f"[현재 uncommitted 변경]\n{git_diff}")

    # 2. 이전 실행 결과
    history = pipe.get("history", [])
    if history:
        last = history[-1]
        last_summary = (last.get("result", "") or "")[:500]
        last_cost = last.get("cost_usd")
        last_time = last.get("completed_at", "")
        if last_summary:
            cost_info = f" (비용: ${last_cost:.4f})" if last_cost else ""
            sections.append(
                f"[이전 실행 결과 — {last_time}{cost_info}]\n{last_summary}"
            )

    # 3. 실행 통계
    run_count = pipe.get("run_count", 0)
    current_interval = pipe.get("effective_interval_sec") or pipe.get("interval_sec")
    if run_count > 0 and current_interval:
        interval_str = f"{current_interval // 60}분" if current_interval >= 60 else f"{current_interval}초"
        sections.append(
            f"[실행 통계] {run_count}회 실행됨 | 현재 간격: {interval_str}"
        )

    if not sections:
        return command

    context_block = "\n\n".join(sections)
    return f"""=== 자동 주입 컨텍스트 (이전 실행 기반) ===
{context_block}
=== 컨텍스트 끝 ===

{command}"""


# ══════════════════════════════════════════════════════════════
#  적응형 인터벌 — 결과 기반 주기 조절
# ══════════════════════════════════════════════════════════════

_NO_CHANGE_PATTERNS = [
    r"변경.*없",
    r"이슈.*없",
    r"문제.*없",
    r"no\s+(issues?|changes?|problems?)",
    r"nothing\s+to",
    r"all\s+ok",
    r"삭제\s*대상\s*없",
    r"개선.*없",
    r"이미.*해결",
    r"already",
    r"회귀.*없",
    r"오류\s*없",
    r"고임팩트.*없",
    # 테스트 결과 패턴 (all passed, 0 failures)
    r"(?:test|테스트).*(?:pass|통과|성공)",
    r"0\s*(?:fail|error|오류)",
    r"(?:all|모든).*(?:pass|통과|ok|정상)",
    r"ran\s+\d+\s+test.*\nok",
    # 유지보수 결과 패턴
    r"정리.*(?:없|0개|완료)",
    r"(?:디스크|disk).*(?:ok|정상|양호)",
    r"(?:상태|status).*(?:정상|양호|ok|healthy)",
    r"(?:점검|확인).*(?:완료|이상\s*없)",
    r"불필요.*없",
    r"(?:특이|이상)\s*(?:사항|점)\s*없",
    # 코드 분석 결과 패턴
    r"(?:품질|quality).*(?:양호|good|ok)",
    r"(?:취약|vuln).*(?:없|0)",
    r"(?:개선|수정)\s*(?:사항|할\s*것)\s*없",
    r"(?:추가|변경)\s*(?:불필요|사항\s*없)",
    # 일반적 무변경 표현
    r"현재\s*(?:상태|코드).*(?:적절|양호|충분)",
    r"(?:작업|할\s*것).*없",
]

# 개별 분리 — 각 키워드가 독립적으로 1점씩 기여하여
# change_score >= 2 조건이 정확하게 동작한다.
_CHANGE_PATTERNS = [
    r"수정",
    r"변경",
    r"추가",
    r"개선",
    r"구현",
    r"삭제",
    r"교체",
    r"리팩",
    r"fix|change|add|remov|improv|implement|refactor",
    r"Edit|Write",  # 도구 사용 흔적
    r"작성.*완료",
    r"생성.*완료",
    r"파일.*(?:생성|작성|수정)",
    r"커밋|commit",
]


def _classify_result(result_text: str) -> str:
    """결과를 분류한다: 'no_change', 'has_change', 'unknown'"""
    if not result_text:
        return "unknown"
    text = result_text[:2000].lower()

    # 변경 없음 패턴 우선 체크
    for pat in _NO_CHANGE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "no_change"

    # 변경 있음 패턴
    change_score = 0
    for pat in _CHANGE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            change_score += 1
    if change_score >= 2:
        return "has_change"

    return "unknown"


def _adapt_interval(pipe: dict, result_text: str) -> int | None:
    """결과를 기반으로 적응형 인터벌을 계산한다.

    개선점 (v2):
    - no_change: 1.5x~2.0x로 공격적 확대 (이전: 최대 1.3x)
    - unknown: no_change와 동일하게 감속 (이전: 현상 유지로 낭비)
    - has_change: 기본 간격으로 복귀
    """
    base_interval = pipe.get("interval_sec")
    if not base_interval:
        return None

    current = pipe.get("effective_interval_sec") or base_interval
    classification = _classify_result(result_text)
    history = pipe.get("history", [])

    # 최근 연속 idle (no_change + unknown) 횟수
    consecutive_idle = 0
    for h in reversed(history):
        cls = h.get("classification", "unknown")
        if cls in ("no_change", "unknown"):
            consecutive_idle += 1
        else:
            break

    if classification in ("no_change", "unknown"):
        consecutive_idle += 1
        # 공격적 확대: 1.5x 기본, 연속 idle마다 0.1씩 추가 (최대 2.0x)
        multiplier = min(2.0, 1.5 + (consecutive_idle * 0.1))
        new_interval = int(current * multiplier)
    elif classification == "has_change":
        new_interval = base_interval
    else:
        new_interval = current

    return max(_MIN_INTERVAL_SEC, min(_MAX_INTERVAL_SEC, new_interval))


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


def create_pipeline(
    project_path: str, command: str, interval: str = "",
    name: str = "", on_complete: str = "",
) -> tuple[dict | None, str | None]:
    project_path = os.path.abspath(os.path.expanduser(project_path))
    if not command.strip():
        return None, "명령어(command)를 입력하세요"
    if not name:
        name = os.path.basename(project_path)

    interval_sec = _parse_interval(interval) if interval else None
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    pipe = {
        "id": _generate_id(),
        "name": name,
        "project_path": project_path,
        "command": command,
        "interval": interval or None,
        "interval_sec": interval_sec,
        "effective_interval_sec": interval_sec,  # 적응형 인터벌
        "status": "active",
        "job_id": None,
        "next_run": None,
        "last_run": None,
        "last_result": None,
        "last_error": None,
        "run_count": 0,
        "history": [],          # 결과 히스토리
        "on_complete": on_complete or None,  # 체이닝: 완료 시 트리거할 pipe_id
        "created_at": now,
        "updated_at": now,
    }
    with _pipeline_lock():
        pipelines = _load_pipelines()
        pipelines.append(pipe)
        _save_pipelines(pipelines)
    return pipe, None


def update_pipeline(
    pipe_id: str, command: str = None, interval: str = None,
    name: str = None, on_complete: str = None,
) -> tuple[dict | None, str | None]:
    def updater(p):
        if command is not None:
            p["command"] = command
        if name is not None:
            p["name"] = name
        if on_complete is not None:
            p["on_complete"] = on_complete if on_complete else None
        if interval is not None:
            if interval == "":
                p["interval"] = None
                p["interval_sec"] = None
                p["effective_interval_sec"] = None
                p["next_run"] = None
            else:
                new_sec = _parse_interval(interval)
                p["interval"] = interval
                p["interval_sec"] = new_sec
                p["effective_interval_sec"] = new_sec
                # active 상태이고 job 미실행 중이면 next_run도 즉시 재계산
                if p.get("status") == "active" and not p.get("job_id") and new_sec:
                    p["next_run"] = _next_run_str(new_sec)
    return _update_pipeline(pipe_id, updater)


def delete_pipeline(pipe_id: str) -> tuple[dict | None, str | None]:
    with _pipeline_lock():
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

# 자동 일시정지 임계값: 연속 idle 이 횟수 이상이면 자동 pause
_AUTO_PAUSE_THRESHOLD = 5


def dispatch(pipe_id: str, force: bool = False) -> tuple[dict | None, str | None]:
    """작업을 FIFO로 전송한다. 컨텍스트 주입 + 적응형 인터벌 적용.

    이중 발사 방지: lock 안에서 job_id 확인 후 dispatch 여부를 결정한다.
    Pre-dispatch 스킵 가드: git 변경 없고 연속 무변경이면 스킵한다.
    자동 일시정지: 연속 idle 5회 이상이면 파이프라인을 자동 pause한다.
    """
    with _pipeline_lock():
        pipelines = _load_pipelines()
        pipe = None
        for p in pipelines:
            if p["id"] == pipe_id:
                pipe = p
                break
        if not pipe:
            return None, "파이프라인을 찾을 수 없습니다"
        if pipe["status"] != "active":
            return None, "파이프라인이 꺼져 있습니다"
        # 이중 발사 방지: 이미 job이 실행 중이면 skip
        if pipe.get("job_id"):
            return {"action": "already_running", "job_id": pipe["job_id"]}, None

        # ── Pre-dispatch 스킵 가드 (force=True일 때 건너뜀) ──
        if not force:
            skip, reason = _should_skip_dispatch(pipe)
            if skip:
                # next_run만 재설정하고 실행 안 함
                effective = pipe.get("effective_interval_sec") or pipe.get("interval_sec")
                if effective:
                    pipe["next_run"] = _next_run_str(effective)
                pipe["skip_count"] = pipe.get("skip_count", 0) + 1
                pipe["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                _save_pipelines(pipelines)
                return {"action": "skipped", "reason": reason, "name": pipe["name"]}, None

            # ── 자동 일시정지: 연속 idle 5회 이상 ──
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
                _save_pipelines(pipelines)
                return {
                    "action": "auto_paused",
                    "reason": f"연속 {consecutive_idle}회 무변경 → 자동 일시정지",
                    "name": pipe["name"],
                }, None

        # lock 안에서 dispatching 마커 설정 (다른 프로세스가 동시에 dispatch 못하게)
        pipe["job_id"] = "__dispatching__"
        pipe["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save_pipelines(pipelines)

    # lock 밖에서 실제 전송 (시간이 걸릴 수 있음)
    enriched_prompt = _build_enriched_prompt(pipe)
    result, send_err = send_to_fifo(enriched_prompt, cwd=pipe["project_path"])

    if send_err:
        # 전송 실패: dispatching 마커 제거
        def clear_marker(p):
            p["job_id"] = None
            p["last_error"] = f"FIFO 전송 실패: {send_err}"
        _update_pipeline(pipe_id, clear_marker)
        return None, f"FIFO 전송 실패: {send_err}"

    job_id = result["job_id"]
    effective = pipe.get("effective_interval_sec") or pipe.get("interval_sec")
    nr = _next_run_str(effective) if effective else None

    # git snapshot 저장 (다음 dispatch 시 비교용)
    head_sha = _get_git_head_sha(pipe["project_path"])
    dirty_hash = _get_git_dirty_hash(pipe["project_path"])
    git_snapshot = f"{head_sha}:{dirty_hash}"

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
        # job 없음 → next_run 확인 후 dispatch
        effective = pipe.get("effective_interval_sec") or pipe.get("interval_sec")
        if pipe.get("next_run") and _parse_timestamp(pipe["next_run"]) > time.time():
            remaining = int(_parse_timestamp(pipe["next_run"]) - time.time())
            return {"action": "waiting", "remaining_sec": remaining}, None
        return dispatch(pipe_id)

    # dispatching 마커: 다른 프로세스가 dispatch 중
    if job_id == "__dispatching__":
        return {"action": "dispatching"}, None

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

    # ── 완료: 히스토리 기록 + 적응형 인터벌 + 체이닝 ──
    summary = (result_text or "")[:500]
    classification = _classify_result(result_text or "")

    # 비용/시간 정보 추출
    cost_usd = None
    duration_ms = None
    if resolved:
        full_result, _ = get_job_result(resolved)
        if full_result:
            cost_usd = full_result.get("cost_usd")
            duration_ms = full_result.get("duration_ms")

    # 적응형 인터벌 계산
    new_interval = _adapt_interval(pipe, result_text or "")

    # 체이닝 대상 확인
    chain_target = pipe.get("on_complete")

    def complete(p, _s=summary, _c=classification, _ni=new_interval,
                 _cost=cost_usd, _dur=duration_ms):
        p["last_result"] = _s
        p["run_count"] = p.get("run_count", 0) + 1
        p["job_id"] = None
        p.pop("resolved_job_id", None)

        # 히스토리 추가
        history = p.get("history", [])
        history.append({
            "result": _s,
            "classification": _c,
            "cost_usd": _cost,
            "duration_ms": _dur,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        # 최대 보관 수 초과 시 오래된 것 제거
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
        p["history"] = history

        # 적응형 인터벌 적용
        if _ni is not None:
            p["effective_interval_sec"] = _ni
            p["next_run"] = _next_run_str(_ni)
        elif p.get("interval_sec"):
            p["next_run"] = _next_run_str(p["interval_sec"])

    _update_pipeline(pipe_id, complete)

    # 체이닝: on_complete에 지정된 파이프라인 트리거
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
    if new_interval and pipe.get("interval_sec") and new_interval != pipe.get("interval_sec"):
        base = pipe["interval_sec"]
        response["interval_adapted"] = {
            "base": base,
            "new": new_interval,
            "change": f"{'+' if new_interval > base else ''}{int((new_interval - base) / base * 100)}%",
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
    """상태 초기화 — 적응형 인터벌도 기본값으로 복구."""
    def reset(p):
        p["effective_interval_sec"] = p.get("interval_sec")
    _update_pipeline(pipe_id, reset)
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

    # 히스토리 통계
    history = pipe.get("history", [])
    total_cost = sum(h.get("cost_usd", 0) or 0 for h in history)
    classifications = [h.get("classification", "unknown") for h in history]

    return {
        "id": pipe["id"],
        "name": pipe["name"],
        "project_path": pipe["project_path"],
        "command": pipe["command"],
        "interval": pipe.get("interval"),
        "effective_interval_sec": pipe.get("effective_interval_sec"),
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
        "classifications": classifications[-5:],  # 최근 5개 분류
        "created_at": pipe["created_at"],
        "updated_at": pipe["updated_at"],
    }, None


def get_pipeline_history(pipe_id: str) -> tuple[dict | None, str | None]:
    """파이프라인의 실행 이력을 반환한다."""
    pipe, err = get_pipeline(pipe_id)
    if err:
        return None, err
    history = pipe.get("history", [])
    return {
        "id": pipe["id"],
        "name": pipe["name"],
        "run_count": pipe.get("run_count", 0),
        "total_cost_usd": round(sum(h.get("cost_usd", 0) or 0 for h in history), 4),
        "entries": list(reversed(history)),  # 최신순
    }, None


# ══════════════════════════════════════════════════════════════
#  Self-Evolution: 메타 분석
# ══════════════════════════════════════════════════════════════

def get_evolution_summary() -> dict:
    """전체 파이프라인 시스템의 자기 진화 상태를 요약한다."""
    pipelines = _load_pipelines()
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

    # 효율성 점수: 변경 있는 실행 / 전체 실행
    total_classified = sum(all_classifications.values())
    efficiency = (
        round(all_classifications["has_change"] / total_classified * 100, 1)
        if total_classified > 0 else 0
    )

    # 적응형 인터벌 상태
    interval_adaptations = []
    for p in pipelines:
        base = p.get("interval_sec")
        effective = p.get("effective_interval_sec")
        if base and effective and base != effective:
            interval_adaptations.append({
                "name": p["name"],
                "base_sec": base,
                "effective_sec": effective,
                "change_pct": int((effective - base) / base * 100),
            })

    # 자동 일시정지된 파이프라인
    auto_paused = [
        {"name": p["name"], "reason": p.get("last_error", "")}
        for p in pipelines
        if p["status"] == "stopped" and (p.get("last_error") or "").startswith("자동 일시정지")
    ]

    # 스킵된 실행 횟수 (total_runs 대비 절감률)
    total_skips = sum(p.get("skip_count", 0) for p in pipelines)

    return {
        "active_count": len(active),
        "total_pipelines": len(pipelines),
        "total_runs": total_runs,
        "total_skips": total_skips,
        "total_cost_usd": round(total_cost, 4),
        "classifications": all_classifications,
        "efficiency_pct": efficiency,
        "interval_adaptations": interval_adaptations,
        "auto_paused": auto_paused,
    }


# ══════════════════════════════════════════════════════════════
#  Tick All
# ══════════════════════════════════════════════════════════════

_TICK_ALL_LOCK = DATA_DIR / ".tick_all.lock"
_TICK_ALL_DEBOUNCE_SEC = 3  # 3초 내 중복 호출 무시


def tick_all() -> list[dict]:
    """모든 active 파이프라인을 tick한다.

    debounce: autoloop.sh cron과 프론트엔드 poll이 동시에 호출해도
    3초 내 중복은 무시한다.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = open(_TICK_ALL_LOCK, "a+")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        # 다른 프로세스가 이미 tick_all 실행 중
        return [{"skip": True, "reason": "another tick_all in progress"}]

    try:
        # debounce: 마지막 tick_all 시각 확인
        fd.seek(0)
        last_tick_str = fd.read().strip()
        if last_tick_str:
            try:
                last_tick = float(last_tick_str)
                if time.time() - last_tick < _TICK_ALL_DEBOUNCE_SEC:
                    return [{"skip": True, "reason": "debounced"}]
            except ValueError:
                pass

        # 현재 시각 기록
        fd.seek(0)
        fd.truncate()
        fd.write(str(time.time()))
        fd.flush()

        results = []
        for p in _load_pipelines():
            if p["status"] == "active":
                result, err = tick(p["id"])
                results.append({"pipeline_id": p["id"], "name": p["name"], "result": result, "error": err})
        return results
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
