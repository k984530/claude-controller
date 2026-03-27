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
  local pid="$1"
  cat <<EOF
============================================================
  Controller Service Daemon
============================================================
  PID       : ${pid}
  FIFO      : ${FIFO_PATH}
  로그      : ${SERVICE_LOG}
  최대 작업 : ${MAX_BACKGROUND_JOBS}
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

# ── dispatch_job: JSON 메시지 파싱 후 claude -p 실행 ────────
dispatch_job() {
  local json_line="$1"

  # JSON 유효성 검사
  if ! echo "$json_line" | jq empty 2>/dev/null; then
    _log_error "유효하지 않은 JSON: ${json_line:0:200}"
    return 1
  fi

  # 필드 추출 (callback은 보안상 제거됨 — eval 인젝션 방지)
  local job_uuid prompt cwd use_worktree repo session_raw
  job_uuid=$(echo "$json_line" | jq -r '.id // empty')
  prompt=$(echo "$json_line" | jq -r '.prompt // empty')
  cwd=$(echo "$json_line" | jq -r '.cwd // empty')
  use_worktree=$(echo "$json_line" | jq -r '.worktree // empty')
  repo=$(echo "$json_line" | jq -r '.repo // empty')
  session_raw=$(echo "$json_line" | jq -r '.session // empty')

  if [[ -z "$prompt" ]]; then
    _log_error "프롬프트가 비어있습니다: ${json_line:0:200}"
    return 1
  fi

  # 고유 ID가 없으면 생성
  if [[ -z "$job_uuid" ]]; then
    job_uuid=$(date '+%s')-$$-$RANDOM
  fi

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

  # Job 등록
  local job_id
  job_id=$(job_register "$prompt")

  local out_file="${LOGS_DIR}/job_${job_id}.out"
  local meta_file="${LOGS_DIR}/job_${job_id}.meta"

  # .meta 파일에 UUID 기록 (원자적 append: temp → rename)
  local _tmp="${meta_file}.tmp.$$"
  { cat "$meta_file"; echo "UUID=${job_uuid}"; } > "$_tmp" && mv -f "$_tmp" "$meta_file"

  # ── Worktree 생성 (요청된 경우) ──
  local wt_path=""
  local effective_repo="${repo:-$TARGET_REPO}"
  if [[ "$use_worktree" == "true" && -n "$effective_repo" ]]; then
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

  # claude -p 인자 구성 (stream-json + verbose로 실시간 추론 스트리밍)
  local args=()
  args+=(-p "$prompt")
  args+=(--output-format stream-json)
  args+=(--verbose)

  if [[ -n "${DEFAULT_ALLOWED_TOOLS:-}" ]]; then
    args+=(--allowedTools "$DEFAULT_ALLOWED_TOOLS")
  fi

  if [[ -n "${DEFAULT_MODEL:-}" ]]; then
    args+=(--model "$DEFAULT_MODEL")
  fi

  if [[ -n "${APPEND_SYSTEM_PROMPT:-}" ]]; then
    args+=(--append-system-prompt "$APPEND_SYSTEM_PROMPT")
  fi

  # 세션 이어가기 플래그
  if [[ -n "$session_raw" ]]; then
    case "$session_raw" in
      resume:*)
        args+=(--resume "${session_raw#resume:}")
        ;;
      continue)
        args+=(--continue)
        ;;
    esac
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
    _log_info "Job #${job_id} 실행 시작 (uuid=${job_uuid}, PID=$$, cwd=${effective_cwd}, worktree=${wt_path:-none})"

    cd "$effective_cwd" 2>/dev/null || true
    "$CLAUDE_BIN" "${args[@]}" < /dev/null > "$out_file" 2>&1
    local exit_code=$?

    # stream-json에서 최종 result와 session_id 추출
    if [[ -f "$out_file" ]]; then
      local result_line
      result_line=$(grep '"type":"result"' "$out_file" | tail -1)
      if [[ -n "$result_line" ]]; then
        local sid
        sid=$(echo "$result_line" | jq -r '.session_id // empty' 2>/dev/null)
        [[ -n "$sid" ]] && job_set_session "$job_id" "$sid"
        [[ -n "$sid" ]] && session_save "$sid" "$prompt"
      fi
    fi

    # 상태 갱신
    if [[ $exit_code -eq 0 ]]; then
      job_mark_done "$job_id"
      _log_info "Job #${job_id} 완료 (exit=0)"
    else
      job_mark_failed "$job_id"
      _log_error "Job #${job_id} 실패 (exit=${exit_code})"
    fi

  ) &

  local bg_pid=$!
  job_set_pid "$job_id" "$bg_pid"

  local wt_label=""
  [[ -n "$wt_path" ]] && wt_label=" [worktree: $(basename "$wt_path")]"
  _log_info "Job #${job_id} 디스패치 완료 (PID=${bg_pid})${wt_label}"
  echo "  [디스패치] Job #${job_id} (uuid=${job_uuid}) → PID ${bg_pid}${wt_label}"
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
    _log_warn "기존 FIFO 파이프 발견. 재사용합니다: ${FIFO_PATH}"
  else
    rm -f "$FIFO_PATH"
    mkfifo "$FIFO_PATH"
    _log_info "FIFO 파이프 생성됨: ${FIFO_PATH}"
  fi

  # PID 기록
  echo $$ > "$PID_FILE"
  _log_info "서비스 시작 (PID: $$)"

  # 배너 출력
  _print_banner $$

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
