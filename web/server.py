#!/usr/bin/env python3
"""
Controller Service — 웹 GUI 서버
Python 표준 라이브러리만 사용하는 경량 HTTP + REST API 서버
"""

import base64
import http.server
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from functools import partial

# ── 경로 설정 ──────────────────────────────────────────────────
WEB_DIR = Path(__file__).resolve().parent
CONTROLLER_DIR = WEB_DIR.parent
STATIC_DIR = WEB_DIR / "static"
FIFO_PATH = CONTROLLER_DIR / "queue" / "controller.pipe"
PID_FILE = CONTROLLER_DIR / "service" / "controller.pid"
LOGS_DIR = CONTROLLER_DIR / "logs"
UPLOADS_DIR = CONTROLLER_DIR / "uploads"
DATA_DIR = CONTROLLER_DIR / "data"
RECENT_DIRS_FILE = DATA_DIR / "recent_dirs.json"
SERVICE_SCRIPT = CONTROLLER_DIR / "service" / "controller.sh"

# ── 포트 설정 ──────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8420))


# ── 유틸리티 함수 ──────────────────────────────────────────────

def parse_meta_file(filepath):
    """
    쉘 source 가능한 .meta 파일을 딕셔너리로 파싱한다.
    KEY=VALUE 또는 KEY='VALUE' 형식을 처리한다.
    """
    data = {}
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.match(r"^(\w+)=(.*)$", line)
                if match:
                    key = match.group(1)
                    val = match.group(2)
                    # 따옴표 제거 (작은따옴표 또는 큰따옴표)
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                        val = val[1:-1]
                    data[key] = val
    except (OSError, IOError):
        pass
    return data


def is_service_running():
    """서비스 PID 파일을 읽고 프로세스 생존 여부를 확인한다."""
    if not PID_FILE.exists():
        return False, None
    try:
        pid = int(PID_FILE.read_text().strip())
        # kill -0 으로 프로세스 존재 여부 확인
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False, None


def get_all_jobs():
    """logs/ 디렉토리의 모든 .meta 파일을 파싱하여 작업 목록을 반환한다."""
    jobs = []
    if not LOGS_DIR.exists():
        return jobs

    meta_files = sorted(LOGS_DIR.glob("job_*.meta"),
                        key=lambda f: int(f.stem.split("_")[1]),
                        reverse=True)
    for mf in meta_files:
        meta = parse_meta_file(mf)
        if not meta:
            continue

        # running 상태이지만 프로세스가 죽었으면 done 으로 보정
        if meta.get("STATUS") == "running" and meta.get("PID"):
            try:
                os.kill(int(meta["PID"]), 0)
            except (ProcessLookupError, ValueError, OSError):
                meta["STATUS"] = "done"

        # 완료된 작업은 result도 함께 추출
        result_text = None
        cost_usd = None
        duration_ms = None
        job_id_str = meta.get("JOB_ID", "")
        if meta.get("STATUS") in ("done", "failed"):
            out_file = LOGS_DIR / f"job_{job_id_str}.out"
            if out_file.exists():
                try:
                    with open(out_file, "r") as f:
                        for line in f:
                            try:
                                obj = json.loads(line.strip())
                                if obj.get("type") == "result":
                                    result_text = obj.get("result", "")
                                    cost_usd = obj.get("total_cost_usd")
                                    duration_ms = obj.get("duration_ms")
                            except json.JSONDecodeError:
                                continue
                    # fallback: 단일 JSON
                    if result_text is None:
                        out_file.seek(0) if hasattr(out_file, 'seek') else None
                        try:
                            data = json.loads(out_file.read_text())
                            result_text = data.get("result", "")
                            cost_usd = data.get("total_cost_usd")
                            duration_ms = data.get("duration_ms")
                        except (json.JSONDecodeError, OSError):
                            pass
                except OSError:
                    pass

        jobs.append({
            "job_id":     job_id_str,
            "status":     meta.get("STATUS", "unknown"),
            "pid":        meta.get("PID", "") or None,
            "prompt":     meta.get("PROMPT", ""),
            "created_at": meta.get("CREATED_AT", ""),
            "session_id": meta.get("SESSION_ID", "") or None,
            "uuid":       meta.get("UUID", "") or None,
            "cwd":        meta.get("CWD", "") or None,
            "result":     result_text,
            "cost_usd":   cost_usd,
            "duration_ms": duration_ms,
        })
    return jobs


def get_job_result(job_id):
    """작업 결과(.out 파일)에서 result 필드를 추출한다."""
    out_file = LOGS_DIR / f"job_{job_id}.out"
    meta_file = LOGS_DIR / f"job_{job_id}.meta"

    if not meta_file.exists():
        return None, "작업을 찾을 수 없습니다"

    meta = parse_meta_file(meta_file)
    if meta.get("STATUS") == "running":
        return {"status": "running", "result": None}, None

    if not out_file.exists():
        return None, "출력 파일이 없습니다"

    try:
        with open(out_file, "r") as f:
            content = f.read()

        # stream-json: 줄 단위 JSON에서 type=result 라인 찾기
        result_data = None
        for line in content.strip().split("\n"):
            try:
                obj = json.loads(line)
                if obj.get("type") == "result":
                    result_data = obj
            except json.JSONDecodeError:
                continue

        if result_data:
            return {
                "status":     meta.get("STATUS", "unknown"),
                "result":     result_data.get("result"),
                "cost_usd":   result_data.get("total_cost_usd"),
                "duration_ms": result_data.get("duration_ms"),
                "session_id": result_data.get("session_id"),
                "is_error":   result_data.get("is_error", False),
            }, None

        # fallback: 단일 JSON 형식 (이전 json 모드 호환)
        try:
            data = json.loads(content)
            return {
                "status":     meta.get("STATUS", "unknown"),
                "result":     data.get("result"),
                "cost_usd":   data.get("total_cost_usd"),
                "duration_ms": data.get("duration_ms"),
                "session_id": data.get("session_id"),
                "is_error":   data.get("is_error", False),
            }, None
        except json.JSONDecodeError:
            pass

        return {"status": meta.get("STATUS", "unknown"), "result": content[:2000]}, None
    except OSError as e:
        return None, f"결과 파싱 실패: {e}"


def send_to_fifo(prompt, cwd=None, job_id=None, images=None, session=None):
    """FIFO 파이프에 JSON 메시지를 전송한다."""
    if not FIFO_PATH.exists():
        return None, "FIFO 파이프가 존재하지 않습니다. 서비스가 실행 중인지 확인하세요."

    if not job_id:
        job_id = f"{int(time.time())}-web-{os.getpid()}-{id(prompt) % 10000}"

    payload = {"id": job_id, "prompt": prompt}
    if cwd:
        payload["cwd"] = cwd
    if images:
        payload["images"] = images
    if session:
        payload["session"] = session

    try:
        # O_NONBLOCK 으로 열어서 수신자 없을 때 블로킹 방지
        fd = os.open(str(FIFO_PATH), os.O_WRONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return {"job_id": job_id, "prompt": prompt, "cwd": cwd}, None
    except OSError as e:
        return None, f"FIFO 전송 실패: {e}"


def start_controller_service():
    """컨트롤러 서비스를 백그라운드로 시작한다."""
    running, pid = is_service_running()
    if running:
        return True, pid

    if not SERVICE_SCRIPT.exists():
        return False, None

    # nohup 으로 백그라운드 실행, stdout/stderr 를 서비스 로그로 리다이렉트
    log_file = LOGS_DIR / "service.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    subprocess.Popen(
        ["bash", str(SERVICE_SCRIPT), "start"],
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # 부모 프로세스와 세션 분리
        cwd=str(CONTROLLER_DIR),
    )

    # 서비스 기동 대기 (최대 3초)
    for _ in range(30):
        time.sleep(0.1)
        running, pid = is_service_running()
        if running:
            return True, pid

    return False, None


def stop_controller_service():
    """컨트롤러 서비스를 종료한다."""
    running, pid = is_service_running()
    if not running:
        return False, "서비스가 실행 중이 아닙니다"

    try:
        os.kill(pid, signal.SIGTERM)
        return True, None
    except OSError as e:
        return False, f"종료 실패: {e}"


# ── HTTP 핸들러 ────────────────────────────────────────────────

class ControllerHandler(http.server.BaseHTTPRequestHandler):
    """Controller REST API + 정적 파일 서빙 핸들러"""

    # ── 로그 포맷 간소화 ──────────────────────────────────────
    def log_message(self, format, *args):
        sys.stderr.write(f"  [{self.log_date_time_string()}] {format % args}\n")

    # ── CORS 헤더 공통 삽입 ───────────────────────────────────
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    # ── JSON 응답 전송 ────────────────────────────────────────
    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._set_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── 에러 응답 ─────────────────────────────────────────────
    def _error_response(self, message, status=400):
        self._json_response({"error": message}, status)

    # ── 요청 본문 읽기 ────────────────────────────────────────
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # ── OPTIONS (CORS preflight) ──────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    # ── GET ────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # --- API 라우팅 ---
        if path == "/api/status":
            return self._handle_status()

        if path == "/api/jobs":
            return self._handle_jobs()

        # /api/jobs/<id>/result
        match = re.match(r"^/api/jobs/(\w+)/result$", path)
        if match:
            return self._handle_job_result(match.group(1))

        # /api/jobs/<id>/stream — 실시간 스트리밍 이벤트
        match = re.match(r"^/api/jobs/(\w+)/stream$", path)
        if match:
            return self._handle_job_stream(match.group(1))

        if path == "/api/recent-dirs":
            return self._handle_get_recent_dirs()

        if path == "/api/dirs":
            qs = parse_qs(parsed.query)
            dir_path = qs.get("path", [os.path.expanduser("~")])[0]
            return self._handle_dirs(dir_path)

        # --- 업로드 이미지 서빙 ---
        match = re.match(r"^/uploads/(.+)$", path)
        if match:
            return self._serve_upload(match.group(1))

        # --- 정적 파일 서빙 ---
        self._serve_static(parsed.path)

    # ── POST ───────────────────────────────────────────────────
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/send":
            return self._handle_send()

        if path == "/api/upload":
            return self._handle_upload()

        if path == "/api/service/start":
            return self._handle_service_start()

        if path == "/api/service/stop":
            return self._handle_service_stop()

        if path == "/api/recent-dirs":
            return self._handle_save_recent_dirs()

        self._error_response("알 수 없는 엔드포인트", 404)

    # ── DELETE ─────────────────────────────────────────────────
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # DELETE /api/jobs/<id>
        match = re.match(r"^/api/jobs/(\w+)$", path)
        if match:
            return self._handle_delete_job(match.group(1))

        # DELETE /api/jobs — 완료된 작업 일괄 삭제
        if path == "/api/jobs":
            return self._handle_delete_completed_jobs()

        self._error_response("알 수 없는 엔드포인트", 404)

    # ── API 핸들러: GET /api/status ───────────────────────────
    def _handle_status(self):
        running, pid = is_service_running()
        self._json_response({
            "running": running,
            "pid":     pid,
            "fifo":    str(FIFO_PATH),
        })

    # ── API 핸들러: GET /api/jobs ─────────────────────────────
    def _handle_jobs(self):
        jobs = get_all_jobs()
        self._json_response(jobs)

    # ── API 핸들러: GET /api/jobs/<id>/result ─────────────────
    def _handle_job_result(self, job_id):
        result, err = get_job_result(job_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(result)

    # ── API 핸들러: POST /api/upload ──────────────────────────
    def _handle_upload(self):
        """base64 인코딩된 파일을 수신하여 uploads/ 디렉토리에 저장한다."""
        body = self._read_body()
        data_b64 = body.get("data", "")
        filename = body.get("filename", "file")

        if not data_b64:
            return self._error_response("data 필드가 필요합니다")

        # Data URL 접두사 제거 (data:image/png;base64,... → ...)
        if "," in data_b64:
            data_b64 = data_b64.split(",", 1)[1]

        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            return self._error_response("잘못된 base64 데이터")

        # 안전한 파일명 생성 — 허용 확장자 화이트리스트
        ext = os.path.splitext(filename)[1].lower()
        IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        ALLOWED_EXTS = IMAGE_EXTS | {
            ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml",
            ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
            ".sh", ".bash", ".zsh", ".fish",
            ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".go", ".rs", ".rb",
            ".swift", ".m", ".r", ".sql", ".graphql",
            ".log", ".env", ".conf", ".ini", ".cfg",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx",
            ".zip", ".tar", ".gz",
        }
        if ext not in ALLOWED_EXTS:
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

    # ── API 핸들러: POST /api/send ────────────────────────────
    def _handle_send(self):
        body = self._read_body()
        prompt = body.get("prompt", "").strip()
        if not prompt:
            return self._error_response("prompt 필드가 필요합니다")

        cwd = body.get("cwd") or None
        job_id = body.get("id") or None
        images = body.get("images") or None
        session = body.get("session") or None

        result, err = send_to_fifo(prompt, cwd=cwd, job_id=job_id, images=images, session=session)
        if err:
            self._error_response(err, 502)
        else:
            self._json_response(result, 201)

    # ── API 핸들러: POST /api/service/start ───────────────────
    def _handle_service_start(self):
        ok, pid = start_controller_service()
        if ok:
            self._json_response({"started": True, "pid": pid})
        else:
            self._error_response("서비스 시작 실패", 500)

    # ── API 핸들러: POST /api/service/stop ────────────────────
    def _handle_service_stop(self):
        ok, err = stop_controller_service()
        if ok:
            self._json_response({"stopped": True})
        else:
            self._error_response(err or "서비스 종료 실패", 500)

    # ── API 핸들러: DELETE /api/jobs/<id> ────────────────────────
    def _handle_delete_job(self, job_id):
        """개별 작업 삭제 (meta + out 파일 제거)"""
        meta_file = LOGS_DIR / f"job_{job_id}.meta"
        out_file = LOGS_DIR / f"job_{job_id}.out"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404)

        # running 상태인 작업은 삭제 금지
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

    # ── API 핸들러: DELETE /api/jobs ───────────────────────────
    def _handle_delete_completed_jobs(self):
        """완료/실패 상태의 모든 작업 일괄 삭제"""
        deleted = []
        for mf in list(LOGS_DIR.glob("job_*.meta")):
            meta = parse_meta_file(mf)
            if not meta:
                continue
            status = meta.get("STATUS", "")
            if status in ("done", "failed"):
                # 프로세스가 실제로 죽었는지 확인
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

    # ── API 핸들러: GET /api/jobs/<id>/stream ──────────────────
    def _handle_job_stream(self, job_id):
        """stream-json .out 파일에서 실시간 이벤트를 반환한다."""
        out_file = LOGS_DIR / f"job_{job_id}.out"
        meta_file = LOGS_DIR / f"job_{job_id}.meta"

        if not meta_file.exists():
            return self._error_response("작업을 찾을 수 없습니다", 404)

        # offset 파라미터: 클라이언트가 이미 받은 바이트 수
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
                    # 유용한 이벤트만 필터링
                    if evt_type == "assistant":
                        # 텍스트 응답 추출
                        msg = evt.get("message", {})
                        content = msg.get("content", [])
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        if text_parts:
                            events.append({"type": "text", "text": "".join(text_parts)})
                        # 도구 사용 추출
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

            # 완료 여부
            meta = parse_meta_file(meta_file)
            done = meta.get("STATUS", "") in ("done", "failed")

            self._json_response({
                "events": events,
                "offset": new_offset,
                "done": done
            })
        except OSError as e:
            self._error_response(f"스트림 읽기 실패: {e}", 500)

    # ── API 핸들러: GET /api/recent-dirs ──────────────────────
    def _handle_get_recent_dirs(self):
        """저장된 최근 디렉토리 목록을 반환한다."""
        try:
            if RECENT_DIRS_FILE.exists():
                data = json.loads(RECENT_DIRS_FILE.read_text("utf-8"))
            else:
                data = []
            self._json_response(data)
        except (json.JSONDecodeError, OSError):
            self._json_response([])

    # ── API 핸들러: POST /api/recent-dirs ─────────────────────
    def _handle_save_recent_dirs(self):
        """최근 디렉토리 목록을 파일에 저장한다."""
        body = self._read_body()
        dirs = body.get("dirs")
        if not isinstance(dirs, list):
            return self._error_response("dirs 배열이 필요합니다")
        # 문자열만 허용, 최대 8개
        dirs = [d for d in dirs if isinstance(d, str)][:8]
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            RECENT_DIRS_FILE.write_text(json.dumps(dirs, ensure_ascii=False), "utf-8")
            self._json_response({"ok": True})
        except OSError as e:
            self._error_response(f"저장 실패: {e}", 500)

    # ── API 핸들러: GET /api/dirs?path=... ─────────────────────
    def _handle_dirs(self, dir_path):
        """디렉토리 내용을 반환한다. 사이드바 파일 탐색기용."""
        try:
            dir_path = os.path.abspath(os.path.expanduser(dir_path))
            if not os.path.isdir(dir_path):
                return self._error_response("디렉토리가 아닙니다", 400)

            entries = []
            try:
                items = sorted(os.listdir(dir_path))
            except PermissionError:
                return self._error_response("접근 권한 없음", 403)

            # 상위 디렉토리
            parent = os.path.dirname(dir_path)
            if parent != dir_path:
                entries.append({"name": "..", "path": parent, "type": "dir"})

            for item in items:
                if item.startswith("."):
                    continue  # 숨김 파일 제외
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

            self._json_response({
                "current": dir_path,
                "entries": entries
            })
        except Exception as e:
            self._error_response(f"디렉토리 읽기 실패: {e}", 500)

    # ── 업로드 이미지 서빙 ──────────────────────────────────────
    def _serve_upload(self, filename):
        """uploads/ 디렉토리의 이미지 파일을 서빙한다."""
        try:
            file_path = (UPLOADS_DIR / filename).resolve()
            if not str(file_path).startswith(str(UPLOADS_DIR.resolve())):
                return self._error_response("접근 거부", 403)
        except (ValueError, OSError):
            return self._error_response("잘못된 경로", 400)

        if not file_path.exists() or not file_path.is_file():
            return self._error_response("파일을 찾을 수 없습니다", 404)

        ext = file_path.suffix.lower()
        mime = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
            ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
            ".json": "application/json", ".xml": "application/xml",
            ".yaml": "text/yaml", ".yml": "text/yaml", ".toml": "text/plain",
            ".py": "text/x-python", ".js": "text/javascript", ".ts": "text/plain",
            ".html": "text/html", ".css": "text/css",
            ".sh": "text/x-shellscript", ".log": "text/plain",
            ".pdf": "application/pdf",
            ".zip": "application/zip", ".gz": "application/gzip",
        }.get(ext, "application/octet-stream")

        try:
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self._set_cors_headers()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._error_response("파일 읽기 실패", 500)

    # ── 정적 파일 서빙 ────────────────────────────────────────
    def _serve_static(self, url_path):
        # URL 경로를 파일시스템 경로로 변환
        if url_path in ("/", ""):
            url_path = "/index.html"

        # 경로 탐색 공격 방지 — resolve 후 STATIC_DIR 하위인지 확인
        try:
            file_path = (STATIC_DIR / url_path.lstrip("/")).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())):
                self._error_response("접근 거부", 403)
                return
        except (ValueError, OSError):
            self._error_response("잘못된 경로", 400)
            return

        if not file_path.exists() or not file_path.is_file():
            self._error_response("파일을 찾을 수 없습니다", 404)
            return

        # MIME 타입 결정
        ext = file_path.suffix.lower()
        mime_map = {
            ".html": "text/html; charset=utf-8",
            ".css":  "text/css; charset=utf-8",
            ".js":   "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png":  "image/png",
            ".jpg":  "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif":  "image/gif",
            ".svg":  "image/svg+xml",
            ".ico":  "image/x-icon",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
            ".ttf":  "font/ttf",
        }
        content_type = mime_map.get(ext, "application/octet-stream")

        try:
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self._set_cors_headers()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._error_response("파일 읽기 실패", 500)


# ── 서버 기동 ──────────────────────────────────────────────────

def main():
    # 서비스 자동 시작 시도
    running, pid = is_service_running()
    service_status = f"실행 중 (PID: {pid})" if running else "중지됨"

    if not running:
        print("  [자동 시작] 컨트롤러 서비스를 시작합니다...")
        ok, pid = start_controller_service()
        if ok:
            service_status = f"시작됨 (PID: {pid})"
            print(f"  [완료] 서비스 시작 성공 (PID: {pid})")
        else:
            service_status = "시작 실패"
            print("  [경고] 서비스 자동 시작 실패. 수동으로 시작하세요.")

    # HTTP 서버 기동
    handler = ControllerHandler
    server = http.server.HTTPServer(("0.0.0.0", PORT), handler)

    # 배너 출력
    print(f"""
============================================================
  Controller Web Server
============================================================
  URL       : http://localhost:{PORT}
  정적 파일 : {STATIC_DIR}
  서비스    : {service_status}
  FIFO      : {FIFO_PATH}
------------------------------------------------------------
  [대기 중] 요청을 수신합니다... (Ctrl+C 로 종료)
============================================================
""")

    # 시그널 핸들러 등록 (깔끔한 종료)
    def _shutdown(signum, frame):
        print("\n  [종료] 웹 서버를 종료합니다...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [종료] 웹 서버를 종료합니다...")
        server.server_close()


if __name__ == "__main__":
    main()
