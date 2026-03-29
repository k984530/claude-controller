"""
Pipeline 컨텍스트 빌드 + Pre-dispatch 스킵 가드 — pipeline.py에서 분리

기능:
  - Git 컨텍스트(최근 커밋, diff stat) 수집
  - 프롬프트에 컨텍스트 주입 (enriched prompt)
  - 연속 무변경 시 프롬프트 개선 힌트 주입
  - Pre-dispatch 스킵 판단 (git 변경 없으면 실행 건너뜀)
"""

import hashlib
import subprocess

from pipeline_classify import count_consecutive_idle, build_refinement_hint


# ── Git 유틸리티 ──────────────────────────────────────────────

def get_git_head_sha(project_path: str) -> str:
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


def get_git_dirty_hash(project_path: str) -> str:
    """uncommitted 변경사항의 해시를 반환한다 (변경 없으면 빈 문자열)."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            cwd=project_path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return hashlib.md5(result.stdout.encode()).hexdigest()[:12]
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def get_git_snapshot(project_path: str) -> str:
    """HEAD SHA + dirty hash를 결합한 git 스냅샷 문자열."""
    return f"{get_git_head_sha(project_path)}:{get_git_dirty_hash(project_path)}"


def get_git_context(project_path: str, max_commits: int = 5) -> str:
    """프로젝트의 최근 git 변경사항을 요약한다."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{max_commits}", "--no-decorate"],
            cwd=project_path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def get_git_diff_stat(project_path: str) -> str:
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


# ── Pre-dispatch 스킵 가드 ──────────────────────────────────

def should_skip_dispatch(pipe: dict) -> tuple[bool, str]:
    """Pre-dispatch 스킵 판단. 반환: (skip 여부, 사유).

    스킵 조건:
    1. git HEAD와 dirty hash가 이전 실행과 동일 (코드 변경 없음)
    2. 이전 결과가 no_change이고 연속 무변경 2회 이상
    """
    project_path = pipe["project_path"]
    current_snapshot = get_git_snapshot(project_path)
    last_snapshot = pipe.get("last_git_snapshot", "")

    if not last_snapshot or current_snapshot != last_snapshot:
        return False, ""  # 코드 변경 있음 → 실행

    history = pipe.get("history", [])
    if not history:
        return False, ""  # 첫 실행

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


# ── 컨텍스트 주입 ──────────────────────────────────────────────

def build_enriched_prompt(pipe: dict) -> str:
    """파이프라인의 원본 command에 컨텍스트를 주입한 프롬프트를 생성한다."""
    command = pipe["command"]
    project_path = pipe["project_path"]
    sections = []

    # 1. Git 컨텍스트
    git_log = get_git_context(project_path)
    git_diff = get_git_diff_stat(project_path)
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
    interval_sec = pipe.get("interval_sec")
    if run_count > 0 and interval_sec:
        interval_str = f"{interval_sec // 60}분" if interval_sec >= 60 else f"{interval_sec}초"
        sections.append(
            f"[실행 통계] {run_count}회 실행됨 | 실행 간격: {interval_str}"
        )

    # 4. 연속 무변경 시 프롬프트 개선 힌트
    idle_count = count_consecutive_idle(pipe)
    hint = build_refinement_hint(idle_count)
    if hint:
        sections.append(hint)

    if not sections:
        return command

    context_block = "\n".join(sections)
    return f"""{command}

{context_block}"""
