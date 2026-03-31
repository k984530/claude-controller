"""
Controller Service — 유틸리티 함수
"""

import json
import os
import re
from pathlib import Path

import time

from config import PID_FILE, SKILLS_FILE, LOGS_DIR

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


def load_json_list(filepath: Path) -> list[dict]:
    """JSON 파일에서 리스트를 로드한다. 파일 없음/파싱 실패 시 빈 리스트 반환."""
    if not filepath.exists():
        return []
    try:
        data = json.loads(filepath.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_json_list(filepath: Path, items: list[dict]):
    """리스트를 JSON 파일에 원자적으로 저장한다. 부모 디렉토리 자동 생성."""
    atomic_json_save(filepath, items)


def load_json_file(filepath: Path, default=None):
    """JSON 파일을 로드한다. 파일 없음/파싱 실패 시 default 반환."""
    if default is None:
        default = {}
    if not filepath.exists():
        return default
    try:
        return json.loads(filepath.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def find_skills_by_ids(skill_ids: list[str]) -> list[dict]:
    """skill_ids에 해당하는 스킬 객체를 반환한다. 호출자가 필요한 필드를 선택."""
    if not skill_ids:
        return []
    cats = load_json_list(SKILLS_FILE)
    id_set = set(skill_ids)
    found = []
    for cat in cats:
        for skill in cat.get("skills", []):
            if skill.get("id") in id_set:
                found.append(skill)
    return found


def load_recent_meta(limit: int = 200) -> list[dict]:
    """최근 작업 메타 데이터를 로드한다. mtime 기준 정렬."""
    if not LOGS_DIR.exists():
        return []
    meta_files = sorted(
        LOGS_DIR.glob("job_*.meta"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]
    result = []
    for mf in meta_files:
        meta = parse_meta_file(mf)
        if meta:
            result.append(meta)
    return result


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


def is_pid_alive(pid) -> bool:
    """프로세스가 살아있는지 확인한다. pid가 None/빈문자열이면 False."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


def correct_running_status(meta: dict) -> str:
    """meta의 STATUS가 running이지만 PID가 죽었으면 'done'으로 보정한 상태를 반환한다."""
    status = meta.get("STATUS", "unknown")
    if status == "running" and not is_pid_alive(meta.get("PID")):
        return "done"
    return status


def parse_job_output(out_file_path) -> dict:
    """job .out 파일에서 result 이벤트를 파싱한다.

    Returns:
        dict with keys: result, cost_usd, duration_ms, session_id, is_error
        모두 None일 수 있음. 파일이 없거나 result 이벤트가 없으면 빈 dict.
    """
    parsed = {"result": None, "cost_usd": None, "duration_ms": None,
              "session_id": None, "is_error": False}
    if not hasattr(out_file_path, 'exists'):
        out_file_path = Path(out_file_path)
    if not out_file_path.exists():
        return parsed
    try:
        with open(out_file_path, "r") as f:
            for line in f:
                if '"type":"result"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "result":
                        parsed["result"] = obj.get("result", "")
                        parsed["cost_usd"] = obj.get("total_cost_usd")
                        parsed["duration_ms"] = obj.get("duration_ms")
                        parsed["session_id"] = obj.get("session_id")
                        parsed["is_error"] = obj.get("is_error", False)
                except json.JSONDecodeError:
                    continue
        # fallback: 전체 파일이 단일 JSON인 경우
        if parsed["result"] is None:
            try:
                data = json.loads(out_file_path.read_text())
                parsed["result"] = data.get("result", "")
                parsed["cost_usd"] = data.get("total_cost_usd")
                parsed["duration_ms"] = data.get("duration_ms")
                parsed["session_id"] = data.get("session_id")
                parsed["is_error"] = data.get("is_error", False)
            except (json.JSONDecodeError, OSError):
                pass
    except OSError:
        pass
    return parsed


def parse_ts(value):
    """타임스탬프 문자열을 Unix timestamp(float)로 파싱한다.

    지원 형식: Unix timestamp, 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SS'.
    파싱 실패 또는 None 입력 시 None 반환.
    """
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return time.mktime(time.strptime(value, fmt))
        except ValueError:
            continue
    return None


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


def parse_stream_events(out_file, offset):
    """out 파일에서 offset 이후의 스트림 이벤트를 파싱한다.

    Returns:
        (events, new_offset) — events는 dict 리스트, new_offset은 다음 읽기 위치.
    """
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
                        from error_classify import classify_error
                        result_evt = {
                            "type": "result",
                            "result": evt.get("result", ""),
                            "cost_usd": evt.get("total_cost_usd"),
                            "duration_ms": evt.get("duration_ms"),
                            "is_error": evt.get("is_error", False),
                            "session_id": evt.get("session_id", "")
                        }
                        if result_evt["is_error"]:
                            result_evt["user_error"] = classify_error(evt.get("result", ""))
                        events.append(result_evt)
                except json.JSONDecodeError:
                    continue
            new_offset = f.tell()
    except OSError:
        pass
    return events, new_offset
