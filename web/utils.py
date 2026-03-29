"""
Controller Service — 유틸리티 함수
"""

import json
import os
import re
from pathlib import Path

import time

from config import PID_FILE

_id_counter = 0


def generate_id(prefix: str = "") -> str:
    """고유 ID를 생성한다. prefix가 있으면 '{prefix}-' 형태로 붙는다."""
    global _id_counter
    _id_counter += 1
    base = f"{int(time.time())}-{os.getpid() % 10000}-{_id_counter}"
    return f"{prefix}-{base}" if prefix else base


def atomic_json_save(filepath: Path, data, ensure_dir: bool = True):
    """원자적 JSON 파일 쓰기: tmp 파일에 쓴 뒤 rename으로 교체.

    Args:
        filepath: 저장할 파일 경로
        data: JSON 직렬화 가능한 데이터
        ensure_dir: True이면 부모 디렉토리를 자동 생성
    """
    if ensure_dir:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp = filepath.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(str(tmp), str(filepath))


def parse_meta_file(filepath):
    """쉘 source 가능한 .meta 파일을 딕셔너리로 파싱한다."""
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
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False, None


def cwd_to_project_dir(cwd: str) -> str:
    """CWD 경로를 Claude Code 프로젝트 디렉토리 이름으로 변환한다."""
    return re.sub(r'[^a-zA-Z0-9]', '-', os.path.normpath(cwd))


def scan_claude_sessions(project_dir: Path, limit=100):
    """Claude Code 프로젝트 디렉토리에서 세션 JSONL 파일을 스캔한다.
    각 파일에서 첫 user 메시지(프롬프트/CWD/타임스탬프)와 slug(세션 이름)을 추출한다."""
    sessions = {}
    if not project_dir.exists():
        return sessions

    jsonl_files = sorted(
        project_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]

    for jf in jsonl_files:
        sid = jf.stem
        prompt = ""
        cwd = ""
        timestamp = ""
        slug = ""
        try:
            with open(jf, "r") as f:
                found_user = False
                for line_no, line in enumerate(f):
                    if line_no >= 30:
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("slug"):
                        slug = obj["slug"]
                    if not found_user and obj.get("type") == "user":
                        msg = obj.get("message", {}).get("content", "")
                        if isinstance(msg, list):
                            msg = " ".join(
                                p.get("text", "") for p in msg
                                if isinstance(p, dict) and p.get("type") == "text"
                            )
                        prompt = (msg or "")[:200]
                        cwd = obj.get("cwd", "")
                        timestamp = obj.get("timestamp", "")
                        found_user = True
                    if found_user and slug:
                        break
        except OSError:
            continue

        sessions[sid] = {
            "session_id": sid,
            "job_id":     None,
            "prompt":     prompt,
            "timestamp":  timestamp,
            "status":     "done",
            "cwd":        cwd,
            "cost_usd":   None,
            "slug":       slug,
        }

    return sessions
