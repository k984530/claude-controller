"""
Controller Service — 프로젝트 관리

프로젝트는 자동화 대상 저장소/디렉토리를 등록·관리하는 단위이다.
기존 프로젝트를 등록하거나, 신규 프로젝트를 생성(디렉토리 + git init)할 수 있다.
저장: data/projects.json
"""

import json
import os
import subprocess
import time

from config import DATA_DIR, LOGS_DIR
from utils import parse_meta_file, generate_id

PROJECTS_FILE = DATA_DIR / "projects.json"


def _load_projects() -> list[dict]:
    """프로젝트 목록을 파일에서 읽는다."""
    try:
        if PROJECTS_FILE.exists():
            return json.loads(PROJECTS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_projects(projects: list[dict]):
    """프로젝트 목록을 파일에 원자적으로 저장한다."""
    from utils import atomic_json_save
    atomic_json_save(PROJECTS_FILE, projects)


def _generate_id() -> str:
    return generate_id("proj")


def _collect_job_stats_by_cwd() -> dict:
    """logs/ 디렉토리의 .meta 파일을 순회하여 cwd별 job 통계를 집계한다."""
    stats = {}
    if not LOGS_DIR.exists():
        return stats
    for mf in LOGS_DIR.glob("job_*.meta"):
        meta = parse_meta_file(mf)
        if not meta:
            continue
        cwd = meta.get("CWD", "")
        if not cwd:
            continue
        norm = os.path.normpath(cwd)
        if norm not in stats:
            stats[norm] = {"total": 0, "running": 0, "done": 0, "failed": 0, "cost": 0.0}
        s = stats[norm]
        s["total"] += 1
        status = meta.get("STATUS", "unknown")
        if status == "running":
            pid = meta.get("PID")
            if pid:
                try:
                    os.kill(int(pid), 0)
                except (ProcessLookupError, ValueError, OSError):
                    status = "done"
        if status == "running":
            s["running"] += 1
        elif status == "done":
            s["done"] += 1
        elif status == "failed":
            s["failed"] += 1
    return stats


def _detect_git_info(path: str) -> dict:
    """디렉토리의 git 정보를 감지한다."""
    info = {"is_git": False, "branch": "", "remote": ""}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return info
        info["is_git"] = True

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path, capture_output=True, text=True, timeout=5,
        )
        info["branch"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path, capture_output=True, text=True, timeout=5,
        )
        info["remote"] = result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return info


# ══════════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════════

def list_projects(include_job_stats=True) -> list[dict]:
    """등록된 프로젝트 목록을 반환한다.

    Args:
        include_job_stats: True이면 각 프로젝트의 job 통계를 포함한다.
    """
    projects = _load_projects()

    # job 통계를 위한 cwd→count 맵 (한 번만 순회)
    job_stats = {}
    if include_job_stats:
        job_stats = _collect_job_stats_by_cwd()

    for p in projects:
        p["exists"] = os.path.isdir(p.get("path", ""))
        if include_job_stats:
            norm_path = os.path.normpath(p.get("path", ""))
            stats = job_stats.get(norm_path, {})
            p["job_stats"] = {
                "total": stats.get("total", 0),
                "running": stats.get("running", 0),
                "done": stats.get("done", 0),
                "failed": stats.get("failed", 0),
                "total_cost": round(stats.get("cost", 0), 4),
            }
    return projects


def get_project(project_id: str) -> tuple[dict | None, str | None]:
    """ID로 프로젝트를 조회한다."""
    projects = _load_projects()
    for p in projects:
        if p["id"] == project_id:
            p["exists"] = os.path.isdir(p.get("path", ""))
            git_info = _detect_git_info(p["path"]) if p["exists"] else {}
            p.update(git_info)
            return p, None
    return None, "프로젝트를 찾을 수 없습니다"


def add_project(path: str, name: str = "", description: str = "") -> tuple[dict | None, str | None]:
    """기존 디렉토리를 프로젝트로 등록한다."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        return None, f"디렉토리가 존재하지 않습니다: {path}"

    projects = _load_projects()

    # 중복 체크
    for p in projects:
        if os.path.normpath(p["path"]) == os.path.normpath(path):
            return None, f"이미 등록된 프로젝트입니다: {p['name']} ({p['id']})"

    if not name:
        name = os.path.basename(path)

    git_info = _detect_git_info(path)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    project = {
        "id": _generate_id(),
        "name": name,
        "path": path,
        "description": description,
        "is_git": git_info["is_git"],
        "branch": git_info["branch"],
        "remote": git_info["remote"],
        "created_at": now,
        "last_used_at": now,
    }

    projects.append(project)
    _save_projects(projects)
    return project, None


def create_project(path: str, name: str = "", description: str = "",
                   init_git: bool = True) -> tuple[dict | None, str | None]:
    """신규 프로젝트를 생성한다 (디렉토리 생성 + git init + 등록)."""
    path = os.path.abspath(os.path.expanduser(path))

    if os.path.exists(path):
        return None, f"이미 존재하는 경로입니다: {path}"

    try:
        os.makedirs(path)
    except OSError as e:
        return None, f"디렉토리 생성 실패: {e}"

    if init_git:
        try:
            subprocess.run(
                ["git", "init"],
                cwd=path, capture_output=True, text=True, timeout=10, check=True,
            )
        except (subprocess.CalledProcessError, OSError) as e:
            return None, f"git init 실패: {e}"

    if not name:
        name = os.path.basename(path)

    return add_project(path, name=name, description=description)


def remove_project(project_id: str) -> tuple[dict | None, str | None]:
    """프로젝트 등록을 해제한다 (디렉토리는 삭제하지 않음)."""
    projects = _load_projects()
    for i, p in enumerate(projects):
        if p["id"] == project_id:
            removed = projects.pop(i)
            _save_projects(projects)
            return removed, None
    return None, "프로젝트를 찾을 수 없습니다"


def update_project(project_id: str, **kwargs) -> tuple[dict | None, str | None]:
    """프로젝트 정보를 업데이트한다."""
    projects = _load_projects()
    allowed = {"name", "description"}
    for p in projects:
        if p["id"] == project_id:
            for k, v in kwargs.items():
                if k in allowed and v is not None:
                    p[k] = v
            p["last_used_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save_projects(projects)
            return p, None
    return None, "프로젝트를 찾을 수 없습니다"


def touch_project(project_id: str):
    """last_used_at을 갱신한다."""
    projects = _load_projects()
    for p in projects:
        if p["id"] == project_id:
            p["last_used_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save_projects(projects)
            return
