#!/usr/bin/env bash
# ============================================================
# Controller Service — Configuration
# ============================================================

# Claude CLI 경로 (앱에서 실행 시 PATH가 제한적이므로 절대 경로 지정)
CLAUDE_BIN="${CLAUDE_BIN:-/Applications/cmux.app/Contents/Resources/bin/claude}"

# 기본 출력 형식 (stream-json: 실시간 토큰 스트리밍)
DEFAULT_OUTPUT_FORMAT="${DEFAULT_OUTPUT_FORMAT:-stream-json}"

# 모든 도구 권한 허용
DEFAULT_ALLOWED_TOOLS="${DEFAULT_ALLOWED_TOOLS:-Bash,Read,Write,Edit,Glob,Grep,Agent,NotebookEdit,WebFetch,WebSearch}"

# 모델 설정
DEFAULT_MODEL="${DEFAULT_MODEL:-}"

# 디렉토리 경로
CONTROLLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="${CONTROLLER_DIR}/logs"
SESSIONS_DIR="${CONTROLLER_DIR}/sessions"
QUEUE_DIR="${CONTROLLER_DIR}/queue"

# FIFO 파이프 경로 — 외부에서 이 파이프에 쓰면 서비스가 수신
FIFO_PATH="${CONTROLLER_DIR}/queue/controller.pipe"

# PID 파일
PID_FILE="${CONTROLLER_DIR}/service/controller.pid"

# 최대 동시 백그라운드 작업 수
MAX_BACKGROUND_JOBS="${MAX_BACKGROUND_JOBS:-10}"

# 시스템 프롬프트 추가
APPEND_SYSTEM_PROMPT="${APPEND_SYSTEM_PROMPT:-}"

# 작업 디렉토리 — claude -p 실행 시 --cwd
WORKING_DIR="${WORKING_DIR:-}"

# ── Worktree 설정 ─────────────────────────────────────────
# 대상 Git 저장소 (worktree 생성 원본)
TARGET_REPO="${TARGET_REPO:-}"

# 워크트리 기준 브랜치
BASE_BRANCH="${BASE_BRANCH:-main}"

# 워크트리 저장 디렉토리
WORKTREES_DIR="${CONTROLLER_DIR}/worktrees"
