#!/usr/bin/env bash
# ============================================================
# dispatch-helpers.sh — dispatch_job 에서 추출된 헬퍼 함수
# ============================================================

# ── 이미지 파일을 @path 형태로 프롬프트에 추가 ──
# 사용법: prompt=$(_build_image_refs "$images_json" "$prompt")
_build_image_refs() {
  local images_json="$1" prompt="$2"
  if [[ -z "$images_json" || "$images_json" == "null" ]]; then
    echo "$prompt"; return
  fi
  local img_count
  img_count=$(echo "$images_json" | jq -r 'length' 2>/dev/null)
  if ! [[ "$img_count" -gt 0 ]] 2>/dev/null; then
    echo "$prompt"; return
  fi
  local img_refs="" i=0
  while [[ $i -lt $img_count ]]; do
    local img_path
    img_path=$(echo "$images_json" | jq -r ".[$i]" 2>/dev/null)
    if [[ -n "$img_path" && -f "$img_path" ]]; then
      img_refs="${img_refs} @${img_path}"
      _log_info "Job 이미지 첨부: ${img_path}"
    else
      _log_warn "이미지 파일 없음 (건너뜀): ${img_path}"
    fi
    (( i++ )) || true
  done
  [[ -n "$img_refs" ]] && prompt="${prompt}${img_refs}"
  echo "$prompt"
}

# ── Goals 컨텍스트 수집 ──
# 사용법: goals_ctx=$(_collect_goals_context "$effective_cwd")
_collect_goals_context() {
  local effective_cwd="$1"
  local _goals_dir="${CONTROLLER_DIR}/data/goals"
  mkdir -p "$_goals_dir" 2>/dev/null
  local ctx=""
  for _gf in "$_goals_dir"/*.md; do
    [[ -f "$_gf" ]] || continue
    if head -10 "$_gf" | grep -q 'status: active'; then
      local _gproject
      _gproject=$(head -10 "$_gf" | grep '^project:' | sed 's/^project: *//')
      if [[ -z "$_gproject" || "$_gproject" == "$effective_cwd" ]]; then
        local _gtitle _gtasks _gdone _gfile
        _gtitle=$(head -10 "$_gf" | grep '^title:' | sed 's/^title: *//')
        _gtasks=$(grep -cE '^\s*- \[[ xX]\]' "$_gf" 2>/dev/null || echo 0)
        _gdone=$(grep -cE '^\s*- \[[xX]\]' "$_gf" 2>/dev/null || echo 0)
        _gfile=$(basename "$_gf")
        ctx="${ctx}
- ${_gtitle} (${_gdone}/${_gtasks}) → ${_goals_dir}/${_gfile}"
      fi
    fi
  done
  echo "$ctx"
}

# ── Fork 세션 컨텍스트 주입 ──
# 사용법: prompt=$(_build_fork_prompt "$fork_sid" "$prompt")
_build_fork_prompt() {
  local fork_sid="$1" prompt="$2"
  local prev_result="" prev_prompt_text="" best_jid=0
  for mf in "${LOGS_DIR}"/job_*.meta; do
    [[ -f "$mf" ]] || continue
    local sid
    sid=$(_get_meta_field "$mf" "SESSION_ID")
    if [[ "$sid" == "$fork_sid" ]]; then
      local jid
      jid=$(_get_meta_field "$mf" "JOB_ID")
      if [[ "$jid" -gt "$best_jid" ]] 2>/dev/null; then
        best_jid="$jid"
        prev_prompt_text=$(_get_meta_field "$mf" "PROMPT")
        local of="${LOGS_DIR}/job_${jid}.out"
        if [[ -f "$of" ]]; then
          prev_result=$(grep '"type":"result"' "$of" | tail -1 | jq -r '.result // empty' 2>/dev/null)
        fi
      fi
    fi
  done
  if [[ -n "$prev_result" ]]; then
    local max_ctx=8000
    if [[ ${#prev_result} -gt $max_ctx ]]; then
      prev_result="${prev_result:0:$max_ctx}
... (이전 응답 ${#prev_result}자 중 ${max_ctx}자까지 포함)"
    fi
    prompt="[이전 대화에서 분기 (Fork from session: ${fork_sid:0:8}...)]
--- 이전 프롬프트 ---
${prev_prompt_text}
--- 이전 응답 ---
${prev_result}
--- 새로운 지시 (이전 컨텍스트를 참고하여 수행) ---
${prompt}"
    _log_info "Job 세션 모드: fork (sid=${fork_sid}, job_id=${best_jid}, context=${#prev_result} chars)"
  else
    _log_warn "Job 세션 모드: fork — 이전 세션 결과 없음, 새 세션으로 실행 (sid=${fork_sid})"
  fi
  echo "$prompt"
}
