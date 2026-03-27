#!/usr/bin/env bash
# ============================================================
# Git Worktree 관리 모듈
# 각 작업을 독립된 git worktree에서 실행하여 격리성을 보장합니다.
# ============================================================

# ── worktree 생성 ──────────────────────────────────────────
# usage: worktree_create <job_id> [repo_path]
# stdout: worktree 경로
worktree_create() {
  local job_id="$1"
  local repo="${2:-$TARGET_REPO}"

  if [[ -z "$repo" ]]; then
    echo "[오류] TARGET_REPO가 설정되지 않았습니다." >&2
    return 1
  fi

  if [[ ! -d "$repo/.git" ]]; then
    echo "[오류] git 저장소가 아닙니다: $repo" >&2
    return 1
  fi

  mkdir -p "$WORKTREES_DIR"

  local branch="controller/job-${job_id}"
  local wt_path="${WORKTREES_DIR}/${branch//\//_}"

  # 기존 브랜치/워크트리 정리
  git -C "$repo" worktree remove "$wt_path" --force 2>/dev/null || true
  git -C "$repo" branch -D "$branch" 2>/dev/null || true

  # base branch에서 새 워크트리 생성
  local base="${BASE_BRANCH:-main}"
  git -C "$repo" fetch origin "$base" 2>/dev/null || true

  if git -C "$repo" worktree add "$wt_path" -b "$branch" "origin/${base}" 2>/dev/null; then
    echo "$wt_path"
    return 0
  fi

  # fallback: 로컬 base branch
  if git -C "$repo" worktree add "$wt_path" -b "$branch" "$base" 2>/dev/null; then
    echo "$wt_path"
    return 0
  fi

  echo "[오류] 워크트리 생성 실패: $wt_path" >&2
  return 1
}

# ── worktree 삭제 ──────────────────────────────────────────
# usage: worktree_remove <job_id> [repo_path]
worktree_remove() {
  local job_id="$1"
  local repo="${2:-$TARGET_REPO}"

  if [[ -z "$repo" ]]; then
    return 1
  fi

  local branch="controller/job-${job_id}"
  local wt_path="${WORKTREES_DIR}/${branch//\//_}"

  if [[ -d "$wt_path" ]]; then
    git -C "$repo" worktree remove "$wt_path" --force 2>/dev/null || true
  fi

  git -C "$repo" branch -D "$branch" 2>/dev/null || true
}

# ── 작업의 worktree 경로 조회 ─────────────────────────────
# usage: worktree_path_for_job <job_id>
worktree_path_for_job() {
  local job_id="$1"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"

  if [[ -f "$meta_file" ]]; then
    local WORKTREE=""
    WORKTREE=$(_get_meta_field "$meta_file" "WORKTREE")
    echo "${WORKTREE:-}"
  fi
}

# ── 전체 worktree 목록 ─────────────────────────────────────
worktree_list() {
  local repo="${1:-$TARGET_REPO}"

  if [[ -z "$repo" || ! -d "$repo/.git" ]]; then
    echo "  (TARGET_REPO 미설정 또는 git 저장소 아님)"
    return
  fi

  git -C "$repo" worktree list 2>/dev/null | while read -r line; do
    echo "  $line"
  done
}

# ── 모든 controller worktree 정리 ──────────────────────────
worktree_clean_all() {
  local repo="${1:-$TARGET_REPO}"

  if [[ -z "$repo" ]]; then
    echo "  [오류] TARGET_REPO 미설정"
    return 1
  fi

  local count=0
  for meta_file in "${LOGS_DIR}"/job_*.meta; do
    [[ -f "$meta_file" ]] || continue
    local JOB_ID="" WORKTREE=""
    JOB_ID=$(_get_meta_field "$meta_file" "JOB_ID")
    WORKTREE=$(_get_meta_field "$meta_file" "WORKTREE")
    if [[ -n "$WORKTREE" && -d "$WORKTREE" ]]; then
      worktree_remove "$JOB_ID" "$repo"
      (( count++ )) || true
    fi
  done

  git -C "$repo" worktree prune 2>/dev/null || true
  echo "  ${count}개 워크트리 정리 완료."
}
