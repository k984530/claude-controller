#!/bin/bash
# stop-quality-gate.sh — Stop hook: 작업 종료 시 품질 게이트
#
# 동작:
#   1. 전체 테스트 실행
#   2. 미커밋 변경사항 경고
#   3. 결과 요약 출력 → Claude에게 피드백

set -uo pipefail

PROJECT_DIR="/Users/choiwon/Desktop/Orchestration/controller"
cd "$PROJECT_DIR"

ISSUES=()

# ── 1. 테스트 ──
TEST_RESULT=$(python3 -m pytest tests/ -q --tb=line 2>&1 | tail -3) || true
if echo "$TEST_RESULT" | grep -q "failed"; then
  ISSUES+=("TEST: $(echo "$TEST_RESULT" | tail -1)")
fi

# ── 2. 미커밋 변경 ──
DIRTY=$(git diff --stat HEAD 2>/dev/null | tail -1) || true
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ') || true

if [[ -n "$DIRTY" ]]; then
  ISSUES+=("UNCOMMITTED: $DIRTY")
fi
if (( UNTRACKED > 0 )); then
  ISSUES+=("UNTRACKED: ${UNTRACKED}개 파일")
fi

# ── JSON 출력 (Claude에게 피드백) ──
if (( ${#ISSUES[@]} > 0 )); then
  MSG=""
  for issue in "${ISSUES[@]}"; do
    MSG="${MSG}- ${issue} "
  done
  echo "{\"systemMessage\":\"QUALITY GATE: ${MSG}\"}"
fi
