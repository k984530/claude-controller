#!/usr/bin/env bash
# ============================================================
# Controller Service Daemon
# FIFO 파이프에서 JSON 메시지를 수신하여 claude -p 를 디스패치하는
# 상주(persistent) 서비스 데몬입니다.
# ============================================================
set -uo pipefail

# ── 의존성 로드 ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../config.sh"
source "${SCRIPT_DIR}/../lib/jobs.sh"
source "${SCRIPT_DIR}/../lib/session.sh"
source "${SCRIPT_DIR}/../lib/executor.sh"
source "${SCRIPT_DIR}/../lib/worktree.sh"
source "${SCRIPT_DIR}/../lib/checkpoint.sh"

# ── 서비스 로그 ──────────────────────────────────────────────
SERVICE_LOG="${LOGS_DIR}/service.log"

_log() {
  local level="$1"
  shift
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[${ts}] [${level}] $*" >> "$SERVICE_LOG"
}

_log_info()  { _log "INFO"  "$@"; }
_log_warn()  { _log "WARN"  "$@"; }
_log_error() { _log "ERROR" "$@"; }

# ── 배너 출력 ────────────────────────────────────────────────
_print_banner() {
  cat <<EOF
============================================================
  Controller Service Daemon
============================================================
  FIFO      : ${FIFO_PATH}
  로그      : ${SERVICE_LOG}
  최대 작업 : ${MAX_BACKGROUND_JOBS}
  관리 기준 : Session ID
------------------------------------------------------------
  [대기 중] FIFO 파이프에서 메시지를 수신합니다...
============================================================
EOF
}

# ── 정리 (cleanup) ───────────────────────────────────────────
cleanup() {
  _log_info "서비스 종료 시작 (PID: $$)"

  # FIFO 제거
  if [[ -p "$FIFO_PATH" ]]; then
    rm -f "$FIFO_PATH"
    _log_info "FIFO 파이프 제거됨: ${FIFO_PATH}"
  fi

  # PID 파일 제거
  if [[ -f "$PID_FILE" ]]; then
    rm -f "$PID_FILE"
    _log_info "PID 파일 제거됨: ${PID_FILE}"
  fi

  # 실행 중인 백그라운드 작업 대기 (최대 5초)
  local remaining
  remaining=$(jobs -rp 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$remaining" -gt 0 ]]; then
    _log_info "백그라운드 작업 ${remaining}개 종료 대기 중..."
    wait 2>/dev/null || true
  fi

  _log_info "서비스 정상 종료됨"
  echo ""
  echo "  [종료] 서비스가 정상적으로 종료되었습니다."
}

# ── 시그널 핸들러 ────────────────────────────────────────────
_on_signal() {
  _log_warn "시그널 수신 — 서비스를 종료합니다."
  echo ""
  echo "  [시그널] 종료 시그널 수신. 정리 중..."
  cleanup
  exit 0
}

trap _on_signal SIGTERM SIGINT SIGHUP

# ── meta 파일 인젝션 방지 ─────────────────────────────────────
# 개행·제어문자를 제거하여 KEY=VALUE 라인 인젝션을 방지한다.
# Python 측 _sanitize_meta_value()와 동일한 역할.
_sanitize_meta_val() {
  printf '%s' "$1" | tr -d '\000-\037\177'
}

# ── 중복 디스패치 방지 ────────────────────────────────────────
# 최근 디스패치된 프롬프트 해시와 타임스탬프를 기록
_LAST_DISPATCH_HASH=""
_LAST_DISPATCH_TIME=0
_DEDUP_WINDOW_SEC=3  # 동일 프롬프트를 무시하는 시간 창(초)

_prompt_hash() {
  printf '%s' "$1" | md5 2>/dev/null || printf '%s' "$1" | md5sum 2>/dev/null | cut -d' ' -f1
}

# ── dispatch_job: JSON 메시지 파싱 후 claude -p 실행 ────────
dispatch_job() {
  local json_line="$1"

  # JSON 유효성 검사
  if ! echo "$json_line" | jq empty 2>/dev/null; then
    _log_error "유효하지 않은 JSON: ${json_line:0:200}"
    return 1
  fi

  # 필드 추출 (callback은 보안상 제거됨 — eval 인젝션 방지)
  local job_uuid prompt cwd use_worktree repo session_raw images_json reuse_wt
  job_uuid=$(echo "$json_line" | jq -r '.id // empty')
  prompt=$(echo "$json_line" | jq -r '.prompt // empty')
  cwd=$(echo "$json_line" | jq -r '.cwd // empty')
  use_worktree=$(echo "$json_line" | jq -r '.worktree // empty')
  repo=$(echo "$json_line" | jq -r '.repo // empty')
  session_raw=$(echo "$json_line" | jq -r '.session // empty')
  images_json=$(echo "$json_line" | jq -c '.images // empty')
  reuse_wt=$(echo "$json_line" | jq -r '.reuse_worktree // empty')

  if [[ -z "$prompt" ]]; then
    _log_error "프롬프트가 비어있습니다: ${json_line:0:200}"
    return 1
  fi

  # 고유 ID가 없으면 생성
  if [[ -z "$job_uuid" ]]; then
    job_uuid=$(date '+%s')-$$-$RANDOM
  fi

  # ── 중복 프롬프트 감지 (짧은 시간 내 동일 프롬프트 무시) ──
  local now
  now=$(date '+%s')
  local phash
  phash=$(_prompt_hash "$prompt")
  local elapsed=$(( now - _LAST_DISPATCH_TIME ))

  if [[ "$phash" == "$_LAST_DISPATCH_HASH" && $elapsed -lt $_DEDUP_WINDOW_SEC ]]; then
    _log_warn "중복 프롬프트 무시 (${elapsed}초 이내 동일 요청): id=${job_uuid}"
    echo "  [무시] 중복 요청이 감지되어 건너뜁니다: ${job_uuid}"
    return 0
  fi

  _LAST_DISPATCH_HASH="$phash"
  _LAST_DISPATCH_TIME="$now"

  _log_info "작업 수신: id=${job_uuid} prompt='${prompt:0:80}...'"

  # 동시 작업 수 제한 확인
  local running_count=0
  for meta_file in "${LOGS_DIR}"/job_*.meta; do
    [[ -f "$meta_file" ]] || continue
    local STATUS=""
    STATUS=$(_get_meta_field "$meta_file" "STATUS")
    if [[ "$STATUS" == "running" ]]; then
      (( running_count++ )) || true
    fi
  done

  if [[ $running_count -ge $MAX_BACKGROUND_JOBS ]]; then
    _log_warn "최대 동시 작업 수(${MAX_BACKGROUND_JOBS}) 도달 — 작업 거부: ${job_uuid}"
    return 1
  fi

  # ── pending 작업 재사용 (DAG 의존성 디스패치) ──
  local pending_jid
  pending_jid=$(echo "$json_line" | jq -r '.pending_job_id // empty')

  local job_id meta_file out_file
  # 사용자 입력값 새니타이즈 (meta 파일 인젝션 방지)
  job_uuid=$(_sanitize_meta_val "$job_uuid")
  cwd=$(_sanitize_meta_val "$cwd")

  if [[ -n "$pending_jid" ]]; then
    local pending_meta="${LOGS_DIR}/job_${pending_jid}.meta"
    if [[ -f "$pending_meta" ]]; then
      job_id="$pending_jid"
      meta_file="$pending_meta"
      _meta_set_field "$meta_file" "STATUS" "running"
      rm -f "${LOGS_DIR}/job_${pending_jid}.pending"
      _log_info "Pending Job #${job_id} 디스패치 (DAG 의존성 충족)"
    else
      job_id=$(job_register "$prompt")
      meta_file="${LOGS_DIR}/job_${job_id}.meta"
      local _tmp="${meta_file}.tmp.$$"
      { cat "$meta_file"; echo "UUID=${job_uuid}"; } > "$_tmp" && mv -f "$_tmp" "$meta_file"
    fi
  else
    # Job 등록
    job_id=$(job_register "$prompt")
    meta_file="${LOGS_DIR}/job_${job_id}.meta"

    # .meta 파일에 UUID 기록 (원자적 append: temp → rename)
    local _tmp="${meta_file}.tmp.$$"
    { cat "$meta_file"; echo "UUID=${job_uuid}"; } > "$_tmp" && mv -f "$_tmp" "$meta_file"
  fi

  out_file="${LOGS_DIR}/job_${job_id}.out"

  # ── Worktree 결정: 재사용(rewind) > 새로 생성 ──
  local wt_path=""
  local effective_repo="${repo:-$TARGET_REPO}"

  if [[ -n "$reuse_wt" && -d "$reuse_wt" ]]; then
    # Rewind: 기존 worktree 재사용
    wt_path="$reuse_wt"
    _tmp="${meta_file}.tmp.$$"
    { cat "$meta_file"; echo "WORKTREE='${wt_path}'"; echo "REWIND=true"; } > "$_tmp" && mv -f "$_tmp" "$meta_file"
    _log_info "Job #${job_id} 기존 워크트리 재사용 (rewind): ${wt_path}"
  elif [[ "$use_worktree" == "true" && -n "$effective_repo" ]]; then
    # 새 worktree 생성
    wt_path=$(worktree_create "$job_id" "$effective_repo" 2>/dev/null)
    if [[ -n "$wt_path" && -d "$wt_path" ]]; then
      _tmp="${meta_file}.tmp.$$"
      { cat "$meta_file"; echo "WORKTREE='${wt_path}'"; echo "REPO='${effective_repo}'"; } > "$_tmp" && mv -f "$_tmp" "$meta_file"
      _log_info "Job #${job_id} 워크트리 생성됨: ${wt_path}"
    else
      _log_warn "Job #${job_id} 워크트리 생성 실패 — cwd 모드로 실행"
      wt_path=""
    fi
  fi

  # ── 이미지 파일을 @path 형태로 프롬프트에 추가 ──
  if [[ -n "$images_json" && "$images_json" != "null" ]]; then
    local img_count
    img_count=$(echo "$images_json" | jq -r 'length' 2>/dev/null)
    if [[ "$img_count" -gt 0 ]] 2>/dev/null; then
      local img_refs=""
      local i=0
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
      if [[ -n "$img_refs" ]]; then
        prompt="${prompt}${img_refs}"
      fi
    fi
  fi

  # claude -p 인자 구성 (stream-json + verbose로 실시간 추론 스트리밍)
  local args=()

  # ── 세션 플래그를 -p 보다 앞에 배치 (CLI 파서 호환성) ──
  if [[ -n "$session_raw" ]]; then
    case "$session_raw" in
      resume:*)
        local resume_sid="${session_raw#resume:}"
        args+=(--resume "$resume_sid")
        _log_info "Job 세션 모드: resume (sid=${resume_sid})"
        ;;
      fork:*)
        local fork_sid="${session_raw#fork:}"
        # Fork: 이전 세션의 결과를 컨텍스트로 주입하여 새 세션으로 실행
        local prev_result="" prev_prompt_text="" best_jid=0
        for mf in "${LOGS_DIR}"/job_*.meta; do
          [[ -f "$mf" ]] || continue
          local sid
          sid=$(_get_meta_field "$mf" "SESSION_ID")
          if [[ "$sid" == "$fork_sid" ]]; then
            local jid
            jid=$(_get_meta_field "$mf" "JOB_ID")
            # 가장 최신 job_id (가장 큰 숫자)를 선택
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
          # 이전 결과가 너무 길면 앞부분만 사용 (토큰 제한 방지)
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
        ;;
      continue)
        args+=(--continue)
        _log_info "Job 세션 모드: continue"
        ;;
    esac
  fi

  args+=(-p "$prompt")
  args+=(--output-format stream-json)
  args+=(--verbose)

  if [[ "${SKIP_PERMISSIONS:-false}" == "true" ]]; then
    args+=(--dangerously-skip-permissions)
  elif [[ -n "${DEFAULT_ALLOWED_TOOLS:-}" ]]; then
    args+=(--allowedTools "$DEFAULT_ALLOWED_TOOLS")
  fi

  if [[ -n "${DEFAULT_MODEL:-}" ]]; then
    args+=(--model "$DEFAULT_MODEL")
  fi

  if [[ -n "${APPEND_SYSTEM_PROMPT:-}" ]]; then
    args+=(--append-system-prompt "$APPEND_SYSTEM_PROMPT")
  fi

  # cwd 결정: worktree > JSON cwd > 글로벌 WORKING_DIR > 현재 디렉토리
  local effective_cwd
  if [[ -n "$wt_path" ]]; then
    effective_cwd="$wt_path"
  else
    effective_cwd="${cwd:-${WORKING_DIR:-$(pwd)}}"
  fi

  # .meta 파일에 CWD 기록
  echo "CWD='${effective_cwd}'" >> "$meta_file"

  # 백그라운드 서브쉘에서 실행 (cd로 작업 디렉토리 변경)
  (
    _log_info "Job #${job_id} 실행 시작 (uuid=${job_uuid}, cwd=${effective_cwd}, worktree=${wt_path:-none})"

    cd "$effective_cwd" 2>/dev/null || true

    # ── Worktree가 있으면 체크포인트 워처 시작 ──
    if [[ -n "$wt_path" && -d "$wt_path" ]]; then
      checkpoint_watcher_loop "$wt_path" "$job_id" "$meta_file" &
      _log_info "Job #${job_id} 체크포인트 워처 시작됨"
    fi

    # stream-json 출력을 파일에 쓰면서 session_id를 조기 캡처
    # stdbuf/gstdbuf로 라인 버퍼링 강제 (파일 리디렉션 시 블록 버퍼링 방지)
    if command -v stdbuf &>/dev/null; then
      stdbuf -oL "$CLAUDE_BIN" "${args[@]}" < /dev/null > "$out_file" 2>&1 &
    elif command -v gstdbuf &>/dev/null; then
      gstdbuf -oL "$CLAUDE_BIN" "${args[@]}" < /dev/null > "$out_file" 2>&1 &
    else
      "$CLAUDE_BIN" "${args[@]}" < /dev/null > "$out_file" 2>&1 &
    fi
    local claude_pid=$!

    # 조기 session_id 캡처: 출력 파일 첫 이벤트에서 session_id 추출
    local _sid_captured=""
    local _sid_wait=0
    while kill -0 "$claude_pid" 2>/dev/null && [[ $_sid_wait -lt 30 ]]; do
      if [[ -f "$out_file" && -s "$out_file" ]]; then
        _sid_captured=$(grep -m1 '"session_id"' "$out_file" 2>/dev/null | head -1 | jq -r '.session_id // empty' 2>/dev/null)
        if [[ -n "$_sid_captured" ]]; then
          job_set_session "$job_id" "$_sid_captured"
          session_save "$_sid_captured" "$prompt"
          _log_info "Job #${job_id} 조기 session_id 캡처: ${_sid_captured:0:8}..."
          break
        fi
      fi
      sleep 1
      (( _sid_wait++ )) || true
    done

    wait "$claude_pid" 2>/dev/null
    local exit_code=$?

    # 조기 캡처되지 않았다면 최종 result에서 추출
    if [[ -z "$_sid_captured" && -f "$out_file" ]]; then
      local result_line
      result_line=$(grep '"type":"result"' "$out_file" | tail -1)
      if [[ -n "$result_line" ]]; then
        local sid
        sid=$(echo "$result_line" | jq -r '.session_id // empty' 2>/dev/null)
        [[ -n "$sid" ]] && job_set_session "$job_id" "$sid"
        [[ -n "$sid" ]] && session_save "$sid" "$prompt"
      fi
    fi

    # 상태 갱신 (워처가 이 변경을 감지하고 최종 커밋 후 종료됨)
    if [[ $exit_code -eq 0 ]]; then
      job_mark_done "$job_id"
      _log_info "Job #${job_id} 완료 (exit=0)"
    else
      job_mark_failed "$job_id"
      _log_error "Job #${job_id} 실패 (exit=${exit_code})"
    fi

    # 체크포인트 워처 종료 대기
    wait 2>/dev/null || true

  ) &

  local bg_pid=$!
  job_set_pid "$job_id" "$bg_pid"

  local wt_label=""
  [[ -n "$wt_path" ]] && wt_label=" [worktree: $(basename "$wt_path")]"
  _log_info "Job #${job_id} 디스패치 완료${wt_label}"
  echo "  [디스패치] Job #${job_id} (uuid=${job_uuid})${wt_label} — session_id는 실행 후 자동 할당됩니다."
}

# ── start_service: 데몬 메인 루프 ───────────────────────────
start_service() {
  # 이미 실행 중인지 확인
  if [[ -f "$PID_FILE" ]]; then
    local existing_pid
    existing_pid=$(cat "$PID_FILE")
    if kill -0 "$existing_pid" 2>/dev/null; then
      echo "  [오류] 서비스가 이미 실행 중입니다 (PID: ${existing_pid})"
      echo "  'stop' 명령으로 먼저 종료하세요."
      exit 1
    else
      _log_warn "오래된 PID 파일 발견 (PID: ${existing_pid}). 정리합니다."
      rm -f "$PID_FILE"
    fi
  fi

  # 디렉토리 보장
  mkdir -p "$LOGS_DIR" "$QUEUE_DIR"

  # FIFO 생성
  if [[ -p "$FIFO_PATH" ]]; then
    chmod 600 "$FIFO_PATH"
    _log_warn "기존 FIFO 파이프 발견. 권한 확인 후 재사용합니다: ${FIFO_PATH}"
  else
    rm -f "$FIFO_PATH"
    mkfifo -m 600 "$FIFO_PATH"
    _log_info "FIFO 파이프 생성됨 (mode 600): ${FIFO_PATH}"
  fi

  # PID 기록
  echo $$ > "$PID_FILE"
  _log_info "서비스 시작 (PID: $$)"

  # 배너 출력
  _print_banner

  # ── 메인 수신 루프 ──────────────────────────────────────
  # 외부 while true: FIFO EOF 시 다시 열기
  # 내부 while read: 각 라인을 dispatch_job으로 전달
  while true; do
    while IFS= read -r line; do
      # 빈 줄 무시
      [[ -z "$line" ]] && continue
      # 주석 무시
      [[ "$line" == \#* ]] && continue

      dispatch_job "$line" || true
    done < "$FIFO_PATH"

    # FIFO EOF — 모든 writer가 닫힘. 재오픈 대기.
    _log_info "FIFO EOF 감지. 파이프를 다시 엽니다..."
  done
}

# ── stop_service: 외부에서 호출하여 서비스 종료 ──────────────
stop_service() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "  [오류] 실행 중인 서비스를 찾을 수 없습니다."
    return 1
  fi

  local pid
  pid=$(cat "$PID_FILE")

  if kill -0 "$pid" 2>/dev/null; then
    echo "  [종료] 서비스에 SIGTERM 전송 (PID: ${pid})..."
    kill "$pid"
    # 종료 대기 (최대 10초)
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 10 ]]; do
      sleep 1
      (( waited++ )) || true
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "  [경고] 정상 종료 실패. SIGKILL 전송..."
      kill -9 "$pid" 2>/dev/null
      rm -f "$PID_FILE" "$FIFO_PATH"
    fi

    echo "  [완료] 서비스가 종료되었습니다."
  else
    echo "  [정보] 프로세스가 이미 종료되어 있습니다. PID 파일을 정리합니다."
    rm -f "$PID_FILE"
  fi
}

# ── 메인 진입점 ──────────────────────────────────────────────
case "${1:-start}" in
  start)
    start_service
    ;;
  stop)
    stop_service
    ;;
  restart)
    stop_service 2>/dev/null || true
    sleep 1
    start_service
    ;;
  status)
    if [[ -f "$PID_FILE" ]]; then
      pid=$(cat "$PID_FILE")
      if kill -0 "$pid" 2>/dev/null; then
        echo "  [실행 중] PID: ${pid}, FIFO: ${FIFO_PATH}"
      else
        echo "  [중지됨] 프로세스 없음 (오래된 PID 파일: ${pid})"
      fi
    else
      echo "  [중지됨] 서비스가 실행 중이지 않습니다."
    fi
    ;;
  *)
    echo "사용법: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
