#!/bin/bash
# notify-completion.sh — Notification hook: macOS 알림
#
# 동작:
#   Claude가 Notification 이벤트를 발생시키면 macOS 알림으로 전달
#
# stdin: { "message": "..." }

set -euo pipefail

INPUT=$(cat)
MSG=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('message', d.get('title', 'Claude Code 알림')))
except: print('Claude Code 작업 완료')
" 2>/dev/null || echo "Claude Code 작업 완료")

# macOS 알림 (소리 포함)
osascript -e "display notification \"$MSG\" with title \"Controller\" sound name \"Glass\"" 2>/dev/null || true
