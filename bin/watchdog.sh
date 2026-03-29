#!/usr/bin/env bash
# ============================================================
# watchdog.sh — Controller 프로세스 워치독
#
# 역할:
#   - Controller 서비스를 10초 주기로 감시
#   - 크래시 감지 시 자동 재시작
#   - 연속 실패 시 지수 백오프 (10s → 20s → 40s → 최대 120s)
#   - 정상 가동 60초 이상이면 백오프 리셋
#   - macOS 알림으로 재시작/실패 통보
#
# 사용법:
#   watchdog.sh start   — 워치독 데몬 시작
#   watchdog.sh stop    — 워치독 중지
#   watchdog.sh status  — 워치독 상태 확인
#   watchdog.sh install — macOS launchd plist 설치
#   watchdog.sh uninstall — launchd plist 제거
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 경로 ──
PID_FILE="${CONTROLLER_DIR}/service/watchdog.pid"
CONTROLLER_PID_FILE="${CONTROLLER_DIR}/service/controller.pid"
STATE_FILE="${CONTROLLER_DIR}/data/watchdog_state.json"
LOG_FILE="${CONTROLLER_DIR}/logs/watchdog.log"
CONTROLLER_BIN="${CONTROLLER_DIR}/bin/controller"

# ── 설정 ──
CHECK_INTERVAL=10          # 기본 감시 간격 (초)
MAX_BACKOFF=120            # 최대 백오프 간격 (초)
STABLE_THRESHOLD=60        # 정상 가동 판정 시간 (초)
MAX_CONSECUTIVE_FAILS=10   # 연속 실패 시 대기 모드 진입 횟수

# ── launchd ──
PLIST_LABEL="com.orchestration.controller.watchdog"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

# 디렉토리 보장
mkdir -p "${CONTROLLER_DIR}/logs" "${CONTROLLER_DIR}/data" "${CONTROLLER_DIR}/service"

# ── 로깅 ──
_log() {
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[${ts}] $*" >> "$LOG_FILE"
}

# ── 상태 파일 갱신 ──
_write_state() {
  local status="$1"
  local restart_count="$2"
  local last_restart="${3:-}"
  local message="${4:-}"
  local now
  now=$(date '+%Y-%m-%dT%H:%M:%S')

  cat > "$STATE_FILE" <<EOF
{
  "status": "${status}",
  "pid": $$,
  "restart_count": ${restart_count},
  "consecutive_fails": ${_CONSECUTIVE_FAILS:-0},
  "last_restart": "${last_restart}",
  "last_check": "${now}",
  "uptime_since": "${_STARTED_AT:-${now}}",
  "message": "${message}"
}
EOF
}

# ── 컨트롤러 상태 확인 ──
_is_controller_alive() {
  if [[ ! -f "$CONTROLLER_PID_FILE" ]]; then
    return 1
  fi
  local pid
  pid=$(cat "$CONTROLLER_PID_FILE" 2>/dev/null)
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

# ── 컨트롤러 재시작 ──
_restart_controller() {
  _log "Controller 재시작 시도..."

  # 기존 좀비 정리
  if [[ -f "$CONTROLLER_PID_FILE" ]]; then
    local old_pid
    old_pid=$(cat "$CONTROLLER_PID_FILE" 2>/dev/null)
    if [[ -n "$old_pid" ]]; then
      kill "$old_pid" 2>/dev/null || true
      sleep 1
      kill -9 "$old_pid" 2>/dev/null || true
    fi
    rm -f "$CONTROLLER_PID_FILE"
  fi

  # controller start (백그라운드)
  nohup "$CONTROLLER_BIN" start >> "$LOG_FILE" 2>&1 &
  sleep 3

  if _is_controller_alive; then
    _log "Controller 재시작 성공 (PID: $(cat "$CONTROLLER_PID_FILE" 2>/dev/null))"
    return 0
  else
    _log "Controller 재시작 실패"
    return 1
  fi
}

# ── macOS 알림 ──
_notify() {
  local title="$1"
  local message="$2"
  local sound="${3:-default}"
  osascript -e "display notification \"${message}\" with title \"${title}\" sound name \"${sound}\"" 2>/dev/null || true
}

# ── 메인 감시 루프 ──
_watchdog_loop() {
  _STARTED_AT=$(date '+%Y-%m-%dT%H:%M:%S')
  local restart_count=0
  _CONSECUTIVE_FAILS=0
  local current_interval=$CHECK_INTERVAL
  local last_restart_time=""
  local controller_up_since=0

  _log "워치독 시작 (PID: $$, 간격: ${CHECK_INTERVAL}초)"
  _write_state "running" "$restart_count" "" "감시 시작"

  while true; do
    sleep "$current_interval"

    if _is_controller_alive; then
      # 정상 — 백오프 리셋 조건 체크
      local now_epoch
      now_epoch=$(date +%s)
      if [[ $controller_up_since -eq 0 ]]; then
        controller_up_since=$now_epoch
      fi

      local uptime=$(( now_epoch - controller_up_since ))
      if [[ $uptime -ge $STABLE_THRESHOLD && $_CONSECUTIVE_FAILS -gt 0 ]]; then
        _log "정상 가동 ${uptime}초 — 백오프 리셋"
        _CONSECUTIVE_FAILS=0
        current_interval=$CHECK_INTERVAL
      fi

      _write_state "running" "$restart_count" "$last_restart_time" "정상 감시 중"
    else
      # 다운 감지
      controller_up_since=0
      (( _CONSECUTIVE_FAILS++ )) || true
      _log "Controller 다운 감지 (연속 실패: ${_CONSECUTIVE_FAILS})"

      if [[ $_CONSECUTIVE_FAILS -ge $MAX_CONSECUTIVE_FAILS ]]; then
        _log "연속 실패 ${MAX_CONSECUTIVE_FAILS}회 도달 — 대기 모드"
        _write_state "cooldown" "$restart_count" "$last_restart_time" "연속 실패 ${_CONSECUTIVE_FAILS}회 — 수동 확인 필요"
        _notify "Watchdog" "Controller 복구 실패 (${_CONSECUTIVE_FAILS}회). 수동 확인 필요." "Basso"

        # 5분 대기 후 다시 시도
        sleep 300
        _CONSECUTIVE_FAILS=0
        current_interval=$CHECK_INTERVAL
        _log "대기 모드 종료, 감시 재개"
        _write_state "running" "$restart_count" "$last_restart_time" "감시 재개"
        continue
      fi

      # 재시작 시도
      if _restart_controller; then
        (( restart_count++ )) || true
        last_restart_time=$(date '+%Y-%m-%dT%H:%M:%S')
        _CONSECUTIVE_FAILS=0
        current_interval=$CHECK_INTERVAL
        controller_up_since=$(date +%s)

        _write_state "running" "$restart_count" "$last_restart_time" "재시작 성공"
        _notify "Watchdog" "Controller 자동 재시작 완료 (#${restart_count})" "Glass"
      else
        # 지수 백오프
        current_interval=$(( CHECK_INTERVAL * (2 ** (_CONSECUTIVE_FAILS - 1)) ))
        if [[ $current_interval -gt $MAX_BACKOFF ]]; then
          current_interval=$MAX_BACKOFF
        fi

        _write_state "retrying" "$restart_count" "$last_restart_time" "재시작 실패, ${current_interval}초 후 재시도"
        _log "재시작 실패 — 다음 체크 ${current_interval}초 후"
        _notify "Watchdog" "Controller 재시작 실패. ${current_interval}초 후 재시도." "Basso"
      fi
    fi
  done
}

# ── cleanup ──
_cleanup() {
  _log "워치독 종료 (PID: $$)"
  _write_state "stopped" "0" "" "정상 종료"
  rm -f "$PID_FILE"
}
trap _cleanup EXIT SIGTERM SIGINT SIGHUP

# ── start ──
cmd_start() {
  # 이미 실행 중인지 확인
  if [[ -f "$PID_FILE" ]]; then
    local existing_pid
    existing_pid=$(cat "$PID_FILE" 2>/dev/null)
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
      echo "워치독이 이미 실행 중입니다 (PID: ${existing_pid})"
      exit 1
    fi
    rm -f "$PID_FILE"
  fi

  # 데몬화 (백그라운드)
  if [[ "${_WATCHDOG_FOREGROUND:-}" != "true" ]]; then
    _WATCHDOG_FOREGROUND=true nohup "$0" start >> "$LOG_FILE" 2>&1 &
    local bg_pid=$!
    echo "$bg_pid" > "$PID_FILE"
    echo "워치독 시작됨 (PID: ${bg_pid})"
    echo "로그: ${LOG_FILE}"
    exit 0
  fi

  # 포그라운드 실행 (데몬 모드)
  echo $$ > "$PID_FILE"
  _watchdog_loop
}

# ── stop ──
cmd_stop() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "실행 중인 워치독이 없습니다."
    return 1
  fi

  local pid
  pid=$(cat "$PID_FILE" 2>/dev/null)
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 5 ]]; do
      sleep 1
      (( waited++ )) || true
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    echo "워치독 종료됨 (PID: ${pid})"
  else
    rm -f "$PID_FILE"
    echo "워치독이 이미 종료되어 있습니다. PID 파일을 정리했습니다."
  fi
}

# ── status ──
cmd_status() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "워치독 실행 중 (PID: ${pid})"
      if [[ -f "$STATE_FILE" ]]; then
        cat "$STATE_FILE"
      fi
      return 0
    else
      echo "워치독 중지됨 (오래된 PID: ${pid})"
      rm -f "$PID_FILE"
      return 1
    fi
  else
    echo "워치독이 실행 중이지 않습니다."
    return 1
  fi
}

# ── install (macOS launchd) ──
cmd_install() {
  local watchdog_path
  watchdog_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

  mkdir -p "$HOME/Library/LaunchAgents"

  cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${watchdog_path}</string>
    <string>start</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_FILE}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_FILE}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>_WATCHDOG_FOREGROUND</key>
    <string>true</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
</dict>
</plist>
PLIST

  launchctl load "$PLIST_PATH" 2>/dev/null || true
  echo "launchd plist 설치 완료: ${PLIST_PATH}"
  echo "워치독이 부팅 시 자동으로 시작됩니다."
  echo ""
  echo "수동 제어:"
  echo "  launchctl start ${PLIST_LABEL}   # 즉시 시작"
  echo "  launchctl stop  ${PLIST_LABEL}   # 즉시 중지"
}

# ── uninstall ──
cmd_uninstall() {
  if [[ -f "$PLIST_PATH" ]]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "launchd plist 제거 완료."
  else
    echo "설치된 plist가 없습니다."
  fi
  # 실행 중이면 중지
  cmd_stop 2>/dev/null || true
}

# ── 메인 진입점 ──
case "${1:-status}" in
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  status)    cmd_status ;;
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  *)
    echo "사용법: watchdog.sh {start|stop|status|install|uninstall}"
    exit 1
    ;;
esac
