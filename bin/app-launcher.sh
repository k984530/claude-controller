#!/usr/bin/env bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Applications/cmux.app/Contents/Resources/bin:$PATH"
CONTROLLER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CONTROLLER_DIR" || exit 1
source config.sh
mkdir -p "$LOGS_DIR" "$QUEUE_DIR" "$SESSIONS_DIR" "$WORKTREES_DIR"

# 서비스 시작
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then true; else
  rm -f "$FIFO_PATH" "$PID_FILE" 2>/dev/null
  bash service/controller.sh start >> "$LOGS_DIR/service.log" 2>&1 &
  sleep 2
fi

# 네이티브 앱 실행
exec /opt/homebrew/bin/python3 bin/native-app.py 2>> "$LOGS_DIR/app.log"
