# Controller

A shell wrapper that runs Claude Code CLI as a headless daemon. Provides FIFO pipe-based async task dispatch, Git Worktree isolation, automatic checkpointing/rewind, automation pipelines, and a web dashboard for remote task management.

## Install

```bash
npm install -g claude-controller
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Web Dashboard (Vanilla JS)                                      │
│  https://localhost:8420                                          │
│  ┌────────┐ ┌──────┐ ┌───────┐ ┌─────────┐ ┌───────┐ ┌───────┐│
│  │ Jobs   │ │Goals │ │Presets│ │Pipelines│ │Skills │ │Results││
│  └────────┘ └──────┘ └───────┘ └─────────┘ └───────┘ └───────┘│
└────────────────────┬─────────────────────────────────────────────┘
                     │ REST API (Python http.server)
┌────────────────────▼─────────────────────────────────────────────┐
│  Web Server (native-app.py)                                      │
│  ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌───────────────────┐ │
│  │ handler  │ │ jobs.py    │ │ auth.py  │ │ checkpoint.py     │ │
│  │ (REST)   │ │ (FIFO I/O) │ │ (Bearer) │ │ (Rewind)          │ │
│  ├──────────┤ ├────────────┤ ├──────────┤ ├───────────────────┤ │
│  │pipeline  │ │ presets.py │ │ goals    │ │ suggestions.py    │ │
│  │(automate)│ │ (templates)│ │(tracking)│ │ (AI recommend)    │ │
│  └──────────┘ └─────┬──────┘ └──────────┘ └───────────────────┘ │
└─────────────────────┼────────────────────────────────────────────┘
                      │ JSON via FIFO (queue/controller.pipe)
┌─────────────────────▼────────────────────────────────────────────┐
│  Controller Daemon (service/controller.sh)                       │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────────────┐  │
│  │ executor │ │ jobs.sh  │ │ session   │ │ worktree.sh       │  │
│  │ (claude) │ │ (state)  │ │ (conv.)   │ │ (Git isolation)   │  │
│  └──────────┘ └──────────┘ └───────────┘ └───────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ checkpoint.sh (watch changes -> auto-commit -> rewind)    │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────┬───────────────────────────────────────────┘
                       │ claude -p --output-format stream-json
                       ▼
              Claude Code CLI (headless)
```

## Project Structure

```
controller/
├── bin/                        # Entry points
│   ├── controller              # Service control (start/stop/restart/status)
│   ├── send                    # CLI client — sends tasks to FIFO
│   ├── start                   # Launch service + web server together
│   ├── ctl                     # Multi-command CLI tool
│   ├── claude-sh               # Interactive shell mode entry point
│   ├── native-app.py           # Web server with auto browser launch
│   ├── autoloop.sh             # Auto-loop daemon for pipeline scheduling
│   ├── watchdog.sh             # Service health monitor + auto-restart
│   ├── app-launcher.sh         # macOS app launcher
│   └── hooks/                  # Claude Code harness hooks
│       ├── pre-safety-guard.sh # Pre-tool safety validation
│       ├── pre-write-guard.sh  # Pre-write file protection
│       ├── post-edit-test.sh   # Post-edit auto-test runner
│       ├── post-bash-error-context.sh  # Bash error context injection
│       ├── stop-quality-gate.sh# Stop-response quality gate
│       ├── audit-log.sh        # API call audit logging
│       └── notify-completion.sh# Job completion notification
├── lib/                        # Core modules (Bash)
│   ├── executor.sh             # claude -p execution engine
│   ├── jobs.sh                 # Job registration / state / result management
│   ├── session.sh              # Claude session ID tracking
│   ├── worktree.sh             # Git Worktree create / remove / list
│   ├── checkpoint.sh           # Auto-checkpoint + Rewind
│   ├── dispatch-helpers.sh     # Shared dispatch utilities
│   └── meta-io.sh             # Job metadata I/O helpers
├── service/
│   └── controller.sh           # FIFO listener → dispatch persistent daemon
├── web/                        # HTTP REST API server (Python)
│   ├── server.py               # Module entry point
│   ├── handler.py              # REST API router (GET/POST/DELETE dispatch)
│   ├── handler_base.py         # Response, Security, StaticServe mixins
│   ├── handler_jobs.py         # Job CRUD + streaming handlers
│   ├── handler_sessions.py     # Session management handlers
│   ├── handler_fs.py           # Filesystem + skills handlers
│   ├── handler_crud.py         # Project + Pipeline CRUD handlers
│   ├── handler_goals.py        # Goal tracking handlers
│   ├── handler_presets.py      # Preset template handlers
│   ├── handler_suggestions.py  # AI suggestion handlers
│   ├── config.py               # Paths / security / SSL settings
│   ├── auth.py                 # Token-based authentication
│   ├── jobs.py                 # Job CRUD + FIFO messaging
│   ├── pipeline.py             # Automation pipeline engine
│   ├── pipeline_crud.py        # Pipeline CRUD operations
│   ├── pipeline_classify.py    # Job-to-pipeline classifier
│   ├── pipeline_context.py     # Pipeline context builder
│   ├── presets.py              # Preset template management
│   ├── suggestions.py          # AI-driven suggestion system
│   ├── suggestions_analyze.py  # Job history analysis for suggestions
│   ├── projects.py             # Multi-project management
│   ├── checkpoint.py           # Checkpoint queries + Rewind execution
│   ├── health.py               # Health check endpoint
│   ├── audit.py                # API audit logging
│   ├── webhook.py              # Webhook delivery
│   ├── utils.py                # Meta file parser, service status check
│   └── static/                 # Web dashboard (Vanilla JS/CSS)
├── config.sh                   # Global config (paths, model, permissions)
├── data/                       # Runtime data (settings, goals, auth_token)
├── logs/                       # Job output (.out) + metadata (.meta)
├── queue/                      # FIFO pipe (controller.pipe)
├── sessions/                   # Session history (history.log)
├── uploads/                    # File upload storage
└── worktrees/                  # Git Worktree storage
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

### Automation Pipelines

Define recurring task pipelines that execute on configurable intervals. Each pipeline ties a prompt template to a project directory with auto-scheduling, execution history, and evolution tracking.

### Goal Tracking

File-based goal system (`data/goals/*.md`) with YAML frontmatter. Create, track, and execute project goals with checkbox-based task progress. Goals can dispatch individual tasks to Claude for automated execution.

### Presets

Reusable prompt templates with configurable parameters. Save frequently used task configurations as presets for quick dispatch.

### AI Suggestions

Analyzes job execution history to generate actionable suggestions — optimization tips, error pattern detection, and workflow improvements.

### Claude Code Hooks

Shell-based hooks (`bin/hooks/`) that integrate with Claude Code's harness system:

- **pre-safety-guard** — Validates tool calls before execution
- **pre-write-guard** — Protects critical files from modification
- **post-edit-test** — Runs tests automatically after code edits
- **stop-quality-gate** — Enforces response quality standards
- **audit-log** — Logs all API calls for audit trail

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Service running status |
| GET | `/api/health` | Server health check |
| GET | `/api/jobs` | List all jobs (paginated) |
| GET | `/api/jobs/:id/result` | Get job result |
| GET | `/api/jobs/:id/stream` | Poll real-time stream (offset-based) |
| GET | `/api/jobs/:id/checkpoints` | List checkpoints |
| GET | `/api/jobs/:id/diff` | Get job diff |
| GET | `/api/sessions` | List sessions |
| GET | `/api/session/:id/job` | Find job by session ID |
| GET | `/api/projects` | List registered projects |
| GET | `/api/projects/:id` | Get project details |
| GET | `/api/projects/:id/jobs` | List jobs for a project |
| GET | `/api/config` | Get configuration |
| GET | `/api/skills` | Get skill definitions |
| GET | `/api/recent-dirs` | Get recent working directories |
| GET | `/api/dirs?path=` | Browse filesystem directories |
| GET | `/api/goals?status=` | List goals (filter by status) |
| GET | `/api/goals/:id` | Get goal details |
| GET | `/api/presets` | List presets |
| GET | `/api/presets/:id` | Get preset details |
| GET | `/api/suggestions?status=` | List suggestions |
| GET | `/api/results` | Get recent results |
| GET | `/api/stats` | Get job statistics |
| GET | `/api/audit` | Search audit logs |
| GET | `/api/pipelines` | List pipelines |
| GET | `/api/pipelines/:id/status` | Pipeline status |
| GET | `/api/pipelines/:id/history` | Pipeline execution history |
| GET | `/api/pipelines/evolution` | Pipeline evolution summary |
| POST | `/api/send` | Send a new task (via FIFO) |
| POST | `/api/upload` | Upload a file (base64) |
| POST | `/api/jobs/:id/rewind` | Rewind to a checkpoint |
| POST | `/api/service/start` | Start the service |
| POST | `/api/service/stop` | Stop the service |
| POST | `/api/config` | Save configuration |
| POST | `/api/skills` | Save skill definitions |
| POST | `/api/goals` | Create a new goal |
| POST | `/api/goals/:id/update` | Update a goal |
| POST | `/api/goals/:id/execute` | Execute goal tasks via AI |
| POST | `/api/presets` | Create a preset |
| POST | `/api/presets/:id` | Update a preset |
| POST | `/api/suggestions/generate` | Generate AI suggestions |
| POST | `/api/suggestions/:id/apply` | Apply a suggestion |
| POST | `/api/suggestions/:id/dismiss` | Dismiss a suggestion |
| POST | `/api/suggestions/clear` | Clear dismissed suggestions |
| POST | `/api/pipelines` | Create a pipeline |
| POST | `/api/pipelines/:id/run` | Run a pipeline |
| POST | `/api/pipelines/:id/stop` | Stop a pipeline |
| POST | `/api/pipelines/:id/update` | Update a pipeline |
| POST | `/api/pipelines/:id/reset` | Reset pipeline state |
| POST | `/api/pipelines/tick-all` | Tick all pipeline schedules |
| POST | `/api/auth/verify` | Verify auth token |
| POST | `/api/webhooks/test` | Test webhook delivery |
| DELETE | `/api/jobs/:id` | Delete a job |
| DELETE | `/api/jobs` | Bulk delete completed jobs |
| DELETE | `/api/projects/:id` | Remove a project |
| DELETE | `/api/pipelines/:id` | Delete a pipeline |
| DELETE | `/api/presets/:id` | Delete a preset |
| DELETE | `/api/suggestions/:id` | Delete a suggestion |
| DELETE | `/api/goals/:id` | Delete a goal |

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
| `skip_permissions` | `false` | Use `--dangerously-skip-permissions` flag |
| `model` | `""` | Claude model override (empty = default) |
| `max_jobs` | `10` | Max concurrent background jobs |
| `target_repo` | `""` | Git repository path for Worktree creation |
| `base_branch` | `main` | Base branch for Worktree |
| `checkpoint_interval` | `5` | Checkpoint watch interval (seconds) |
| `append_system_prompt` | `""` | Additional system prompt text |
| `allowed_tools` | All tools | Tool allowlist for Claude |
| `webhook_url` | `""` | Webhook URL for job completion notifications |

## License

MIT
