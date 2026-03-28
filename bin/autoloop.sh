#!/usr/bin/env bash
# ============================================================
# autoloop.sh — 5분 주기 통합 모니터링 + 파이프라인 틱
#
# 역할:
#   1. Controller 서비스 헬스체크 (죽었으면 자동 재시작)
#   2. 파이프라인 tick-all (단계 자동 진행)
#   3. Stuck job 감지 (30분 이상 running)
#   4. 고아 프로세스 감지
#   5. 디스크 사용량 경고
#   6. 기본 로그 로테이션
#
# crontab:
#   */5 * * * * /path/to/autoloop.sh >> logs/autoloop.log 2>&1
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTROLLER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$CONTROLLER_DIR/service/controller.pid"
FIFO_PATH="$CONTROLLER_DIR/queue/controller.pipe"
LOGS_DIR="$CONTROLLER_DIR/logs"
WORKTREES_DIR="$CONTROLLER_DIR/worktrees"
PYTHON="$(command -v python3 2>/dev/null || echo "/opt/homebrew/opt/python@3.14/bin/python3.14")"
CTL="$PYTHON $CONTROLLER_DIR/bin/ctl"

# 설정
STUCK_THRESHOLD_MIN=30         # 이 시간(분) 이상 running이면 stuck
DISK_WARN_MB=500               # 디스크 경고 임계값 (MB)
DISK_CRITICAL_MB=2000          # 디스크 위험 임계값 (MB)
LOG_MAX_SIZE_MB=10             # service.log 로테이션 임계값
MAX_RESTART_ATTEMPTS=3         # 연속 재시작 최대 횟수
RESTART_STATE_FILE="$CONTROLLER_DIR/data/.restart_count"

NOW=$(date '+%Y-%m-%d %H:%M:%S')
ISSUES=()

log() { echo "[$NOW] $1"; }
warn() { echo "[$NOW] WARN: $1"; ISSUES+=("$1"); }
err()  { echo "[$NOW] ERROR: $1"; ISSUES+=("$1"); }

# ── 1. 서비스 헬스체크 ──────────────────────────────────────

check_service() {
  local pid=""
  if [[ -f "$PID_FILE" ]]; then
    pid=$(cat "$PID_FILE" 2>/dev/null)
  fi

  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    # 프로세스 살아있음 + FIFO 존재 확인
    if [[ -p "$FIFO_PATH" ]]; then
      log "Service OK (PID $pid)"
      # 재시작 카운터 리셋
      rm -f "$RESTART_STATE_FILE"
      return 0
    else
      warn "FIFO missing — pipe가 없음, 서비스 재시작 필요"
      return 1
    fi
  else
    warn "Service DOWN — PID ${pid:-unknown} 응답 없음"
    return 1
  fi
}

restart_service() {
  # 재시작 횟수 체크 (무한 루프 방지)
  local count=0
  if [[ -f "$RESTART_STATE_FILE" ]]; then
    count=$(cat "$RESTART_STATE_FILE" 2>/dev/null || echo 0)
  fi

  if (( count >= MAX_RESTART_ATTEMPTS )); then
    err "재시작 ${MAX_RESTART_ATTEMPTS}회 초과 — cooldown. 수동 확인 필요"
    # macOS 알림
    osascript -e 'display notification "Controller 재시작 실패 (3회 초과). 수동 확인 필요." with title "AutoLoop" sound name "Basso"' 2>/dev/null || true
    return 1
  fi

  echo $(( count + 1 )) > "$RESTART_STATE_FILE"
  log "서비스 재시작 시도 (#$(( count + 1 ))/$MAX_RESTART_ATTEMPTS)..."

  # 고아 프로세스 정리 후 시작
  cleanup_zombies
  "$CONTROLLER_DIR/bin/controller" start 2>/dev/null
  sleep 2

  if check_service 2>/dev/null; then
    log "서비스 재시작 성공"
    osascript -e 'display notification "Controller 서비스 자동 재시작 완료" with title "AutoLoop"' 2>/dev/null || true
    rm -f "$RESTART_STATE_FILE"
    return 0
  else
    err "서비스 재시작 실패"
    return 1
  fi
}

# ── 2. 파이프라인 tick ─────────────────────────────────────

tick_pipelines() {
  local result
  result=$($CTL pipeline tick-all 2>&1) || true
  if [[ -n "$result" && "$result" != "[]" ]]; then
    log "Pipeline tick: $result"

    # 새 단계가 시작되면 알림
    if echo "$result" | grep -q '"action": "dispatched"'; then
      local phase
      phase=$(echo "$result" | $PYTHON -c "import sys,json; r=json.load(sys.stdin); print(next((x['result'].get('label','?') for x in r if x.get('result',{}).get('action')=='dispatched'),'?'))" 2>/dev/null || echo "?")
      osascript -e "display notification \"파이프라인 단계 시작: $phase\" with title \"AutoLoop\"" 2>/dev/null || true
    fi

    # 파이프라인 완료 알림
    if echo "$result" | grep -q '"action": "done"'; then
      osascript -e 'display notification "파이프라인 완료!" with title "AutoLoop" sound name "Glass"' 2>/dev/null || true
    fi

    # 파이프라인 실패 감지 ("error": null이 아닌 실제 에러만)
    if echo "$result" | grep -q '"error":' && ! echo "$result" | grep -q '"error": null'; then
      warn "파이프라인 tick 에러 발생"
    fi
  else
    log "Pipeline tick: 활성 파이프라인 없음"
  fi
}

# ── 3. Stuck job 감지 ──────────────────────────────────────

check_stuck_jobs() {
  local now_epoch
  now_epoch=$(date +%s)

  for meta in "$LOGS_DIR"/job_*.meta; do
    [[ -f "$meta" ]] || continue

    local status created_at job_id
    status=$(grep '^STATUS=' "$meta" 2>/dev/null | cut -d= -f2 || true)
    [[ "$status" == "running" ]] || continue

    job_id=$(grep '^JOB_ID=' "$meta" 2>/dev/null | cut -d= -f2 || true)
    created_at=$(grep '^CREATED_AT=' "$meta" 2>/dev/null | sed "s/^CREATED_AT='//" | sed "s/'$//" || true)

    if [[ -n "$created_at" ]]; then
      local job_epoch
      job_epoch=$(date -j -f "%Y-%m-%d %H:%M:%S" "$created_at" +%s 2>/dev/null || echo 0)
      local elapsed_min=$(( (now_epoch - job_epoch) / 60 ))

      if (( elapsed_min > STUCK_THRESHOLD_MIN )); then
        warn "Job $job_id stuck: ${elapsed_min}분째 running"
      fi
    fi
  done
}

# ── 4. 고아 프로세스 감지/정리 ──────────────────────────────

cleanup_zombies() {
  local controller_pid=""
  if [[ -f "$PID_FILE" ]]; then
    controller_pid=$(cat "$PID_FILE" 2>/dev/null)
  fi

  # controller가 죽었는데 claude 프로세스가 남아있는 경우
  if [[ -n "$controller_pid" ]] && ! kill -0 "$controller_pid" 2>/dev/null; then
    local orphans
    orphans=$(pgrep -f "claude.*-p" 2>/dev/null || true)
    if [[ -n "$orphans" ]]; then
      warn "고아 claude 프로세스 감지: $orphans"
      # 여기서는 감지만 하고 kill은 하지 않음 (안전)
      # 실제 kill이 필요하면 아래 주석 해제
      # echo "$orphans" | xargs kill -TERM 2>/dev/null || true
    fi
  fi
}

# ── 5. 디스크 사용량 체크 ──────────────────────────────────

check_disk() {
  local logs_kb=0 wt_kb=0

  if [[ -d "$LOGS_DIR" ]]; then
    logs_kb=$(du -sk "$LOGS_DIR" 2>/dev/null | awk '{print $1}')
  fi
  if [[ -d "$WORKTREES_DIR" ]]; then
    wt_kb=$(du -sk "$WORKTREES_DIR" 2>/dev/null | awk '{print $1}')
  fi

  local total_mb=$(( (logs_kb + wt_kb) / 1024 ))

  if (( total_mb > DISK_CRITICAL_MB )); then
    err "디스크 위험: ${total_mb}MB (logs+worktrees). 긴급 정리 필요"
    osascript -e "display notification \"디스크 ${total_mb}MB — 긴급 정리 필요\" with title \"AutoLoop\" sound name \"Basso\"" 2>/dev/null || true
  elif (( total_mb > DISK_WARN_MB )); then
    warn "디스크 경고: ${total_mb}MB (logs+worktrees)"
  else
    log "Disk OK: ${total_mb}MB"
  fi
}

# ── 6. 로그 로테이션 ──────────────────────────────────────

rotate_logs() {
  local service_log="$LOGS_DIR/service.log"
  if [[ -f "$service_log" ]]; then
    local size_mb
    size_mb=$(( $(stat -f%z "$service_log" 2>/dev/null || echo 0) / 1048576 ))
    if (( size_mb > LOG_MAX_SIZE_MB )); then
      log "service.log 로테이션: ${size_mb}MB > ${LOG_MAX_SIZE_MB}MB"
      # 3세대 로테이션
      [[ -f "${service_log}.2.gz" ]] && rm -f "${service_log}.2.gz"
      [[ -f "${service_log}.1.gz" ]] && mv "${service_log}.1.gz" "${service_log}.2.gz"
      [[ -f "${service_log}.0" ]] && gzip "${service_log}.0" && mv "${service_log}.0.gz" "${service_log}.1.gz"
      mv "$service_log" "${service_log}.0"
      touch "$service_log"
    fi
  fi

  # autoloop.log 자체도 로테이션
  local autoloop_log="$LOGS_DIR/autoloop.log"
  if [[ -f "$autoloop_log" ]]; then
    local size_mb
    size_mb=$(( $(stat -f%z "$autoloop_log" 2>/dev/null || echo 0) / 1048576 ))
    if (( size_mb > LOG_MAX_SIZE_MB )); then
      log "autoloop.log 로테이션"
      mv "$autoloop_log" "${autoloop_log}.old"
      touch "$autoloop_log"
    fi
  fi
}

# ── 메인 실행 ──────────────────────────────────────────────

main() {
  log "========== autoloop tick =========="

  # 1. 로그 로테이션 (가장 먼저 — 디스크 보호)
  rotate_logs

  # 2. 서비스 헬스체크 + 자동 재시작
  if ! check_service; then
    restart_service || true
  fi

  # 3. 파이프라인 tick (서비스가 살아있을 때만 의미있음)
  if check_service 2>/dev/null; then
    tick_pipelines
  fi

  # 4. Stuck job 감지
  check_stuck_jobs

  # 5. 고아 프로세스 체크
  cleanup_zombies

  # 6. 디스크 사용량
  check_disk

  # 요약
  if (( ${#ISSUES[@]} > 0 )); then
    log "Issues (${#ISSUES[@]}): ${ISSUES[*]}"
  else
    log "All OK"
  fi

  log "========== done =========="
}

main "$@"
