"""
Job 관련 HTTP 핸들러 Mixin

포함 엔드포인트:
  - GET  /api/jobs, /api/jobs/:id/result, /api/jobs/:id/stream, /api/jobs/:id/checkpoints
  - GET  /api/session/:id/job
  - POST /api/send
  - POST /api/jobs/:id/rewind
  - DELETE /api/jobs, /api/jobs/:id

참고: /api/upload은 FsHandlerMixin, /api/service/*는 MiscHandlerMixin에 위치
"""

import json
import os
import time
from urllib.parse import urlparse, parse_qs

from config import LOGS_DIR
from utils import parse_meta_file, is_pid_alive, correct_running_status, parse_stream_events

_SSE_HEARTBEAT_SEC = 15   # SSE heartbeat 간격 (초)
_SSE_POLL_SEC = 0.3       # SSE 폴링 간격 (초)


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

    def _handle_delete_job(self, job_id):
        meta_file = LOGS_DIR / f"job_{job_id}.meta"
        out_file = LOGS_DIR / f"job_{job_id}.out"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404, code="JOB_NOT_FOUND")

        meta = parse_meta_file(meta_file)
        if meta and meta.get("STATUS") == "running" and is_pid_alive(meta.get("PID")):
            return self._error_response("실행 중인 작업은 삭제할 수 없습니다", 409, code="JOB_RUNNING")

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
            events, new_offset = parse_stream_events(out_file, offset)
            meta = parse_meta_file(meta_file)
            done = meta.get("STATUS", "") in ("done", "failed")
            self._json_response({"events": events, "offset": new_offset, "done": done})
        except OSError as e:
            self._error_response(f"스트림 읽기 실패: {e}", 500, code="STREAM_READ_ERROR")

    def _handle_job_stream_sse(self, job_id):
        """SSE 실시간 스트림 — 이벤트를 push 방식으로 전달한다."""
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
        last_activity = time.time()

        try:
            while True:
                events, new_offset = parse_stream_events(out_file, offset)
                offset = new_offset

                for evt in events:
                    data = json.dumps(evt, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))

                if events:
                    self.wfile.flush()
                    last_activity = time.time()

                # 작업 완료 확인
                meta = parse_meta_file(meta_file)
                status = correct_running_status(meta)

                if status in ("done", "failed"):
                    # 최종 이벤트 한 번 더 수집
                    final_events, _ = parse_stream_events(out_file, offset)
                    for evt in final_events:
                        data = json.dumps(evt, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.write(f"event: done\ndata: {{\"status\":\"{status}\"}}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    break

                # Heartbeat — 일정 시간 동안 이벤트 없으면 keepalive 전송
                now = time.time()
                if now - last_activity > _SSE_HEARTBEAT_SEC:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_activity = now

                time.sleep(_SSE_POLL_SEC)

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
