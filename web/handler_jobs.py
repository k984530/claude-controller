"""
Job 관련 HTTP 핸들러 Mixin

포함 엔드포인트:
  - GET  /api/jobs, /api/jobs/:id/result, /api/jobs/:id/stream, /api/jobs/:id/checkpoints
  - GET  /api/session/:id/job
  - POST /api/send, /api/upload, /api/service/start, /api/service/stop
  - POST /api/jobs/:id/rewind
  - DELETE /api/jobs, /api/jobs/:id
"""

import base64
import json
import os
import time
from urllib.parse import urlparse, parse_qs

from config import LOGS_DIR, UPLOADS_DIR
from utils import parse_meta_file

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


class JobHandlerMixin:

    def _handle_jobs(self):
        self._json_response(self._jobs_mod().get_all_jobs())

    def _handle_job_result(self, job_id):
        result, err = self._jobs_mod().get_job_result(job_id)
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

        result, err = self._jobs_mod().send_to_fifo(
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
        ok, _ = self._jobs_mod().start_controller_service()
        if ok:
            self._json_response({"started": True})
        else:
            self._error_response("서비스 시작 실패", 500)

    def _handle_service_stop(self):
        ok, err = self._jobs_mod().stop_controller_service()
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
            events = []
            with open(out_file, "r") as f:
                f.seek(offset)
                for raw_line in f:
                    if '"type":"assistant"' not in raw_line and '"type":"result"' not in raw_line:
                        continue
                    try:
                        evt = json.loads(raw_line)
                        evt_type = evt.get("type", "")
                        if evt_type == "assistant":
                            msg = evt.get("message", {})
                            content = msg.get("content", [])
                            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                            if text_parts:
                                events.append({"type": "text", "text": "".join(text_parts)})
                            for tp in content:
                                if tp.get("type") == "tool_use":
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
                                "is_error": evt.get("is_error", False),
                                "session_id": evt.get("session_id", "")
                            })
                    except json.JSONDecodeError:
                        continue
                new_offset = f.tell()

            meta = parse_meta_file(meta_file)
            done = meta.get("STATUS", "") in ("done", "failed")
            self._json_response({"events": events, "offset": new_offset, "done": done})
        except OSError as e:
            self._error_response(f"스트림 읽기 실패: {e}", 500)

    def _handle_job_checkpoints(self, job_id):
        checkpoints, err = self._ckpt_mod().get_job_checkpoints(job_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(checkpoints)

    def _handle_job_by_session(self, session_id):
        jobs = self._jobs_mod().get_all_jobs()
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

        result, err = self._ckpt_mod().rewind_job(job_id, checkpoint_hash, new_prompt)
        if err:
            self._error_response(err, 400 if "찾을 수 없습니다" in err else 500)
        else:
            self._json_response(result, 201)
