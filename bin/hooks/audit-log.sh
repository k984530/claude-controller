#!/bin/bash
# audit-log.sh — PostToolUse hook: Bash 명령 실행 이력 기록
#
# 동작:
#   1. Bash 도구 실행 후 command 추출
#   2. 타임스탬프 + 명령어 + 종료코드를 로그 파일에 기록
#   3. 로그 파일 크기 제한 (10MB 초과 시 로테이션)
#
# stdin: { "tool_name": "Bash", "tool_input": {"command": "..."}, "tool_output": "..." }

set -euo pipefail

LOG_DIR="/Users/choiwon/Desktop/Orchestration/controller/logs"
LOG_FILE="$LOG_DIR/audit.log"
MAX_SIZE=$((10 * 1024 * 1024))  # 10MB

INPUT=$(cat)

# ── 명령어 추출 ──
CMD=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {})
    if isinstance(inp, str):
        import json as j2; inp = j2.loads(inp)
    print(inp.get('command', '')[:200])
except: print('')
" 2>/dev/null)

[[ -z "$CMD" ]] && exit 0

# ── 로그 로테이션 ──
if [[ -f "$LOG_FILE" ]]; then
  SIZE=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
  if (( SIZE > MAX_SIZE )); then
    mv "$LOG_FILE" "${LOG_FILE}.$(date +%Y%m%d%H%M%S).bak"
  fi
fi

# ── 로그 기록 ──
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] $CMD" >> "$LOG_FILE"
