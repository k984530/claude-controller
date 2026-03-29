#!/bin/bash
# post-edit-test.sh — PostToolUse hook: .py 편집 후 자동 테스트
#
# 동작:
#   1. Edit/Write 대상이 .py 파일인지 확인
#   2. 30초 쿨다운 적용 (연속 편집 시 과잉 실행 방지)
#   3. pytest 실행 후 실패 시만 경고 출력 → Claude에게 피드백
#
# stdin: { "tool_name": "...", "tool_input": {...}, "tool_output": "..." }

set -euo pipefail

COOLDOWN_FILE="/tmp/.controller-test-cooldown"
COOLDOWN_SEC=30
PROJECT_DIR="/Users/choiwon/Desktop/Orchestration/controller"

# ── 쿨다운 체크 ──
if [[ -f "$COOLDOWN_FILE" ]]; then
  LAST=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  if (( NOW - LAST < COOLDOWN_SEC )); then
    exit 0
  fi
fi

# ── 파일 경로 추출 ──
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

# ── 대상 파일 필터 ──
IS_PY=false
IS_SH=false
case "$FILE_PATH" in
  */web/*.py|*/tests/*.py|*/cognitive/*.py|*/dag/*.py|*/lib/*.py|*/bin/*.py)
    IS_PY=true ;;
  *.sh)
    IS_SH=true ;;
  *)
    exit 0 ;;
esac

# ── 쿨다운 갱신 ──
date +%s > "$COOLDOWN_FILE"

FEEDBACK=""

# ── Python: py_compile + pytest ──
if $IS_PY; then
  SYNTAX_ERR=""
  if [[ -f "$FILE_PATH" ]]; then
    SYNTAX_ERR=$(TARGET_FILE="$FILE_PATH" python3 -c "
import os, py_compile
py_compile.compile(os.environ['TARGET_FILE'], doraise=True)
" 2>&1) || true
  fi
  if [[ -n "$SYNTAX_ERR" ]]; then
    FEEDBACK="PY SYNTAX: $(echo "$SYNTAX_ERR" | tail -1) "
  fi

  cd "$PROJECT_DIR"
  RESULT=$(python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5) || true
  if echo "$RESULT" | grep -q "failed"; then
    FEEDBACK="${FEEDBACK}TEST FAIL: $(echo "$RESULT" | tail -1)"
  fi
fi

# ── Shell: bash -n 구문 검증 ──
if $IS_SH; then
  if [[ -f "$FILE_PATH" ]]; then
    SH_ERR=$(bash -n "$FILE_PATH" 2>&1) || true
    if [[ -n "$SH_ERR" ]]; then
      FEEDBACK="SH SYNTAX: $(echo "$SH_ERR" | head -3 | tr '\n' ' ')"
    fi
  fi
fi

if [[ -n "$FEEDBACK" ]]; then
  SAFE_FB=$(echo "$FEEDBACK" | tr '\n' ' ' | sed 's/"/\\"/g' | head -c 500)
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\",\"additionalContext\":\"$SAFE_FB\"}}"
fi
