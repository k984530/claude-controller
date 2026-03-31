"""
Session 목록 HTTP 핸들러 Mixin

Claude Code 네이티브 세션 + history.log + job meta 파일을 통합하여 세션 목록을 제공한다.
"""

import os

from config import LOGS_DIR, SESSIONS_DIR, CLAUDE_PROJECTS_DIR
from utils import parse_meta_file, parse_job_output, correct_running_status, cwd_to_project_dir, scan_claude_sessions


_MAX_SESSIONS = 50          # 세션 목록 반환 최대 수
_MAX_PROJECT_DIRS = 15      # 스캔할 Claude 프로젝트 디렉토리 최대 수
_MAX_NATIVE_SESSIONS = 60   # 프로젝트당 네이티브 세션 스캔 최대 수


class SessionHandlerMixin:

    def _handle_sessions(self, filter_cwd=None):
        seen = {}
        self._collect_claude_native_sessions(seen, filter_cwd)
        self._collect_job_meta_sessions(seen)
        self._collect_history_log_sessions(seen)

        # cwd 필터 적용
        if filter_cwd:
            norm = os.path.normpath(filter_cwd)
            seen = {
                sid: s for sid, s in seen.items()
                if s.get("cwd") and os.path.normpath(s["cwd"]) == norm
            }

        sessions = sorted(seen.values(), key=lambda s: s.get("timestamp") or "", reverse=True)
        self._json_response(sessions[:_MAX_SESSIONS])

    @staticmethod
    def _collect_claude_native_sessions(seen, filter_cwd):
        """Claude Code 네이티브 세션을 스캔한다."""
        if filter_cwd:
            proj_name = cwd_to_project_dir(filter_cwd)
            project_dirs = [CLAUDE_PROJECTS_DIR / proj_name]
        else:
            if CLAUDE_PROJECTS_DIR.exists():
                all_dirs = sorted(
                    (d for d in CLAUDE_PROJECTS_DIR.iterdir() if d.is_dir()),
                    key=lambda d: d.stat().st_mtime,
                    reverse=True,
                )
                project_dirs = all_dirs[:_MAX_PROJECT_DIRS]
            else:
                project_dirs = []

        for pd in project_dirs:
            native = scan_claude_sessions(pd, limit=_MAX_NATIVE_SESSIONS)
            for sid, info in native.items():
                if sid not in seen:
                    seen[sid] = info

    @staticmethod
    def _collect_job_meta_sessions(seen):
        """Job meta 파일에서 세션 정보를 보강한다."""
        if not LOGS_DIR.exists():
            return

        meta_files = sorted(
            LOGS_DIR.glob("job_*.meta"),
            key=lambda f: int(f.stem.split("_")[1]),
            reverse=True,
        )
        for mf in meta_files:
            meta = parse_meta_file(mf)
            if not meta:
                continue
            sid = meta.get("SESSION_ID", "").strip()
            if not sid:
                continue

            status = correct_running_status(meta)

            job_id = meta.get("JOB_ID", "")
            cost_usd = None
            if status in ("done", "failed"):
                out_file = LOGS_DIR / f"job_{job_id}.out"
                parsed = parse_job_output(out_file)
                cost_usd = parsed["cost_usd"]

            entry = {
                "session_id": sid,
                "job_id":     job_id,
                "prompt":     meta.get("PROMPT", ""),
                "timestamp":  meta.get("CREATED_AT", ""),
                "status":     status,
                "cwd":        meta.get("CWD", ""),
                "cost_usd":   cost_usd,
                "slug":       "",
            }

            if sid not in seen:
                seen[sid] = entry
            else:
                existing = seen[sid]
                if existing.get("job_id") is None:
                    existing.update({"job_id": job_id, "status": status, "cost_usd": cost_usd})
                else:
                    try:
                        if int(job_id) > int(existing.get("job_id", 0)):
                            seen[sid] = entry
                    except (ValueError, TypeError):
                        pass

    @staticmethod
    def _collect_history_log_sessions(seen):
        """history.log에서 세션 정보를 보충한다."""
        history_file = SESSIONS_DIR / "history.log"
        if not history_file.exists():
            return
        try:
            for line in history_file.read_text("utf-8").strip().split("\n"):
                parts = line.split("|", 2)
                if len(parts) >= 2:
                    ts, sid = parts[0].strip(), parts[1].strip()
                    if not sid:
                        continue
                    prompt = parts[2].strip() if len(parts) > 2 else ""
                    if sid not in seen:
                        seen[sid] = {
                            "session_id": sid, "job_id": None,
                            "prompt": prompt, "timestamp": ts,
                            "status": "done", "cwd": None,
                            "cost_usd": None, "slug": "",
                        }
        except OSError:
            pass
