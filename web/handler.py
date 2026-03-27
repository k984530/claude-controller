"""
Controller Service — HTTP REST API 핸들러

보안 계층:
  1. Host 헤더 검증 — DNS Rebinding 방지
  2. Origin 검증 — CORS를 허용된 출처로 제한
  3. 토큰 인증 — API 요청마다 Authorization 헤더 필수
"""

import base64
import http.server
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, parse_qs

from config import (
    STATIC_DIR, LOGS_DIR, UPLOADS_DIR, DATA_DIR,
    RECENT_DIRS_FILE, SETTINGS_FILE, SESSIONS_DIR,
    CLAUDE_PROJECTS_DIR, FIFO_PATH,
    ALLOWED_ORIGINS, ALLOWED_HOSTS,
    AUTH_REQUIRED, AUTH_EXEMPT_PREFIXES, AUTH_EXEMPT_PATHS,
)
from utils import parse_meta_file, is_service_running, cwd_to_project_dir, scan_claude_sessions
from jobs import get_all_jobs, get_job_result, send_to_fifo, start_controller_service, stop_controller_service
from checkpoint import get_job_checkpoints, rewind_job
from auth import verify_token, get_token


# MIME 타입 맵 (업로드/정적 파일 공용)
MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".json": "application/json", ".xml": "application/xml",
    ".yaml": "text/yaml", ".yml": "text/yaml", ".toml": "text/plain",
    ".py": "text/x-python", ".js": "application/javascript",
    ".ts": "text/plain", ".jsx": "text/plain", ".tsx": "text/plain",
    ".html": "text/html", ".css": "text/css", ".scss": "text/plain",
    ".sh": "text/x-shellscript", ".bash": "text/x-shellscript",
    ".zsh": "text/plain", ".fish": "text/plain",
    ".c": "text/plain", ".cpp": "text/plain", ".h": "text/plain",
    ".hpp": "text/plain", ".java": "text/plain", ".kt": "text/plain",
    ".go": "text/plain", ".rs": "text/plain", ".rb": "text/plain",
    ".swift": "text/plain", ".m": "text/plain", ".r": "text/plain",
    ".sql": "text/plain", ".graphql": "text/plain",
    ".log": "text/plain", ".env": "text/plain",
    ".conf": "text/plain", ".ini": "text/plain", ".cfg": "text/plain",
    ".pdf": "application/pdf",
    ".doc": "application/msword", ".docx": "application/msword",
    ".xls": "application/vnd.ms-excel", ".xlsx": "application/vnd.ms-excel",
    ".pptx": "application/vnd.ms-powerpoint",
    ".zip": "application/zip", ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".svg": "image/svg+xml", ".ico": "image/x-icon",
}

# 업로드 허용 확장자
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
ALLOWED_UPLOAD_EXTS = IMAGE_EXTS | {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".sh", ".bash", ".zsh", ".fish",
    ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".go", ".rs", ".rb",
    ".swift", ".m", ".r", ".sql", ".graphql",
    ".log", ".env", ".conf", ".ini", ".cfg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx",
    ".zip", ".tar", ".gz",
}


class ControllerHandler(http.server.BaseHTTPRequestHandler):
    """Controller REST API + 정적 파일 서빙 핸들러"""

    def log_message(self, format, *args):
        sys.stderr.write(f"  [{self.log_date_time_string()}] {format % args}\n")

    # ════════════════════════════════════════════════
    #  보안 미들웨어
    # ════════════════════════════════════════════════

    def _get_origin(self):
        """요청의 Origin 헤더를 반환한다."""
        return self.headers.get("Origin", "")

    def _set_cors_headers(self):
        """허용된 Origin만 CORS 응답에 포함한다."""
        origin = self._get_origin()
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif not origin:
            # same-origin 요청 (Origin 헤더 없음) — 로컬 접근 허용
            self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Credentials", "true")

    def _check_host(self) -> bool:
        """Host 헤더를 검증하여 DNS Rebinding 공격을 차단한다."""
        host = self.headers.get("Host", "")
        # 포트 번호 제거 후 호스트명만 비교
        hostname = host.split(":")[0] if ":" in host else host
        if hostname not in ALLOWED_HOSTS:
            self._send_forbidden("잘못된 Host 헤더")
            return False
        return True

    def _check_auth(self, path: str) -> bool:
        """토큰 인증을 검증한다. AUTH_REQUIRED=false면 항상 통과."""
        if not AUTH_REQUIRED:
            return True

        # 정적 파일 및 면제 경로
        if path in AUTH_EXEMPT_PATHS:
            return True
        for prefix in AUTH_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return True

        # Authorization: Bearer <token>
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if verify_token(token):
                return True

        self._send_unauthorized()
        return False

    def _send_forbidden(self, message="Forbidden"):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_unauthorized(self):
        body = json.dumps({"error": "인증이 필요합니다. Authorization 헤더에 토큰을 포함하세요."}, ensure_ascii=False).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", "Bearer")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ════════════════════════════════════════════════
    #  공통 응답 헬퍼
    # ════════════════════════════════════════════════

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._set_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error_response(self, message, status=400):
        self._json_response({"error": message}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _serve_file(self, file_path, base_dir):
        """파일을 읽어 HTTP 응답으로 전송한다. 경로 탈출 방지 포함."""
        try:
            resolved = file_path.resolve()
            if not str(resolved).startswith(str(base_dir.resolve())):
                return self._error_response("접근 거부", 403)
        except (ValueError, OSError):
            return self._error_response("잘못된 경로", 400)

        if not resolved.exists() or not resolved.is_file():
            return self._error_response("파일을 찾을 수 없습니다", 404)

        ext = resolved.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        if mime.startswith("text/") or mime in ("application/json", "application/javascript"):
            mime += "; charset=utf-8"

        try:
            data = resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self._set_cors_headers()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._error_response("파일 읽기 실패", 500)

    # ── OPTIONS (CORS preflight) ──
    def do_OPTIONS(self):
        # preflight는 Host/Auth 검사 면제 (브라우저 자동 요청)
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    # ── GET ──
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # 보안 게이트
        if not self._check_host():
            return
        if not self._check_auth(path):
            return

        if path == "/api/auth/verify":
            return self._handle_auth_verify()

        if path == "/api/status":
            return self._handle_status()
        if path == "/api/jobs":
            return self._handle_jobs()
        if path == "/api/sessions":
            qs = parse_qs(parsed.query)
            filter_cwd = qs.get("cwd", [None])[0]
            return self._handle_sessions(filter_cwd=filter_cwd)
        if path == "/api/config":
            return self._handle_get_config()
        if path == "/api/recent-dirs":
            return self._handle_get_recent_dirs()
        if path == "/api/dirs":
            qs = parse_qs(parsed.query)
            dir_path = qs.get("path", [os.path.expanduser("~")])[0]
            return self._handle_dirs(dir_path)

        match = re.match(r"^/api/jobs/(\w+)/result$", path)
        if match:
            return self._handle_job_result(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)/stream$", path)
        if match:
            return self._handle_job_stream(match.group(1))
        match = re.match(r"^/api/jobs/(\w+)/checkpoints$", path)
        if match:
            return self._handle_job_checkpoints(match.group(1))
        match = re.match(r"^/api/session/([a-f0-9-]+)/job$", path)
        if match:
            return self._handle_job_by_session(match.group(1))
        match = re.match(r"^/uploads/(.+)$", path)
        if match:
            return self._serve_file(UPLOADS_DIR / match.group(1), UPLOADS_DIR)

        # 정적 파일
        self._serve_static(parsed.path)

    # ── POST ──
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # 보안 게이트
        if not self._check_host():
            return
        if not self._check_auth(path):
            return

        if path == "/api/auth/verify":
            return self._handle_auth_verify()

        if path == "/api/send":
            return self._handle_send()
        if path == "/api/upload":
            return self._handle_upload()
        if path == "/api/service/start":
            return self._handle_service_start()
        if path == "/api/service/stop":
            return self._handle_service_stop()
        if path == "/api/config":
            return self._handle_save_config()
        if path == "/api/recent-dirs":
            return self._handle_save_recent_dirs()

        match = re.match(r"^/api/jobs/(\w+)/rewind$", path)
        if match:
            return self._handle_job_rewind(match.group(1))

        self._error_response("알 수 없는 엔드포인트", 404)

    # ── DELETE ──
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # 보안 게이트
        if not self._check_host():
            return
        if not self._check_auth(path):
            return

        match = re.match(r"^/api/jobs/(\w+)$", path)
        if match:
            return self._handle_delete_job(match.group(1))
        if path == "/api/jobs":
            return self._handle_delete_completed_jobs()

        self._error_response("알 수 없는 엔드포인트", 404)

    # ════════════════════════════════════════════════
    #  API 핸들러
    # ════════════════════════════════════════════════

    def _handle_auth_verify(self):
        """POST /api/auth/verify — 토큰 검증 엔드포인트.
        프론트엔드에서 토큰 유효성을 확인할 때 사용한다."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if verify_token(token):
                return self._json_response({"valid": True})
        self._json_response({"valid": False}, 401)

    def _handle_status(self):
        running, _ = is_service_running()
        self._json_response({"running": running, "fifo": str(FIFO_PATH)})

    def _handle_jobs(self):
        self._json_response(get_all_jobs())

    def _handle_job_result(self, job_id):
        result, err = get_job_result(job_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(result)

    def _handle_upload(self):
        body = self._read_body()
        data_b64 = body.get("data", "")
        filename = body.get("filename", "file")

        if not data_b64:
            return self._error_response("data 필드가 필요합니다")
        if "," in data_b64:
            data_b64 = data_b64.split(",", 1)[1]

        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            return self._error_response("잘못된 base64 데이터")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTS:
            ext = ext if ext else ".bin"
        prefix = "img" if ext in IMAGE_EXTS else "file"
        safe_name = f"{prefix}_{int(time.time())}_{os.getpid()}_{id(raw) % 10000}{ext}"

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = UPLOADS_DIR / safe_name
        filepath.write_bytes(raw)

        is_image = ext in IMAGE_EXTS
        self._json_response({
            "path": str(filepath),
            "filename": safe_name,
            "originalName": filename,
            "size": len(raw),
            "isImage": is_image,
        }, 201)

    def _handle_send(self):
        body = self._read_body()
        prompt = body.get("prompt", "").strip()
        if not prompt:
            return self._error_response("prompt 필드가 필요합니다")

        result, err = send_to_fifo(
            prompt,
            cwd=body.get("cwd") or None,
            job_id=body.get("id") or None,
            images=body.get("images") or None,
            session=body.get("session") or None,
        )
        if err:
            self._error_response(err, 502)
        else:
            self._json_response(result, 201)

    def _handle_service_start(self):
        ok, _ = start_controller_service()
        if ok:
            self._json_response({"started": True})
        else:
            self._error_response("서비스 시작 실패", 500)

    def _handle_service_stop(self):
        ok, err = stop_controller_service()
        if ok:
            self._json_response({"stopped": True})
        else:
            self._error_response(err or "서비스 종료 실패", 500)

    def _handle_delete_job(self, job_id):
        meta_file = LOGS_DIR / f"job_{job_id}.meta"
        out_file = LOGS_DIR / f"job_{job_id}.out"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404)

        meta = parse_meta_file(meta_file)
        if meta and meta.get("STATUS") == "running":
            pid = meta.get("PID")
            if pid:
                try:
                    os.kill(int(pid), 0)
                    return self._error_response("실행 중인 작업은 삭제할 수 없습니다", 409)
                except (ProcessLookupError, ValueError, OSError):
                    pass

        try:
            if meta_file.exists():
                meta_file.unlink()
            if out_file.exists():
                out_file.unlink()
            self._json_response({"deleted": True, "job_id": job_id})
        except OSError as e:
            self._error_response(f"삭제 실패: {e}", 500)

    def _handle_delete_completed_jobs(self):
        deleted = []
        for mf in list(LOGS_DIR.glob("job_*.meta")):
            meta = parse_meta_file(mf)
            if not meta:
                continue
            status = meta.get("STATUS", "")
            if status in ("done", "failed"):
                pid = meta.get("PID")
                if pid and status == "running":
                    try:
                        os.kill(int(pid), 0)
                        continue
                    except (ProcessLookupError, ValueError, OSError):
                        pass
                job_id = meta.get("JOB_ID", "")
                out_file = LOGS_DIR / f"job_{job_id}.out"
                try:
                    mf.unlink()
                    if out_file.exists():
                        out_file.unlink()
                    deleted.append(job_id)
                except OSError:
                    pass
        self._json_response({"deleted": deleted, "count": len(deleted)})

    def _handle_job_stream(self, job_id):
        out_file = LOGS_DIR / f"job_{job_id}.out"
        meta_file = LOGS_DIR / f"job_{job_id}.meta"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404)

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        offset = int(qs.get("offset", [0])[0])

        if not out_file.exists():
            return self._json_response({"events": [], "offset": 0, "done": False})

        try:
            with open(out_file, "r") as f:
                f.seek(offset)
                new_data = f.read()
                new_offset = f.tell()

            events = []
            for line in new_data.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                    evt_type = evt.get("type", "")
                    if evt_type == "assistant":
                        msg = evt.get("message", {})
                        content = msg.get("content", [])
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        if text_parts:
                            events.append({"type": "text", "text": "".join(text_parts)})
                        tool_parts = [c for c in content if c.get("type") == "tool_use"]
                        for tp in tool_parts:
                            events.append({
                                "type": "tool_use",
                                "tool": tp.get("name", ""),
                                "input": str(tp.get("input", ""))[:200]
                            })
                    elif evt_type == "result":
                        events.append({
                            "type": "result",
                            "result": evt.get("result", ""),
                            "cost_usd": evt.get("total_cost_usd"),
                            "duration_ms": evt.get("duration_ms"),
                            "is_error": evt.get("is_error", False)
                        })
                except json.JSONDecodeError:
                    continue

            meta = parse_meta_file(meta_file)
            done = meta.get("STATUS", "") in ("done", "failed")

            self._json_response({"events": events, "offset": new_offset, "done": done})
        except OSError as e:
            self._error_response(f"스트림 읽기 실패: {e}", 500)

    def _handle_job_checkpoints(self, job_id):
        checkpoints, err = get_job_checkpoints(job_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(checkpoints)

    def _handle_job_by_session(self, session_id):
        """Session ID로 가장 최근 job을 찾아 반환한다."""
        jobs = get_all_jobs()
        matched = [j for j in jobs if j.get("session_id") == session_id]
        if not matched:
            return self._error_response(
                f"Session ID '{session_id[:8]}...'에 해당하는 작업을 찾을 수 없습니다", 404)
        self._json_response(matched[0])

    def _handle_job_rewind(self, job_id):
        body = self._read_body()
        checkpoint_hash = body.get("checkpoint", "").strip()
        new_prompt = body.get("prompt", "").strip()

        if not checkpoint_hash:
            return self._error_response("checkpoint 필드가 필요합니다")
        if not new_prompt:
            return self._error_response("prompt 필드가 필요합니다")

        result, err = rewind_job(job_id, checkpoint_hash, new_prompt)
        if err:
            self._error_response(err, 400 if "찾을 수 없습니다" in err else 500)
        else:
            self._json_response(result, 201)

    def _handle_sessions(self, filter_cwd=None):
        """Claude Code 네이티브 세션 + history.log + job meta 파일을 합쳐 세션 목록을 반환한다."""
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

    def _handle_get_config(self):
        defaults = {
            "skip_permissions": True,
            "allowed_tools": "Bash,Read,Write,Edit,Glob,Grep,Agent,NotebookEdit,WebFetch,WebSearch",
            "model": "",
            "max_jobs": 10,
            "append_system_prompt": "",
            "target_repo": "",
            "base_branch": "main",
            "checkpoint_interval": 5,
            "locale": "ko",
        }
        try:
            if SETTINGS_FILE.exists():
                saved = json.loads(SETTINGS_FILE.read_text("utf-8"))
                defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
        self._json_response(defaults)

    def _handle_save_config(self):
        body = self._read_body()
        if not body or not isinstance(body, dict):
            return self._error_response("설정 데이터가 필요합니다")

        current = {}
        try:
            if SETTINGS_FILE.exists():
                current = json.loads(SETTINGS_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

        allowed_keys = {
            "skip_permissions", "allowed_tools", "model", "max_jobs",
            "append_system_prompt", "target_repo", "base_branch",
            "checkpoint_interval", "locale",
        }
        for k, v in body.items():
            if k in allowed_keys:
                current[k] = v

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), "utf-8"
            )
            self._json_response({"ok": True, "config": current})
        except OSError as e:
            self._error_response(f"설정 저장 실패: {e}", 500)

    def _handle_get_recent_dirs(self):
        try:
            if RECENT_DIRS_FILE.exists():
                data = json.loads(RECENT_DIRS_FILE.read_text("utf-8"))
            else:
                data = []
            self._json_response(data)
        except (json.JSONDecodeError, OSError):
            self._json_response([])

    def _handle_save_recent_dirs(self):
        body = self._read_body()
        dirs = body.get("dirs")
        if not isinstance(dirs, list):
            return self._error_response("dirs 배열이 필요합니다")
        dirs = [d for d in dirs if isinstance(d, str)][:8]
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            RECENT_DIRS_FILE.write_text(json.dumps(dirs, ensure_ascii=False), "utf-8")
            self._json_response({"ok": True})
        except OSError as e:
            self._error_response(f"저장 실패: {e}", 500)

    def _handle_dirs(self, dir_path):
        try:
            dir_path = os.path.abspath(os.path.expanduser(dir_path))
            if not os.path.isdir(dir_path):
                return self._error_response("디렉토리가 아닙니다", 400)

            entries = []
            try:
                items = sorted(os.listdir(dir_path))
            except PermissionError:
                return self._error_response("접근 권한 없음", 403)

            parent = os.path.dirname(dir_path)
            if parent != dir_path:
                entries.append({"name": "..", "path": parent, "type": "dir"})

            for item in items:
                if item.startswith("."):
                    continue
                full = os.path.join(dir_path, item)
                entry = {"name": item, "path": full}
                if os.path.isdir(full):
                    entry["type"] = "dir"
                else:
                    entry["type"] = "file"
                    try:
                        entry["size"] = os.path.getsize(full)
                    except OSError:
                        entry["size"] = 0
                entries.append(entry)

            self._json_response({"current": dir_path, "entries": entries})
        except Exception as e:
            self._error_response(f"디렉토리 읽기 실패: {e}", 500)

    def _serve_static(self, url_path):
        if url_path in ("/", ""):
            url_path = "/index.html"
        self._serve_file(STATIC_DIR / url_path.lstrip("/"), STATIC_DIR)
