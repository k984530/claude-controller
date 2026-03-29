#!/bin/bash
# pre-write-guard.sh — PreToolUse hook: 민감 파일 쓰기 차단
#
# 동작:
#   1. Write/Edit 대상 파일 경로 추출
#   2. .env, credentials, secrets 등 민감 파일 패턴 매칭
#   3. 매칭 시 차단 JSON 반환
#
# stdin: { "tool_name": "Write|Edit", "tool_input": {"file_path": "..."} }

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {})
    if isinstance(inp, str):
        import json as j2; inp = j2.loads(inp)
    print(inp.get('file_path', ''))
except: print('')
" 2>/dev/null)

[[ -z "$FILE_PATH" ]] && exit 0

BASENAME=$(basename "$FILE_PATH")
BLOCKED=""

# .env 파일 (환경 변수 / 시크릿)
if echo "$BASENAME" | grep -qE '^\.(env|env\.local|env\.production|env\.secret)$'; then
  BLOCKED=".env 파일 쓰기 차단 — 시크릿 유출 위험"
fi

# credentials / secrets 파일
if echo "$BASENAME" | grep -qiE '^(credentials|secrets|service.?account).*\.(json|yaml|yml|key|pem)$'; then
  BLOCKED="인증 정보 파일 쓰기 차단"
fi

# SSH 키
if echo "$FILE_PATH" | grep -qE '\.ssh/(id_|authorized_keys|known_hosts)'; then
  BLOCKED="SSH 키 파일 쓰기 차단"
fi

# 인증서 비밀키
if echo "$BASENAME" | grep -qiE '\.(key|p12|pfx)$'; then
  BLOCKED="비밀키 파일 쓰기 차단"
fi

if [[ -n "$BLOCKED" ]]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"WRITE GUARD: $BLOCKED\"}}"
fi
