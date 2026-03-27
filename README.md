# Controller

A shell wrapper that runs Claude Code CLI as a headless daemon. Provides FIFO pipe-based async task dispatch, Git Worktree isolation, automatic checkpointing/rewind, and a web dashboard for remote task management.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Web Dashboard (Vanilla JS)                                     │
│  https://claude.won-space.com  <->  localhost:8420              │
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
│  │ (claude) │ │ (state)  │ │ (conv.)   │ │ (Git isolation)   │ │
│  └──────────┘ └──────────┘ └───────────┘ └───────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ checkpoint.sh (watch changes -> auto-commit -> rewind)    │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────┘
                       │ claude -p --output-format stream-json
                       ▼
              Claude Code CLI (headless)
```

## Project Structure

```
controller/
├── bin/                    # Entry points
│   ├── controller          # Service control (start/stop/restart/status)
│   ├── send                # CLI client — sends tasks to FIFO
│   ├── start               # Launch service + TUI together
│   ├── claude-sh           # Interactive shell mode entry point
│   ├── native-app.py       # Web server with auto browser launch
│   └── app-launcher.sh     # macOS app launcher
├── lib/                    # Core modules (Bash)
│   ├── executor.sh         # claude -p execution engine
│   ├── jobs.sh             # Job registration / state / result management
│   ├── session.sh          # Claude session ID tracking
│   ├── worktree.sh         # Git Worktree create / remove / list
│   └── checkpoint.sh       # Auto-checkpoint + Rewind
├── service/
│   └── controller.sh       # FIFO listener → dispatch persistent daemon
├── web/                    # HTTP REST API server (Python)
│   ├── server.py           # Module entry point
│   ├── handler.py          # REST API handler (GET/POST/DELETE)
│   ├── config.py           # Paths / security / SSL settings
│   ├── auth.py             # Token-based authentication
│   ├── jobs.py             # Job CRUD + FIFO messaging
│   ├── checkpoint.py       # Checkpoint queries + Rewind execution
│   ├── utils.py            # Meta file parser, service status check
│   └── static/             # Web dashboard (Vanilla JS/CSS)
├── config.sh               # Global config (paths, model, permissions, worktree)
├── data/                   # Runtime data (settings.json, auth_token)
├── logs/                   # Job output (.out) + metadata (.meta)
├── queue/                  # FIFO pipe (controller.pipe)
├── sessions/               # Session history (history.log)
├── uploads/                # File upload storage
└── worktrees/              # Git Worktree storage
```

## Getting Started

### Prerequisites

- macOS / Linux
- Claude Code CLI (`claude` command or app-bundled binary)
- Python 3.8+
- `jq` (JSON processing)
- Git (required for Worktree features)

### Running

```bash
# Start the service only
bin/controller start

# Start service + TUI together
bin/start

# Start the web server (auto-opens browser)
python3 bin/native-app.py

# Check service status
bin/controller status

# Stop the service
bin/controller stop
```

### Sending Tasks via CLI

```bash
# Send a basic prompt
bin/send "Fix the bug in auth.py"

# Specify a working directory
bin/send --cwd /path/to/repo "Write test code"

# Run in an isolated Git Worktree
bin/send --worktree --repo /path/to/repo "Perform refactoring"

# Specify a custom task ID
bin/send --id my-task-1 "Write README"

# Check all task statuses
bin/send --status

# View task result
bin/send --result <task_id>
```

## Key Features

### FIFO-Based Async Dispatch

The service daemon listens on a Named Pipe (`queue/controller.pipe`) for JSON messages and runs `claude -p` in the background. Supports duplicate prompt detection (3-second window), max concurrent job limits, and session modes (new/resume/fork/continue).

```json
{
  "id": "task-1",
  "prompt": "Fix the bug",
  "cwd": "/path/to/project",
  "worktree": "true",
  "session": "resume:<session_id>",
  "images": ["/path/to/screenshot.png"]
}
```

### Git Worktree Isolation

Each task runs in an independent Git Worktree, enabling parallel work without affecting the main branch. A `controller/job-<id>` branch is automatically created and can be cleaned up after completion.

### Auto-Checkpoint & Rewind

Periodically monitors file changes in the Worktree and auto-commits when changes stabilize. If something goes wrong, you can `git reset --hard` to a specific checkpoint and resume work with a new prompt that includes the previous conversation context (Rewind).

### Session Management

Tracks Claude Code session IDs to enable conversation continuity:

- **new** — Start a fresh session
- **resume** — Continue an existing session (`--resume <session_id>`)
- **fork** — Branch from a previous session by injecting its context
- **continue** — Continue the most recent conversation (`--continue`)

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Service running status |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/:id/result` | Get job result |
| GET | `/api/jobs/:id/stream` | Poll real-time stream (offset-based) |
| GET | `/api/jobs/:id/checkpoints` | List checkpoints |
| GET | `/api/sessions` | List sessions (Claude Code native + job meta) |
| GET | `/api/session/:id/job` | Find job by session ID |
| GET | `/api/config` | Get configuration |
| GET | `/api/recent-dirs` | Get recent working directories |
| GET | `/api/dirs?path=` | Browse filesystem directories |
| POST | `/api/send` | Send a new task (via FIFO) |
| POST | `/api/upload` | Upload a file (base64) |
| POST | `/api/jobs/:id/rewind` | Rewind to a checkpoint |
| POST | `/api/service/start` | Start the service |
| POST | `/api/service/stop` | Stop the service |
| POST | `/api/config` | Save configuration |
| POST | `/api/auth/verify` | Verify auth token |
| DELETE | `/api/jobs/:id` | Delete a job |
| DELETE | `/api/jobs` | Bulk delete completed jobs |

## Security

Three-layer security model:

1. **Host Header Validation** — Only allows `localhost`, `127.0.0.1`, `[::1]` to prevent DNS Rebinding attacks.
2. **Origin Validation (CORS)** — Only accepts cross-origin requests from an allowed Origin list.
3. **Token Authentication** — Generates a random token on server startup. When `AUTH_REQUIRED=true`, all API requests must include an `Authorization: Bearer <token>` header.

### SSL/HTTPS

Generate local certificates with `mkcert` to enable HTTPS mode:

```bash
mkcert -install
mkcert -cert-file certs/localhost+1.pem -key-file certs/localhost+1-key.pem localhost 127.0.0.1
```

## Configuration

Override settings via `data/settings.json` or environment variables:

| Setting | Default | Description |
|---------|---------|-------------|
| `skip_permissions` | `true` | Use `--dangerously-skip-permissions` flag |
| `model` | `""` | Claude model override (empty = default model) |
| `max_jobs` | `10` | Max concurrent background jobs |
| `target_repo` | `""` | Git repository path for Worktree creation |
| `base_branch` | `main` | Base branch for Worktree |
| `checkpoint_interval` | `5` | Checkpoint watch interval (seconds) |
| `append_system_prompt` | `""` | Additional system prompt text |
| `allowed_tools` | All tools | Tool allowlist for Claude |

## License

MIT
