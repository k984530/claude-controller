# ============================================================
# Claude Controller — Docker Image
# python:3.11-slim 기반, git + jq + Node.js + Claude CLI 포함
# ============================================================

FROM python:3.11-slim

LABEL maintainer="choiwon"
LABEL description="Claude Code headless controller — FIFO daemon + web dashboard"

# ── 시스템 의존성 ──
# git: worktree 격리, jq: JSON 파싱, bash: 데몬 스크립트
# curl: 헬스체크, coreutils: stdbuf (라인 버퍼링)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    jq \
    bash \
    curl \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 설치 (Claude CLI용) ──
# nodesource에서 LTS(20.x) 설치
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Claude CLI 설치 ──
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# ── 작업 디렉토리 ──
WORKDIR /app

# ── 소스 복사 ──
COPY . /app/

# ── 런타임 디렉토리 생성 (볼륨 마운트 대상) ──
RUN mkdir -p /app/logs /app/data /app/queue /app/sessions \
             /app/uploads /app/worktrees /app/certs

# ── 실행 권한 ──
RUN chmod +x /app/bin/* /app/service/*.sh 2>/dev/null || true

# ── 기본 설정 파일 생성 (없을 때만) ──
RUN if [ ! -f /app/data/settings.json ]; then \
    cat > /app/data/settings.json <<'EOF' \
{ \
  "skip_permissions": false, \
  "allowed_tools": "Bash,Read,Write,Edit,Glob,Grep,Agent,NotebookEdit,WebFetch,WebSearch", \
  "model": "", \
  "max_jobs": 10, \
  "checkpoint_interval": 5, \
  "target_repo": "", \
  "base_branch": "main", \
  "append_system_prompt": "", \
  "web_port": 8420, \
  "auth_required": false \
} \
EOF \
fi

# ── 환경변수 ──
# ANTHROPIC_API_KEY는 런타임에 주입 (docker run -e 또는 docker-compose)
ENV PORT=8420
ENV PYTHONUNBUFFERED=1
# 컨테이너 내에서는 SSL 없이 HTTP 모드로 실행
ENV SSL_CERT=""
ENV SSL_KEY=""

# ── 포트 노출 ──
EXPOSE 8420

# ── 헬스체크 ──
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8420/api/health || exit 1

# ── 엔트리포인트 ──
# native-app.py가 데몬 + 웹서버를 모두 기동
CMD ["python3", "/app/bin/native-app.py"]
