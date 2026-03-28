"""
Session 목록 HTTP 핸들러 Mixin

Claude Code 네이티브 세션 + history.log + job meta 파일을 통합하여 세션 목록을 제공한다.
"""

import json
import os

from config import LOGS_DIR, SESSIONS_DIR, CLAUDE_PROJECTS_DIR
from utils import parse_meta_file, cwd_to_project_dir, scan_claude_sessions


class SessionHandlerMixin:

    def _handle_sessions(self, filter_cwd=None):
        seen = {}

        # 0) Claude Code 네이티브 세션 스캔
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
                project_dirs = all_dirs[:15]
            else:
                project_dirs = []

        for pd in project_dirs:
            native = scan_claude_sessions(pd, limit=60)
            for sid, info in native.items():
                if sid not in seen:
                    seen[sid] = info

        # 1) Job meta 파일에서 보강
        if LOGS_DIR.exists():
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

                status = meta.get("STATUS", "unknown")
                if status == "running" and meta.get("PID"):
                    try:
                        os.kill(int(meta["PID"]), 0)
                    except (ProcessLookupError, ValueError, OSError):
                        status = "done"

                job_id = meta.get("JOB_ID", "")
                cost_usd = None
                if status in ("done", "failed"):
                    out_file = LOGS_DIR / f"job_{job_id}.out"
                    if out_file.exists():
                        try:
                            for line in open(out_file, "r"):
                                try:
                                    obj = json.loads(line.strip())
                                    if obj.get("type") == "result":
                                        cost_usd = obj.get("total_cost_usd")
                                except json.JSONDecodeError:
                                    continue
                        except OSError:
                            pass

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

        # 2) history.log 보충
        history_file = SESSIONS_DIR / "history.log"
        if history_file.exists():
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

        # cwd 필터 적용
        if filter_cwd:
            norm = os.path.normpath(filter_cwd)
            seen = {
                sid: s for sid, s in seen.items()
                if s.get("cwd") and os.path.normpath(s["cwd"]) == norm
            }

        sessions = sorted(seen.values(), key=lambda s: s.get("timestamp") or "", reverse=True)
        self._json_response(sessions[:50])
