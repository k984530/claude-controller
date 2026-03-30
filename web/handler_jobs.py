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

    def _handle_jobs(self, cwd_filter=None, page=1, limit=10):
        all_jobs = self._jobs_mod().get_all_jobs(cwd_filter=cwd_filter)
        total = len(all_jobs)
        # limit=0 → 전체 반환 (프론트엔드 그룹 뷰에서 자체 페이지네이션 사용)
        if limit <= 0:
            self._json_response({
                "jobs": all_jobs,
                "total": total,
                "page": 1,
                "limit": total or 1,
                "pages": 1,
            })
            return
        page = max(1, page)
        limit = max(1, min(limit, 500))
        pages = max(1, (total + limit - 1) // limit)
        page = min(page, pages)
        start = (page - 1) * limit
        self._json_response({
            "jobs": all_jobs[start:start + limit],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        })

    def _handle_job_result(self, job_id):
        result, err = self._jobs_mod().get_job_result(job_id)
        if err:
            self._error_response(err, 404, code="JOB_NOT_FOUND")
        else:
            self._json_response(result)

    def _handle_upload(self):
        body = self._read_body()
        data_b64 = body.get("data", "")
        filename = body.get("filename", "file")

        if not data_b64:
            return self._error_response("data 필드가 필요합니다", code="MISSING_FIELD")
        if "," in data_b64:
            data_b64 = data_b64.split(",", 1)[1]

        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            return self._error_response("잘못된 base64 데이터", code="INVALID_DATA")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTS:
            return self._error_response(
                f"허용되지 않는 파일 형식입니다: {ext or '(확장자 없음)'}",
                400, code="INVALID_FILE_TYPE")
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
            return self._error_response("prompt 필드가 필요합니다", code="MISSING_FIELD")

        # depends_on: 선행 작업 ID 목록 (예: [42, 43] 또는 "42,43")
        depends_on = body.get("depends_on")
        if isinstance(depends_on, str):
            depends_on = [d.strip() for d in depends_on.split(",") if d.strip()]

        # origin: 작업 출처 (스킬/파이프라인 등)
        origin = body.get("origin") or None

        result, err = self._jobs_mod().send_to_fifo(
            prompt,
            cwd=body.get("cwd") or None,
            job_id=body.get("id") or None,
            images=body.get("images") or None,
            session=body.get("session") or None,
            depends_on=depends_on or None,
            system_prompt=body.get("system_prompt") or None,
            origin=origin,
        )
        if err:
            self._error_response(err, 502, code="SEND_FAILED")
        else:
            self._json_response(result, 201)

    def _handle_service_start(self):
        ok, _ = self._jobs_mod().start_controller_service()
        if ok:
            self._json_response({"started": True})
        else:
            self._error_response("서비스 시작 실패", 500, code="SERVICE_START_FAILED")

    def _handle_service_stop(self):
        ok, err = self._jobs_mod().stop_controller_service()
        if ok:
            self._json_response({"stopped": True})
        else:
            self._error_response(err or "서비스 종료 실패", 500, code="SERVICE_STOP_FAILED")

    def _handle_delete_job(self, job_id):
        meta_file = LOGS_DIR / f"job_{job_id}.meta"
        out_file = LOGS_DIR / f"job_{job_id}.out"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404, code="JOB_NOT_FOUND")

        meta = parse_meta_file(meta_file)
        if meta and meta.get("STATUS") == "running":
            pid = meta.get("PID")
            if pid:
                try:
                    os.kill(int(pid), 0)
                    return self._error_response("실행 중인 작업은 삭제할 수 없습니다", 409, code="JOB_RUNNING")
                except (ProcessLookupError, ValueError, OSError):
                    pass

        try:
            if meta_file.exists():
                meta_file.unlink()
            if out_file.exists():
                out_file.unlink()
            self._json_response({"deleted": True, "job_id": job_id})
        except OSError as e:
            self._error_response(f"삭제 실패: {e}", 500, code="DELETE_FAILED")

    def _handle_delete_completed_jobs(self):
        deleted = []
        for mf in list(LOGS_DIR.glob("job_*.meta")):
            meta = parse_meta_file(mf)
            if not meta:
                continue
            status = meta.get("STATUS", "")
            if status in ("done", "failed"):
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

    @staticmethod
    def _parse_stream_events(out_file, offset):
        """out 파일에서 offset 이후의 스트림 이벤트를 파싱한다. (events, new_offset) 반환."""
        events = []
        new_offset = offset
        if not out_file.exists():
            return events, new_offset
        try:
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
                            result_evt = {
                                "type": "result",
                                "result": evt.get("result", ""),
                                "cost_usd": evt.get("total_cost_usd"),
                                "duration_ms": evt.get("duration_ms"),
                                "is_error": evt.get("is_error", False),
                                "session_id": evt.get("session_id", "")
                            }
                            if result_evt["is_error"]:
                                from error_classify import classify_error
                                result_evt["user_error"] = classify_error(evt.get("result", ""))
                            events.append(result_evt)
                    except json.JSONDecodeError:
                        continue
                new_offset = f.tell()
        except OSError:
            pass
        return events, new_offset

    def _handle_job_stream(self, job_id):
        # SSE content negotiation — Accept 헤더로 분기
        accept = self.headers.get("Accept", "")
        if "text/event-stream" in accept:
            return self._handle_job_stream_sse(job_id)

        out_file = LOGS_DIR / f"job_{job_id}.out"
        meta_file = LOGS_DIR / f"job_{job_id}.meta"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404, code="JOB_NOT_FOUND")

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        offset = self._safe_int(qs.get("offset", [0])[0], 0)

        if not out_file.exists():
            return self._json_response({"events": [], "offset": 0, "done": False})

        try:
            events, new_offset = self._parse_stream_events(out_file, offset)
            meta = parse_meta_file(meta_file)
            done = meta.get("STATUS", "") in ("done", "failed")
            self._json_response({"events": events, "offset": new_offset, "done": done})
        except OSError as e:
            self._error_response(f"스트림 읽기 실패: {e}", 500, code="STREAM_READ_ERROR")

    def _handle_job_stream_sse(self, job_id):
        """SSE 실시간 스트림 — 이벤트를 push 방식으로 전달한다."""
        import time as _time

        out_file = LOGS_DIR / f"job_{job_id}.out"
        meta_file = LOGS_DIR / f"job_{job_id}.meta"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404, code="JOB_NOT_FOUND")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self._set_cors_headers()
        self.end_headers()

        offset = 0
        last_activity = _time.time()

        try:
            while True:
                events, new_offset = self._parse_stream_events(out_file, offset)
                offset = new_offset

                for evt in events:
                    data = json.dumps(evt, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))

                if events:
                    self.wfile.flush()
                    last_activity = _time.time()

                # 작업 완료 확인
                meta = parse_meta_file(meta_file)
                status = meta.get("STATUS", "")
                if status == "running" and meta.get("PID"):
                    try:
                        os.kill(int(meta["PID"]), 0)
                    except (ProcessLookupError, ValueError, OSError):
                        status = "done"

                if status in ("done", "failed"):
                    # 최종 이벤트 한 번 더 수집
                    final_events, _ = self._parse_stream_events(out_file, offset)
                    for evt in final_events:
                        data = json.dumps(evt, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.write(f"event: done\ndata: {{\"status\":\"{status}\"}}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    break

                # Heartbeat — 15초 동안 이벤트 없으면 keepalive 전송
                now = _time.time()
                if now - last_activity > 15:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_activity = now

                _time.sleep(0.3)

        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # 클라이언트 연결 끊김

    def _handle_job_checkpoints(self, job_id):
        checkpoints, err = self._ckpt_mod().get_job_checkpoints(job_id)
        if err:
            self._error_response(err, 404, code="JOB_NOT_FOUND")
        else:
            self._json_response(checkpoints)

    def _handle_job_by_session(self, session_id):
        jobs = self._jobs_mod().get_all_jobs()
        matched = [j for j in jobs if j.get("session_id") == session_id]
        if not matched:
            return self._error_response(
                f"Session ID '{session_id[:8]}...'에 해당하는 작업을 찾을 수 없습니다", 404, code="SESSION_NOT_FOUND")
        self._json_response(matched[0])

    def _handle_job_diff(self, job_id):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        from_hash = qs.get("from", [""])[0].strip()
        to_hash = qs.get("to", [""])[0].strip()

        if not from_hash:
            return self._error_response("from 파라미터가 필요합니다", code="MISSING_FIELD")

        result, err = self._ckpt_mod().diff_checkpoints(job_id, from_hash, to_hash or None)
        if err:
            status = 404 if "찾을 수 없습니다" in err else 500
            self._error_response(err, status, code="DIFF_FAILED")
        else:
            self._json_response(result)

    def _handle_job_rewind(self, job_id):
        body = self._read_body()
        checkpoint_hash = body.get("checkpoint", "").strip()
        new_prompt = body.get("prompt", "").strip()

        if not checkpoint_hash:
            return self._error_response("checkpoint 필드가 필요합니다", code="MISSING_FIELD")
        if not new_prompt:
            return self._error_response("prompt 필드가 필요합니다", code="MISSING_FIELD")

        result, err = self._ckpt_mod().rewind_job(job_id, checkpoint_hash, new_prompt)
        if err:
            if "찾을 수 없습니다" in err:
                self._error_response(err, 400, code="CHECKPOINT_NOT_FOUND")
            else:
                self._error_response(err, 500, code="REWIND_FAILED")
        else:
            self._json_response(result, 201)

    def _handle_results(self, parsed):
        qs = parse_qs(parsed.query)
        origin_type = qs.get("origin_type", [None])[0]
        origin_id = qs.get("origin_id", [None])[0]
        limit = self._safe_int(qs.get("limit", [20])[0], 20)
        results = self._jobs_mod().get_results(
            origin_type=origin_type, origin_id=origin_id, limit=limit,
        )
        self._json_response(results)
