#!/usr/bin/env bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Applications/cmux.app/Contents/Resources/bin:$PATH"

CONTROLLER_DIR="/Users/choiwon/Desktop/Orchestration/controller"
cd "$CONTROLLER_DIR" || exit 1
source "${CONTROLLER_DIR}/config.sh"

mkdir -p "$LOGS_DIR" "$QUEUE_DIR" "$SESSIONS_DIR" "$WORKTREES_DIR"

# 네이티브 데스크톱 앱 실행
exec python3 "${CONTROLLER_DIR}/bin/native-app.py"
