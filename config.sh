#!/usr/bin/env bash
# ============================================================
# Controller Service — Configuration
# ============================================================

# Claude CLI 경로
# 1) 환경변수 CLAUDE_BIN이 있으면 사용
# 2) PATH에서 claude를 찾음
# 3) macOS 앱 기본 경로
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "/Applications/cmux.app/Contents/Resources/bin/claude")}"

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

# 완료/실패 작업 파일 보존 기간 (일) — 이 기간이 지난 job_*.out/.meta 자동 삭제
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-30}"

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

# ── 권한 설정 ──────────────────────────────────────────────
# true로 설정 시 --dangerously-skip-permissions 사용 (모든 도구 무제한 허용)
# 보안상 기본값은 false — 필요 시 환경변수 또는 settings.json에서 명시적으로 활성화
SKIP_PERMISSIONS="${SKIP_PERMISSIONS:-false}"

# ── Checkpoint 설정 ────────────────────────────────────────
# 체크포인트 감시 주기 (초) — 이 간격으로 worktree 변경을 확인
CHECKPOINT_INTERVAL="${CHECKPOINT_INTERVAL:-5}"

# ── settings.json 오버라이드 ────────────────────────────────
# data/settings.json이 존재하면 해당 값으로 기본값을 덮어씀
SETTINGS_FILE="${CONTROLLER_DIR}/data/settings.json"
if [[ -f "$SETTINGS_FILE" ]] && command -v jq &>/dev/null; then
  _s() { jq -r "$1 // empty" "$SETTINGS_FILE" 2>/dev/null; }
  _v=$(_s '.skip_permissions');       [[ -n "$_v" ]] && SKIP_PERMISSIONS="$_v"
  _v=$(_s '.allowed_tools');          [[ -n "$_v" ]] && DEFAULT_ALLOWED_TOOLS="$_v"
  _v=$(_s '.model');                  [[ -n "$_v" ]] && DEFAULT_MODEL="$_v"
  _v=$(_s '.max_jobs');               [[ -n "$_v" ]] && MAX_BACKGROUND_JOBS="$_v"
  _v=$(_s '.append_system_prompt');   [[ -n "$_v" ]] && APPEND_SYSTEM_PROMPT="$_v"
  _v=$(_s '.target_repo');            [[ -n "$_v" ]] && TARGET_REPO="$_v"
  _v=$(_s '.base_branch');            [[ -n "$_v" ]] && BASE_BRANCH="$_v"
  _v=$(_s '.checkpoint_interval');    [[ -n "$_v" ]] && CHECKPOINT_INTERVAL="$_v"
  _v=$(_s '.log_retention_days');     [[ -n "$_v" ]] && LOG_RETENTION_DAYS="$_v"
  unset -f _s; unset _v
fi
