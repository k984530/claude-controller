#!/usr/bin/env bash
# ============================================================
# 백그라운드 작업(Job) 관리 모듈
# Session ID 기반으로 작업의 상태, 결과를 추적합니다.
# PID는 내부 프로세스 관리 전용으로만 사용합니다.
# ============================================================

# ── 안전한 .meta 파일 파서 ─────────────────────────────────
# source 대신 grep+sed로 필드를 추출하여 쉘 인젝션을 방지한다.
_get_meta_field() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 1
  grep "^${key}=" "$file" 2>/dev/null | head -1 | sed "s/^${key}=//" | sed "s/^['\"]//;s/['\"]$//"
}

# .meta 파일의 모든 필드를 로컬 변수로 로드 (source 대체)
# usage: _load_meta "$meta_file"  →  JOB_ID, STATUS, PID, PROMPT, ... 변수 설정
_load_meta() {
  local file="$1"
  JOB_ID=$(_get_meta_field "$file" "JOB_ID")
  STATUS=$(_get_meta_field "$file" "STATUS")
  PID=$(_get_meta_field "$file" "PID")
  PROMPT=$(_get_meta_field "$file" "PROMPT")
  CREATED_AT=$(_get_meta_field "$file" "CREATED_AT")
  SESSION_ID=$(_get_meta_field "$file" "SESSION_ID")
  UUID=$(_get_meta_field "$file" "UUID")
  CWD=$(_get_meta_field "$file" "CWD")
  WORKTREE=$(_get_meta_field "$file" "WORKTREE")
  REPO=$(_get_meta_field "$file" "REPO")
}

# 디스크 기반 Job 카운터 (서브쉘에서도 안전하게 동작)
_JOB_COUNTER_FILE="${LOGS_DIR}/.job_counter"

# 카운터를 원자적으로 증가시키고 새 값을 stdout에 출력
_next_job_id() {
  local lockfile="${_JOB_COUNTER_FILE}.lock"
  local waited=0
  # 스핀락 + stale lock 감지: 500회(≈5초) 대기 후 강제 해제
  while ! mkdir "$lockfile" 2>/dev/null; do
    sleep 0.01
    (( waited++ )) || true
    if [[ $waited -gt 500 ]]; then
      rmdir "$lockfile" 2>/dev/null || rm -rf "$lockfile" 2>/dev/null || true
      waited=0
    fi
  done
  local current=0
  [[ -f "$_JOB_COUNTER_FILE" ]] && current=$(cat "$_JOB_COUNTER_FILE")
  local next=$(( current + 1 ))
  echo "$next" > "$_JOB_COUNTER_FILE"
  rmdir "$lockfile" 2>/dev/null || true
  echo "$next"
}

# ── Job 생성 등록 ──────────────────────────────────────────
# usage: job_register <prompt_text>
# stdout: job_id
job_register() {
  local prompt="$1"
  local job_id
  job_id=$(_next_job_id)
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')

  local meta_file="${LOGS_DIR}/job_${job_id}.meta"
  # 프롬프트 내의 특수문자를 이스케이프하여 안전하게 저장
  local safe_prompt
  safe_prompt=$(printf '%s' "$prompt" | head -c 500 | tr -d '\000-\037\177' | sed "s/'/'\\\\''/g")
  cat > "$meta_file" <<EOF
JOB_ID=${job_id}
STATUS=running
PID=
PROMPT='${safe_prompt}'
CREATED_AT='${ts}'
SESSION_ID=
EOF
  echo "$job_id"
}

# ── 원자적 meta 필드 갱신 (temp → rename) ─────────────────
_meta_set_field() {
  local meta_file="$1" key="$2" value="$3"
  [[ -f "$meta_file" ]] || return 1
  local tmp_file="${meta_file}.tmp.$$"
  sed "s/^${key}=.*/${key}=${value}/" "$meta_file" > "$tmp_file" && \
    mv -f "$tmp_file" "$meta_file"
}

# ── PID / 세션 ID 갱신 ────────────────────────────────────
job_set_pid() {
  local job_id="$1" pid="$2"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"
  _meta_set_field "$meta_file" "PID" "$pid"
}

job_set_session() {
  local job_id="$1" session_id="$2"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"
  _meta_set_field "$meta_file" "SESSION_ID" "$session_id"
}

# ── 상태 변경 ──────────────────────────────────────────────
job_mark_done() {
  local job_id="$1"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"
  _meta_set_field "$meta_file" "STATUS" "done"
  _fire_webhook "$job_id" "done"
}

job_mark_failed() {
  local job_id="$1"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"
  _meta_set_field "$meta_file" "STATUS" "failed"
  _fire_webhook "$job_id" "failed"
}

# ── 웹훅 전달 (백그라운드) ─────────────────────────────────
_fire_webhook() {
  local job_id="$1" status="$2"
  local webhook_script="${CONTROLLER_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}/web/webhook.py"
  [[ -f "$webhook_script" ]] || return 0
  # 백그라운드에서 실행 — 작업 완료 흐름을 차단하지 않는다
  python3 "$webhook_script" "$job_id" "$status" &>/dev/null &
}

# ── 상태 조회 ──────────────────────────────────────────────
job_status() {
  local job_id="$1"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"
  if [[ -f "$meta_file" ]]; then
    local STATUS="" PID=""
    STATUS=$(_get_meta_field "$meta_file" "STATUS")
    PID=$(_get_meta_field "$meta_file" "PID")
    # PID가 아직 살아있는지 확인 (내부 전용)
    if [[ "$STATUS" == "running" && -n "$PID" ]]; then
      if ! kill -0 "$PID" 2>/dev/null; then
        job_mark_done "$job_id"
        STATUS="done"
      fi
    fi
    echo "$STATUS"
  else
    echo "not_found"
  fi
}

# ── Session ID로 Job 찾기 ────────────────────────────────
# session_id로 가장 최신 job_id를 반환한다.
job_find_by_session() {
  local target_sid="$1"
  local best_jid=0 found_jid=""
  for meta_file in "${LOGS_DIR}"/job_*.meta; do
    [[ -f "$meta_file" ]] || continue
    local sid
    sid=$(_get_meta_field "$meta_file" "SESSION_ID")
    if [[ "$sid" == "$target_sid" ]]; then
      local jid
      jid=$(_get_meta_field "$meta_file" "JOB_ID")
      if [[ "$jid" -gt "$best_jid" ]] 2>/dev/null; then
        best_jid="$jid"
        found_jid="$jid"
      fi
    fi
  done
  if [[ -n "$found_jid" ]]; then
    echo "$found_jid"
    return 0
  fi
  return 1
}

# ── 실행 중인 Job의 Session ID 조기 추출 ────────────────
# stream-json 출력 파일에서 session_id를 탐색하여 meta에 캐싱한다.
job_get_session_id() {
  local job_id="$1"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"

  # meta 파일에서 먼저 확인
  local sid
  sid=$(_get_meta_field "$meta_file" "SESSION_ID")
  if [[ -n "$sid" ]]; then
    echo "$sid"
    return 0
  fi

  # stream 출력에서 조기 추출 시도
  local out_file="${LOGS_DIR}/job_${job_id}.out"
  if [[ -f "$out_file" ]]; then
    sid=$(grep -m1 '"session_id"' "$out_file" 2>/dev/null | head -1 | jq -r '.session_id // empty' 2>/dev/null)
    if [[ -n "$sid" ]]; then
      job_set_session "$job_id" "$sid"
      echo "$sid"
      return 0
    fi
  fi
  return 1
}

# ── 전체 작업 목록 ─────────────────────────────────────────
jobs_list() {
  local meta_files=("${LOGS_DIR}"/job_*.meta)
  if [[ ! -f "${meta_files[0]}" ]]; then
    echo "  (백그라운드 작업 없음)"
    return
  fi

  printf "  %-4s  %-9s  %-10s  %-19s  %s\n" "ID" "STATUS" "SESSION" "CREATED" "PROMPT"
  printf "  %-4s  %-9s  %-10s  %-19s  %s\n" "----" "---------" "----------" "-------------------" "--------------------"

  # 최근 작업이 위로 오도록 JOB_ID 내림차순 정렬
  local sorted_files
  IFS=$'\n' sorted_files=($(
    for f in "${meta_files[@]}"; do
      [[ -f "$f" ]] || continue
      local num="${f##*job_}"
      num="${num%.meta}"
      echo "${num} ${f}"
    done | sort -t' ' -k1 -rn | cut -d' ' -f2-
  ))
  unset IFS

  for meta_file in "${sorted_files[@]}"; do
    [[ -f "$meta_file" ]] || continue
    (
      local JOB_ID="" STATUS="" PID="" PROMPT="" CREATED_AT="" SESSION_ID=""
      _load_meta "$meta_file"
      # 프로세스 생존 확인 (내부 전용)
      if [[ "$STATUS" == "running" && -n "$PID" ]]; then
        if ! kill -0 "$PID" 2>/dev/null; then
          STATUS="done"
        fi
      fi
      # Session ID가 없으면 stream에서 조기 추출 시도
      if [[ -z "$SESSION_ID" ]]; then
        SESSION_ID=$(job_get_session_id "$JOB_ID" 2>/dev/null) || true
      fi
      local short_sid="${SESSION_ID:0:8}"
      [[ ${#SESSION_ID} -gt 8 ]] && short_sid="${short_sid}.."
      local short_prompt="${PROMPT:0:40}"
      [[ ${#PROMPT} -gt 40 ]] && short_prompt="${short_prompt}..."
      printf "  %-4s  %-9s  %-10s  %-19s  %s\n" \
        "$JOB_ID" "$STATUS" "${short_sid:-"-"}" "$CREATED_AT" "$short_prompt"
    )
  done
}

# ── 작업 결과 보기 ─────────────────────────────────────────
job_result() {
  local job_id="$1"
  local out_file="${LOGS_DIR}/job_${job_id}.out"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"

  if [[ ! -f "$meta_file" ]]; then
    echo "  [오류] Job #${job_id}를 찾을 수 없습니다."
    return 1
  fi

  local status
  status=$(job_status "$job_id")

  if [[ "$status" == "running" ]]; then
    echo "  [진행 중] Job #${job_id}가 아직 실행 중입니다..."
    return 0
  fi

  if [[ -f "$out_file" ]]; then
    # JSON 출력에서 result 텍스트만 추출 시도
    local result_text
    result_text=$(jq -r '.result // empty' "$out_file" 2>/dev/null)
    if [[ -n "$result_text" ]]; then
      echo "$result_text"
    else
      cat "$out_file"
    fi
  else
    echo "  [오류] Job #${job_id}의 출력 파일이 없습니다."
    return 1
  fi
}

# ── 작업의 세션 ID 가져오기 ────────────────────────────────
job_session_id() {
  local job_id="$1"
  local out_file="${LOGS_DIR}/job_${job_id}.out"
  if [[ -f "$out_file" ]]; then
    jq -r '.session_id // empty' "$out_file" 2>/dev/null
  fi
}

# ── 작업 강제 종료 ─────────────────────────────────────────
# job_id 또는 session_id로 호출 가능.
# session_id(UUID 형태)가 입력되면 자동으로 job_id로 변환한다.
job_kill() {
  local identifier="$1"
  local job_id="$identifier"

  # UUID 형태(하이픈 포함 36자)이면 session_id로 간주
  if [[ "$identifier" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    job_id=$(job_find_by_session "$identifier")
    if [[ -z "$job_id" ]]; then
      echo "  [오류] Session ID '${identifier:0:8}...'에 해당하는 작업을 찾을 수 없습니다."
      return 1
    fi
  fi

  local meta_file="${LOGS_DIR}/job_${job_id}.meta"

  if [[ ! -f "$meta_file" ]]; then
    echo "  [오류] Job #${job_id}를 찾을 수 없습니다."
    return 1
  fi

  local STATUS="" PID="" SESSION_ID=""
  _load_meta "$meta_file"
  local sid_label="${SESSION_ID:+${SESSION_ID:0:8}..}"

  if [[ "$STATUS" != "running" ]]; then
    echo "  Job #${job_id}${sid_label:+ (session: $sid_label)}는 이미 종료되었습니다. (status: $STATUS)"
    return 0
  fi

  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null
    sleep 0.5
    kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null
    job_mark_failed "$job_id"
    echo "  Job #${job_id}${sid_label:+ (session: $sid_label)} 종료됨."
  else
    job_mark_done "$job_id"
    echo "  Job #${job_id}${sid_label:+ (session: $sid_label)}는 이미 종료된 프로세스입니다."
  fi
}

# ── 로그 파일 정리 ─────────────────────────────────────────
jobs_clean() {
  local count=0
  for f in "${LOGS_DIR}"/job_*.meta "${LOGS_DIR}"/job_*.out "${LOGS_DIR}"/job_*.ext_id; do
    if [[ -f "$f" ]]; then rm -f "$f"; (( count++ )) || true; fi
  done
  # 카운터 초기화
  echo "0" > "$_JOB_COUNTER_FILE"
  echo "  ${count}개의 작업 파일 정리 완료."
}
