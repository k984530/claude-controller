#!/usr/bin/env bash
# ============================================================
# postinstall — npm install 후 런타임 디렉토리 및 권한 설정
# ============================================================
set -euo pipefail

CONTROLLER_DIR="$(cd "$(dirname "$0")" && pwd)"

# 런타임 디렉토리 생성 (패키지에 포함되지 않는 것들)
for dir in logs sessions data queue worktrees uploads certs; do
  mkdir -p "${CONTROLLER_DIR}/${dir}"
done

# bin 스크립트에 실행 권한 부여
chmod +x "${CONTROLLER_DIR}/bin/"* 2>/dev/null || true
chmod +x "${CONTROLLER_DIR}/service/"*.sh 2>/dev/null || true

echo ""
echo "  claude-controller 설치 완료!"
echo ""
echo "  사용법:"
echo "    claude-controller start     서비스 시작"
echo "    claude-controller stop      서비스 중지"
echo "    claude-controller status    상태 확인"
echo "    claude-send \"프롬프트\"       작업 전송"
echo "    claude-start                서비스 + TUI 실행"
echo ""
echo "  웹 대시보드:"
echo "    npm run server              웹 서버 시작 (localhost:8420)"
echo ""
