#!/usr/bin/env bash
# ============================================================
# Checkpoint 관리 모듈
# Worktree에서 실행 중인 job의 파일 변경을 자동 커밋(checkpoint)하고
# 특정 체크포인트로 되돌리는(rewind) 기능을 제공합니다.
#
# 의존: jobs.sh (_get_meta_field), config.sh (LOGS_DIR)
# ============================================================

# ── 설정 ────────────────────────────────────────────────────
CHECKPOINT_INTERVAL="${CHECKPOINT_INTERVAL:-5}"
CHECKPOINT_PREFIX="ckpt"

# ── 체크포인트 워처 루프 ────────────────────────────────────
# 백그라운드에서 worktree를 감시하며 파일 변경이 안정화되면 자동 커밋.
# 호출 시 반드시 & (백그라운드)로 실행할 것.
#
# Usage: checkpoint_watcher_loop <worktree_path> <job_id> <meta_file> &
checkpoint_watcher_loop() {
  local wt_path="$1"
  local job_id="$2"
  local meta_file="$3"
  local turn=0
  local prev_hash=""

  cd "$wt_path" 2>/dev/null || return 1

  # worktree 로컬 git 설정 (커밋용)
  git config user.email "checkpoint@controller.local" 2>/dev/null
  git config user.name "Controller Checkpoint" 2>/dev/null

  # 초기 상태에 untracked 파일이 있으면 커밋
  git add -A 2>/dev/null
  if ! git diff --cached --quiet 2>/dev/null; then
    git commit -m "${CHECKPOINT_PREFIX}:${job_id}:0:init" --no-verify 2>/dev/null || true
  fi

  while true; do
    sleep "$CHECKPOINT_INTERVAL"

    # job 상태 확인 — running이 아니면 최종 커밋 후 종료
    local status=""
    [[ -f "$meta_file" ]] && status=$(grep '^STATUS=' "$meta_file" 2>/dev/null | tail -1 | sed 's/^STATUS=//')
    if [[ "$status" != "running" ]]; then
      _ckpt_commit_if_dirty "$wt_path" "$job_id" "$turn" "final"
      break
    fi

    # 현재 변경사항 해시 (diff + untracked files)
    local curr_hash
    curr_hash=$( { git diff 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | md5 2>/dev/null || echo "none" )

    # 빈 해시 = 변경 없음
    local empty_hash
    empty_hash=$(echo -n | md5 2>/dev/null || echo "none")
    if [[ "$curr_hash" == "$empty_hash" ]]; then
      prev_hash=""
      continue
    fi

    # 안정화 대기: 이전 체크와 해시가 다르면 아직 변경 진행 중
    if [[ "$curr_hash" != "$prev_hash" ]]; then
      prev_hash="$curr_hash"
      continue
    fi

    # 2회 연속 동일 해시 = 변경 완료, 커밋 수행
    (( turn++ )) || true
    _ckpt_commit_if_dirty "$wt_path" "$job_id" "$turn" ""
    prev_hash=""
  done
}

# ── 내부: 변경이 있으면 커밋 ────────────────────────────────
_ckpt_commit_if_dirty() {
  local wt_path="$1" job_id="$2" turn="$3" suffix="$4"

  cd "$wt_path" 2>/dev/null || return 1

  git add -A 2>/dev/null

  if ! git diff --cached --quiet 2>/dev/null; then
    local msg="${CHECKPOINT_PREFIX}:${job_id}:${turn}"
    [[ -n "$suffix" ]] && msg="${msg}:${suffix}"

    # 변경 파일 목록 (최대 5개)
    local changed
    changed=$(git diff --cached --name-only 2>/dev/null | head -5 | tr '\n' ', ')
    [[ -n "$changed" ]] && msg="${msg} [${changed%,}]"

    git commit -m "$msg" --no-verify 2>/dev/null || true
  fi
}

# ── 체크포인트 목록 조회 ────────────────────────────────────
# worktree의 git log에서 이 job의 checkpoint 커밋들을 JSON 배열로 반환.
#
# Usage: checkpoint_list <worktree_path> <job_id>
# Output: JSON array
checkpoint_list() {
  local wt_path="$1"
  local job_id="$2"

  # worktree 유효성 확인
  if [[ ! -d "$wt_path" ]] || ! (cd "$wt_path" && git rev-parse --git-dir >/dev/null 2>&1); then
    echo "[]"
    return
  fi

  cd "$wt_path" 2>/dev/null || { echo "[]"; return; }

  local result="["
  local first=true

  while IFS='|' read -r hash ts msg; do
    [[ -z "$hash" ]] && continue

    # 턴 번호 추출
    local turn_num
    turn_num=$(echo "$msg" | sed -n "s/.*${CHECKPOINT_PREFIX}:${job_id}:\([0-9]*\).*/\1/p")
    [[ -z "$turn_num" ]] && turn_num=0

    # 변경 파일 수
    local file_count
    file_count=$(git diff-tree --no-commit-id --name-only -r "$hash" 2>/dev/null | wc -l | tr -d ' ')

    # 변경 파일 목록
    local file_list
    file_list=$(git diff-tree --no-commit-id --name-only -r "$hash" 2>/dev/null | head -10 | jq -R . 2>/dev/null | jq -s . 2>/dev/null)
    [[ -z "$file_list" ]] && file_list="[]"

    [[ "$first" == "true" ]] && first=false || result="${result},"
    result="${result}{\"hash\":\"${hash}\",\"turn\":${turn_num},\"timestamp\":\"${ts}\",\"message\":$(echo "$msg" | jq -R .),\"files_changed\":${file_count},\"files\":${file_list}}"
  done < <(git log --format='%H|%aI|%s' --grep="${CHECKPOINT_PREFIX}:${job_id}:" 2>/dev/null)

  result="${result}]"
  echo "$result"
}

# ── 대화 컨텍스트 추출 ──────────────────────────────────────
# stream-json .out 파일에서 assistant 텍스트 + tool_use 요약을 추출.
# 최대 max_chars 글자까지만 반환하여 프롬프트 크기를 제한.
#
# Usage: checkpoint_extract_context <out_file> [max_chars]
# Output: plain text
checkpoint_extract_context() {
  local out_file="$1"
  local max_chars="${2:-4000}"

  [[ -f "$out_file" ]] || return 0

  # jq로 한 번에 추출 (성능 + 안정성)
  jq -r '
    if .type == "assistant" then
      [.message.content[]? |
        if .type == "text" then "[\(.type)] \(.text[0:300])"
        elif .type == "tool_use" then "[tool: \(.name)] \(.input | tostring[0:150])"
        else empty end
      ] | join("\n")
    elif .type == "result" then
      "[result] \(.result[0:300] // "")"
    else empty end
  ' "$out_file" 2>/dev/null | head -c "$max_chars"
}

# ── Rewind 실행 ──────────────────────────────────────────────
# 1. 실행 중인 job 종료
# 2. worktree를 지정된 checkpoint로 git reset --hard
# 3. 대화 컨텍스트 추출
# 4. 새 프롬프트 생성 (FIFO 전송은 호출자가 담당)
#
# Usage: checkpoint_rewind <job_id> <checkpoint_hash> <new_prompt>
# Output: 생성된 full_prompt (stdout), 실패 시 exit 1
checkpoint_rewind() {
  local job_id="$1"
  local ckpt_hash="$2"
  local new_prompt="$3"

  local meta_file="${LOGS_DIR}/job_${job_id}.meta"
  local out_file="${LOGS_DIR}/job_${job_id}.out"

  # meta 파일 확인
  if [[ ! -f "$meta_file" ]]; then
    echo "[오류] Job #${job_id}를 찾을 수 없습니다." >&2
    return 1
  fi

  # 실행 중이면 종료
  local status
  status=$(_get_meta_field "$meta_file" "STATUS")
  if [[ "$status" == "running" ]]; then
    job_kill "$job_id" >/dev/null 2>&1
    sleep 1
  fi

  # worktree 경로 확인
  local wt_path
  wt_path=$(_get_meta_field "$meta_file" "WORKTREE")
  if [[ -z "$wt_path" || ! -d "$wt_path" ]]; then
    echo "[오류] 워크트리를 찾을 수 없습니다." >&2
    return 1
  fi

  # checkpoint 커밋 유효성 확인
  if ! (cd "$wt_path" && git cat-file -t "$ckpt_hash" >/dev/null 2>&1); then
    echo "[오류] 유효하지 않은 체크포인트: $ckpt_hash" >&2
    return 1
  fi

  # 체크포인트로 reset
  (cd "$wt_path" && git reset --hard "$ckpt_hash" 2>/dev/null) || {
    echo "[오류] git reset 실패" >&2
    return 1
  }

  # 대화 컨텍스트 추출
  local context=""
  if [[ -f "$out_file" ]]; then
    context=$(checkpoint_extract_context "$out_file" 4000)
  fi

  # 새 프롬프트 구성
  if [[ -n "$context" ]]; then
    cat <<REWIND_PROMPT
[이전 작업 컨텍스트 — 아래는 이전 세션에서 수행된 작업 요약입니다]
${context}

[Rewind 지시사항]
파일 상태가 위 작업 중간의 체크포인트 시점으로 복원되었습니다.
이전 작업 내용을 참고하되, 이어서 다음을 수행하세요:

${new_prompt}
REWIND_PROMPT
  else
    echo "$new_prompt"
  fi
}
