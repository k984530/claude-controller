#!/usr/bin/env bash
# ============================================================
# 세션 관리 모듈
# claude -p 의 세션 ID 를 추적하여 대화를 이어갈 수 있게 합니다.
# ============================================================

# 현재 활성 세션 ID (가장 최근 포그라운드 실행의 세션)
_CURRENT_SESSION_ID=""

# ── 세션 저장 ──────────────────────────────────────────────
session_save() {
  local session_id="$1"
  local prompt="$2"
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')

  if [[ -n "$session_id" ]]; then
    _CURRENT_SESSION_ID="$session_id"
    echo "${ts}|${session_id}|${prompt:0:200}" >> "${SESSIONS_DIR}/history.log"
  fi
}

# ── 현재 세션 ID 반환 ─────────────────────────────────────
session_current() {
  echo "$_CURRENT_SESSION_ID"
}

# ── 세션 목록 보기 ─────────────────────────────────────────
session_list() {
  local history_file="${SESSIONS_DIR}/history.log"
  if [[ ! -f "$history_file" ]]; then
    echo "  (세션 기록 없음)"
    return
  fi

  printf "  %-19s  %-40s  %s\n" "TIME" "SESSION_ID" "PROMPT"
  printf "  %-19s  %-40s  %s\n" "-------------------" "----------------------------------------" "--------------------"

  tail -20 "$history_file" | while IFS='|' read -r ts sid prompt; do
    local short_prompt="${prompt:0:40}"
    [[ ${#prompt} -gt 40 ]] && short_prompt="${short_prompt}..."
    printf "  %-19s  %-40s  %s\n" "$ts" "$sid" "$short_prompt"
  done
}

# ── 특정 세션으로 전환 ─────────────────────────────────────
session_switch() {
  local session_id="$1"
  if [[ -n "$session_id" ]]; then
    _CURRENT_SESSION_ID="$session_id"
    echo "  세션 전환됨: $session_id"
  else
    echo "  [오류] 세션 ID를 지정해주세요."
  fi
}

# ── claude -p 에 세션 관련 플래그 생성 ─────────────────────
# --continue: 가장 최근 대화 이어가기
# --resume <id>: 특정 세션 이어가기
session_build_flags() {
  local mode="$1"  # "continue" | "resume" | ""
  local flags=()

  case "$mode" in
    continue)
      flags+=(--continue)
      ;;
    resume)
      if [[ -n "$_CURRENT_SESSION_ID" ]]; then
        flags+=(--resume "$_CURRENT_SESSION_ID")
      else
        echo "  [경고] 이어갈 세션이 없습니다. 새 세션으로 실행합니다." >&2
      fi
      ;;
  esac

  echo "${flags[@]+"${flags[@]}"}"
}
