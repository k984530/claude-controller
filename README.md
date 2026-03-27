# Controller

Claude Code CLI를 headless 데몬으로 감싸는 셸 래퍼입니다. FIFO 파이프 기반의 비동기 작업 디스패치, Git Worktree 격리 실행, 자동 체크포인트/리와인드를 제공하며, 웹 대시보드를 통해 원격으로 작업을 관리할 수 있습니다.

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│  Web Dashboard (Vanilla JS)                                     │
│  https://claude.won-space.com  ←→  localhost:8420               │
└────────────────────┬────────────────────────────────────────────┘
                     │ REST API (Python http.server)
┌────────────────────▼────────────────────────────────────────────┐
│  Web Server (native-app.py)                                     │
│  ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌───────────────────┐│
│  │ handler  │ │ jobs.py    │ │ auth.py  │ │ checkpoint.py     ││
│  │ (REST)   │ │ (FIFO I/O) │ │ (Bearer) │ │ (Rewind)          ││
│  └──────────┘ └─────┬──────┘ └──────────┘ └───────────────────┘│
└─────────────────────┼───────────────────────────────────────────┘
                      │ JSON via FIFO (queue/controller.pipe)
┌─────────────────────▼───────────────────────────────────────────┐
│  Controller Daemon (service/controller.sh)                      │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────────────┐ │
│  │ executor │ │ jobs.sh  │ │ session   │ │ worktree.sh       │ │
│  │ (claude) │ │ (상태)   │ │ (대화)    │ │ (Git 격리)        │ │
│  └──────────┘ └──────────┘ └───────────┘ └───────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ checkpoint.sh (변경 감시 → 자동 커밋 → Rewind 지원)       │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────┘
                       │ claude -p --output-format stream-json
                       ▼
              Claude Code CLI (headless)
```

## 프로젝트 구조

```
controller/
├── bin/                    # 실행 진입점
│   ├── controller          # 서비스 제어 (start/stop/restart/status)
│   ├── send                # CLI 클라이언트 — FIFO에 작업 전송
│   ├── start               # 서비스 + TUI 일괄 실행
│   ├── claude-sh           # 인터랙티브 셸 모드 진입점
│   ├── native-app.py       # 웹 서버 실행 + 브라우저 자동 오픈
│   └── app-launcher.sh     # macOS 앱 런처
├── lib/                    # 핵심 모듈 (Bash)
│   ├── executor.sh         # claude -p 실행 엔진
│   ├── jobs.sh             # 작업 등록/상태/결과 관리
│   ├── session.sh          # Claude 세션 ID 추적
│   ├── worktree.sh         # Git Worktree 생성/삭제/조회
│   └── checkpoint.sh       # 자동 체크포인트 + Rewind
├── service/
│   └── controller.sh       # FIFO 수신 → dispatch 상주 데몬
├── web/                    # HTTP REST API 서버 (Python)
│   ├── server.py           # 모듈 진입점
│   ├── handler.py          # REST API 핸들러 (GET/POST/DELETE)
│   ├── config.py           # 경로/보안/SSL 설정
│   ├── auth.py             # 토큰 기반 인증
│   ├── jobs.py             # Job CRUD + FIFO 전송
│   ├── checkpoint.py       # Checkpoint 조회 + Rewind 실행
│   ├── utils.py            # meta 파싱, 서비스 상태 확인
│   └── static/             # 웹 대시보드 (Vanilla JS/CSS)
├── config.sh               # 전역 설정 (경로, 모델, 권한, Worktree)
├── data/                   # 런타임 데이터 (settings.json, auth_token)
├── logs/                   # 작업 출력 (.out) + 메타데이터 (.meta)
├── queue/                  # FIFO 파이프 (controller.pipe)
├── sessions/               # 세션 히스토리 (history.log)
├── uploads/                # 파일 업로드 저장소
└── worktrees/              # Git Worktree 저장소
```

## 시작하기

### 요구사항

- macOS / Linux
- Claude Code CLI (`claude` 명령 또는 앱 내장 바이너리)
- Python 3.8+
- `jq` (JSON 처리)
- Git (Worktree 기능 사용 시)

### 실행

```bash
# 서비스만 실행
bin/controller start

# 서비스 + TUI 일괄 실행
bin/start

# 웹 서버 실행 (브라우저 자동 오픈)
python3 bin/native-app.py

# 서비스 상태 확인
bin/controller status

# 서비스 중지
bin/controller stop
```

### CLI로 작업 전송

```bash
# 기본 프롬프트 전송
bin/send "auth.py의 버그를 수정해줘"

# 작업 디렉토리 지정
bin/send --cwd /path/to/repo "테스트 코드 작성"

# Git Worktree 격리 실행
bin/send --worktree --repo /path/to/repo "리팩토링 수행"

# 작업 ID 직접 지정
bin/send --id my-task-1 "README 작성"

# 작업 상태 조회
bin/send --status

# 작업 결과 보기
bin/send --result <작업ID>
```

## 핵심 기능

### FIFO 기반 비동기 디스패치

서비스 데몬이 Named Pipe(`queue/controller.pipe`)에서 JSON 메시지를 수신하여 `claude -p`를 백그라운드로 실행합니다. 중복 프롬프트 감지(3초 윈도우), 최대 동시 작업 수 제한, 세션 모드(new/resume/fork/continue) 등을 지원합니다.

```json
{
  "id": "task-1",
  "prompt": "버그를 수정해줘",
  "cwd": "/path/to/project",
  "worktree": "true",
  "session": "resume:<session_id>",
  "images": ["/path/to/screenshot.png"]
}
```

### Git Worktree 격리 실행

각 작업을 독립된 Git Worktree에서 실행하여 메인 브랜치에 영향 없이 병렬 작업이 가능합니다. `controller/job-<id>` 브랜치가 자동 생성되고, 완료 후 정리할 수 있습니다.

### 자동 체크포인트 & Rewind

Worktree에서 실행 중인 작업의 파일 변경을 주기적으로 감시하여 안정화되면 자동 커밋합니다. 문제가 발생하면 특정 체크포인트 시점으로 `git reset --hard`하고, 이전 대화 컨텍스트를 포함한 새 프롬프트로 작업을 재개(Rewind)합니다.

### 세션 관리

Claude Code의 세션 ID를 추적하여 대화를 이어갈 수 있습니다:

- **new** — 새 세션으로 실행
- **resume** — 기존 세션을 이어서 실행 (`--resume <session_id>`)
- **fork** — 이전 세션의 컨텍스트를 주입하여 분기 실행
- **continue** — 가장 최근 대화를 이어서 실행 (`--continue`)

## REST API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/status` | 서비스 실행 상태 |
| GET | `/api/jobs` | 전체 작업 목록 |
| GET | `/api/jobs/:id/result` | 작업 결과 조회 |
| GET | `/api/jobs/:id/stream` | 실시간 스트림 폴링 (offset 기반) |
| GET | `/api/jobs/:id/checkpoints` | 체크포인트 목록 |
| GET | `/api/sessions` | 세션 목록 (Claude Code 네이티브 + Job 메타) |
| GET | `/api/session/:id/job` | 세션 ID로 작업 찾기 |
| GET | `/api/config` | 설정 조회 |
| GET | `/api/recent-dirs` | 최근 작업 디렉토리 |
| GET | `/api/dirs?path=` | 파일시스템 디렉토리 탐색 |
| POST | `/api/send` | 새 작업 전송 (FIFO) |
| POST | `/api/upload` | 파일 업로드 (base64) |
| POST | `/api/jobs/:id/rewind` | 체크포인트로 Rewind |
| POST | `/api/service/start` | 서비스 시작 |
| POST | `/api/service/stop` | 서비스 중지 |
| POST | `/api/config` | 설정 저장 |
| POST | `/api/auth/verify` | 토큰 검증 |
| DELETE | `/api/jobs/:id` | 작업 삭제 |
| DELETE | `/api/jobs` | 완료된 작업 일괄 삭제 |

## 보안

3중 보안 계층으로 구성되어 있습니다:

1. **Host 헤더 검증** — `localhost`, `127.0.0.1`, `[::1]`만 허용하여 DNS Rebinding 공격을 차단합니다.
2. **Origin 검증 (CORS)** — 허용된 Origin 목록에서만 교차 출처 요청을 수락합니다.
3. **토큰 인증** — 서버 시작 시 랜덤 토큰을 발급하며, `AUTH_REQUIRED=true` 설정 시 모든 API 요청에 `Authorization: Bearer <token>` 헤더가 필요합니다.

### SSL/HTTPS

`mkcert`로 로컬 인증서를 생성하면 HTTPS 모드로 실행됩니다:

```bash
mkcert -install
mkcert -cert-file certs/localhost+1.pem -key-file certs/localhost+1-key.pem localhost 127.0.0.1
```

## 설정

`data/settings.json` 또는 환경변수로 설정을 오버라이드할 수 있습니다:

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `skip_permissions` | `true` | `--dangerously-skip-permissions` 사용 여부 |
| `model` | `""` | Claude 모델 지정 (비어있으면 기본 모델) |
| `max_jobs` | `10` | 최대 동시 백그라운드 작업 수 |
| `target_repo` | `""` | Worktree 대상 Git 저장소 경로 |
| `base_branch` | `main` | Worktree 기준 브랜치 |
| `checkpoint_interval` | `5` | 체크포인트 감시 주기 (초) |
| `append_system_prompt` | `""` | 시스템 프롬프트 추가 |
| `allowed_tools` | 전체 도구 | Claude에 허용할 도구 목록 |

## 라이선스

MIT
