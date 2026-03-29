#!/usr/bin/env bash
# ============================================================
# postinstall — npm install 후 런타임 디렉토리, 권한, 의존성 자동 설정
# ============================================================
set -uo pipefail

CONTROLLER_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── 색상 ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; }
warn() { printf "  ${YELLOW}!${NC} %s\n" "$1"; }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; }
info() { printf "  ${CYAN}→${NC} %s\n" "$1"; }

echo ""
printf "  ${BOLD}claude-controller${NC} setup\n"
echo "  ─────────────────────────────────"

# ── 1. 런타임 디렉토리 생성 ──
for dir in logs sessions data queue worktrees uploads certs; do
  mkdir -p "${CONTROLLER_DIR}/${dir}"
done
ok "런타임 디렉토리 생성 완료"

# ── 2. 실행 권한 부여 ──
chmod +x "${CONTROLLER_DIR}/bin/"* 2>/dev/null || true
chmod +x "${CONTROLLER_DIR}/service/"*.sh 2>/dev/null || true
ok "실행 권한 설정 완료"

# ── 3. Claude CLI 확인/설치 ──
CLAUDE_FOUND=false
if command -v claude &>/dev/null; then
  CLAUDE_VER=$(claude --version 2>/dev/null | head -1)
  ok "Claude CLI 감지: ${CLAUDE_VER}"
  CLAUDE_FOUND=true
else
  warn "Claude CLI가 설치되어 있지 않습니다"
  info "자동 설치 시도: npm i -g @anthropic-ai/claude-code"
  if npm i -g @anthropic-ai/claude-code 2>/dev/null; then
    CLAUDE_VER=$(claude --version 2>/dev/null | head -1)
    ok "Claude CLI 설치 완료: ${CLAUDE_VER}"
    CLAUDE_FOUND=true
  else
    fail "Claude CLI 자동 설치 실패"
    warn "수동 설치: npm i -g @anthropic-ai/claude-code"
    warn "권한 오류 시: sudo npm i -g @anthropic-ai/claude-code"
  fi
fi

# ── 4. python3 확인 ──
PYTHON_FOUND=false
if command -v python3 &>/dev/null; then
  PY_VER=$(python3 --version 2>/dev/null)
  ok "Python3 감지: ${PY_VER}"
  PYTHON_FOUND=true
else
  fail "python3를 찾을 수 없습니다 (웹 대시보드에 필요)"
  warn "macOS:  brew install python3"
  warn "Ubuntu: sudo apt install python3"
fi

# ── 5. 기본 설정 파일 생성 ──
SETTINGS_FILE="${CONTROLLER_DIR}/data/settings.json"
if [[ ! -f "$SETTINGS_FILE" ]]; then
  cat > "$SETTINGS_FILE" << 'SETTINGS'
{
  "skip_permissions": false,
  "allowed_tools": "Bash,Read,Write,Edit,Glob,Grep,Agent,NotebookEdit,WebFetch,WebSearch",
  "model": "",
  "max_jobs": 10,
  "checkpoint_interval": 5,
  "target_repo": "",
  "base_branch": "main",
  "append_system_prompt": "",
  "web_port": 3100,
  "auth_required": false
}
SETTINGS
  ok "기본 설정 파일 생성: data/settings.json"
else
  ok "기존 설정 파일 유지"
fi

# ── 결과 ──
echo ""
echo "  ─────────────────────────────────"

if $CLAUDE_FOUND && $PYTHON_FOUND; then
  printf "  ${GREEN}${BOLD}설치 완료! 바로 실행하세요:${NC}\n"
  echo ""
  printf "    ${BOLD}claude-start${NC}\n"
  echo ""
  info "웹 대시보드: http://localhost:3100"
  info "CLI 전송:    claude-send \"프롬프트\""
  info "셸 모드:     claude-sh"
else
  printf "  ${YELLOW}${BOLD}설치 완료 (일부 의존성 누락)${NC}\n"
  echo ""
  if ! $CLAUDE_FOUND; then
    warn "Claude CLI 설치 후 실행: npm i -g @anthropic-ai/claude-code"
  fi
  if ! $PYTHON_FOUND; then
    warn "python3 설치 필요 (웹 대시보드용)"
  fi
  echo ""
  info "의존성 설치 후: claude-start"
fi

echo ""
