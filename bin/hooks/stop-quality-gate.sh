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

# ── 2. Shell 스크립트 구문 검증 ──
SH_ERRORS=0
while IFS= read -r shfile; do
  if ! bash -n "$shfile" 2>/dev/null; then
    SH_ERRORS=$((SH_ERRORS + 1))
    ISSUES+=("SH_SYNTAX: $(basename "$shfile") 구문 오류")
  fi
done < <(find "$PROJECT_DIR" -name '*.sh' -not -path '*/node_modules/*' 2>/dev/null)

# ── 3. JSON 설정 파일 검증 ──
for jsonfile in "$PROJECT_DIR"/.claude/settings.json "$PROJECT_DIR"/package.json; do
  if [[ -f "$jsonfile" ]]; then
    if ! python3 -m json.tool "$jsonfile" > /dev/null 2>&1; then
      ISSUES+=("JSON_SYNTAX: $(basename "$jsonfile") 파싱 실패")
    fi
  fi
done

# ── 4. JavaScript 구문 검증 (node -c) ──
if command -v node &> /dev/null; then
  JS_ERRORS=0
  while IFS= read -r jsfile; do
    if ! node -c "$jsfile" 2>/dev/null; then
      JS_ERRORS=$((JS_ERRORS + 1))
      ISSUES+=("JS_SYNTAX: $(basename "$jsfile") 구문 오류")
    fi
  done < <(find "$PROJECT_DIR" -name '*.js' -not -path '*/node_modules/*' -not -path '*/.next/*' 2>/dev/null)
fi

# ── 5. 감사 로그 요약 (최근 세션) ──
AUDIT_LOG="$PROJECT_DIR/logs/audit.log"
if [[ -f "$AUDIT_LOG" ]]; then
  WARN_COUNT=$(grep -c '\[WARN\]\|\[CRIT\]' "$AUDIT_LOG" 2>/dev/null || echo 0)
  if (( WARN_COUNT > 0 )); then
    ISSUES+=("AUDIT: 위험 명령 ${WARN_COUNT}건 감지 — logs/audit.log 확인 필요")
  fi
fi

# ── 6. Python import 검증 (순환 import 탐지) ──
PY_IMPORT_ERRS=0
for pydir in web cognitive dag lib bin; do
  TARGET="$PROJECT_DIR/$pydir"
  [[ -d "$TARGET" ]] || continue
  while IFS= read -r pyfile; do
    IMPORT_ERR=$(TARGET_FILE="$pyfile" python3 -c "
import py_compile, os
try:
    py_compile.compile(os.environ['TARGET_FILE'], doraise=True)
except py_compile.PyCompileError as e:
    print(str(e)[:120])
" 2>&1) || true
    if [[ -n "$IMPORT_ERR" ]]; then
      PY_IMPORT_ERRS=$((PY_IMPORT_ERRS + 1))
      ISSUES+=("PY_IMPORT: $(basename "$pyfile") — $IMPORT_ERR")
    fi
  done < <(find "$TARGET" -maxdepth 2 -name '*.py' -not -name '__init__.py' 2>/dev/null | head -20)
done

# ── 7. Hook 자체 테스트 ──
HOOK_TEST="$PROJECT_DIR/tests/test_hooks.sh"
if [[ -f "$HOOK_TEST" ]]; then
  HOOK_RESULT=$(bash "$HOOK_TEST" 2>&1 | tail -3) || true
  if echo "$HOOK_RESULT" | grep -q "FAIL"; then
    FAIL_COUNT=$(echo "$HOOK_RESULT" | grep -oE 'FAIL: [0-9]+' | grep -oE '[0-9]+')
    ISSUES+=("HOOK_TEST: ${FAIL_COUNT:-?}건 실패 — tests/test_hooks.sh 확인")
  fi
fi

# ── 8. YAML 파일 구문 검증 ──
if command -v python3 &> /dev/null; then
  YAML_ERRORS=0
  while IFS= read -r yamlfile; do
    YAML_ERR=$(TARGET_FILE="$yamlfile" python3 -c "
import yaml, os
try:
    with open(os.environ['TARGET_FILE']) as f: yaml.safe_load(f)
except yaml.YAMLError as e:
    print(str(e)[:100])
except ImportError:
    pass
" 2>&1) || true
    if [[ -n "$YAML_ERR" ]]; then
      YAML_ERRORS=$((YAML_ERRORS + 1))
      ISSUES+=("YAML_SYNTAX: $(basename "$yamlfile") — $YAML_ERR")
    fi
  done < <(find "$PROJECT_DIR" \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null | grep -v node_modules | head -20)
fi

# ── 9. TODO/FIXME/HACK 잔류 감지 (미커밋 diff 내) ──
TODO_HITS=$(git diff HEAD 2>/dev/null | grep -E '^\+' | grep -v '^\+\+\+' | \
  grep -ciE '(TODO|FIXME|HACK|XXX|TEMP|WORKAROUND)\b' 2>/dev/null || echo 0)
if (( TODO_HITS > 0 )); then
  ISSUES+=("TODO_MARKERS: 미커밋 diff에 TODO/FIXME/HACK 마커 ${TODO_HITS}건 — 의도적 잔류인지 확인")
fi

# ── 10. 테스트 .only/.skip 잔류 감지 ──
FOCUS_HITS=$(git diff HEAD 2>/dev/null | grep -E '^\+' | grep -v '^\+\+\+' | \
  grep -cE '\.(only|skip)\s*\(' 2>/dev/null || echo 0)
if (( FOCUS_HITS > 0 )); then
  ISSUES+=("TEST_FOCUS: .only()/.skip() ${FOCUS_HITS}건 잔류 — 커밋 전 제거 필요")
fi

# ── 11. console.log 잔류 감지 (JS/TS diff 내) ──
CONSOLE_HITS=$(git diff HEAD -- '*.js' '*.ts' '*.tsx' '*.jsx' 2>/dev/null | grep -E '^\+' | grep -v '^\+\+\+' | \
  grep -cE 'console\.(log|warn|error|debug|info)\(' 2>/dev/null || echo 0)
if (( CONSOLE_HITS > 0 )); then
  ISSUES+=("CONSOLE_LOG: JS/TS diff에 console.* 호출 ${CONSOLE_HITS}건 — 프로덕션 코드 확인")
fi

# ── 12. 디버그 문 감지 (커밋되지 않은 변경 내) ──
DEBUG_HITS=$(git diff HEAD 2>/dev/null | grep -E '^\+' | grep -v '^\+\+\+' | \
  grep -cE '(debugger;|pdb\.set_trace|breakpoint\(\)|print\(\s*f?["\x27]DEBUG|System\.out\.println)' 2>/dev/null || echo 0)
if (( DEBUG_HITS > 0 )); then
  ISSUES+=("DEBUG_STMT: 미커밋 diff에 디버그 문 ${DEBUG_HITS}건 — 커밋 전 제거 권장")
fi

# ── 13. 하드코딩 시크릿 패턴 감지 ──
SECRET_HITS=$(git diff HEAD 2>/dev/null | grep -E '^\+' | grep -v '^\+\+\+' | \
  grep -ciE '(password|passwd|secret|api_key|apikey|token|auth)\s*[:=]\s*["\x27][^"\x27]{8,}' 2>/dev/null || echo 0)
if (( SECRET_HITS > 0 )); then
  ISSUES+=("HARDCODED_SECRET: 시크릿 패턴 ${SECRET_HITS}건 감지 — 환경변수/vault 사용 권장")
fi

# ── 14. 대규모 미커밋 변경 경고 ──
DIFF_LINES=$(git diff --stat HEAD 2>/dev/null | tail -1 | grep -oE '[0-9]+ insertion|[0-9]+ deletion' | grep -oE '[0-9]+' | paste -sd+ - | bc 2>/dev/null || echo 0)
if (( DIFF_LINES > 1000 )); then
  ISSUES+=("LARGE_DIFF: 미커밋 변경 ${DIFF_LINES}줄 — 단계적 커밋 권장")
fi

# ── 15. 미커밋 변경 ──
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
