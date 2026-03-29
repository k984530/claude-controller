#!/bin/bash
# pre-safety-guard.sh — PreToolUse hook: 파괴적 git/bash 명령 차단
#
# 동작:
#   1. Bash 도구 호출 시 command를 추출
#   2. 파괴적 패턴 매칭 (force push, reset --hard, rm -rf 등)
#   3. 매칭 시 차단 JSON 반환 → Claude에게 거부 피드백
#
# stdin: { "tool_name": "Bash", "tool_input": {"command": "..."} }

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {})
    if isinstance(inp, str):
        import json as j2; inp = j2.loads(inp)
    print(inp.get('command', ''))
except: print('')
" 2>/dev/null)

[[ -z "$COMMAND" ]] && exit 0

# ── 파괴적 패턴 목록 ──
BLOCKED=""

# git force push (main/master 보호)
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force|git\s+push\s+-f'; then
  if echo "$COMMAND" | grep -qE '\b(main|master)\b'; then
    BLOCKED="git force push to main/master 금지"
  fi
fi

# git reset --hard
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
  BLOCKED="git reset --hard 감지 — 커밋되지 않은 변경사항이 사라질 수 있음"
fi

# rm -rf on project root or broad paths
if echo "$COMMAND" | grep -qE 'rm\s+-rf\s+(/|~|\.\.|\.(/|$))'; then
  BLOCKED="rm -rf 위험 경로 감지"
fi

# git clean -f (untracked 파일 삭제)
if echo "$COMMAND" | grep -qE 'git\s+clean\s+-[a-zA-Z]*f'; then
  BLOCKED="git clean -f 감지 — untracked 파일이 삭제됨"
fi

# git checkout . (모든 변경 폐기)
if echo "$COMMAND" | grep -qE 'git\s+checkout\s+\.\s*$'; then
  BLOCKED="git checkout . 감지 — 모든 변경사항 폐기"
fi

# git branch -D (강제 브랜치 삭제)
if echo "$COMMAND" | grep -qE 'git\s+branch\s+-[a-zA-Z]*D'; then
  BLOCKED="git branch -D 감지 — 브랜치 강제 삭제 위험"
fi

# git restore . (모든 변경 폐기)
if echo "$COMMAND" | grep -qE 'git\s+restore\s+\.\s*$'; then
  BLOCKED="git restore . 감지 — 모든 변경사항 폐기"
fi

# chmod 777 (과도한 권한)
if echo "$COMMAND" | grep -qE 'chmod\s+777'; then
  BLOCKED="chmod 777 감지 — 과도한 파일 권한 설정"
fi

# SQL 파괴 명령 (DROP, TRUNCATE)
if echo "$COMMAND" | grep -qiE '(DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)'; then
  BLOCKED="SQL 파괴 명령 감지 (DROP/TRUNCATE)"
fi

# --no-verify (hook 우회 방지)
if echo "$COMMAND" | grep -qE 'git\s+.*--no-verify'; then
  BLOCKED="--no-verify 감지 — git hook 우회 금지"
fi

# ── 차단 결과 ──
if [[ -n "$BLOCKED" ]]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"SAFETY GUARD: $BLOCKED\"}}"
fi
