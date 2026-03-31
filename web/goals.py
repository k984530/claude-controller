"""
Goal Engine — 파일 기반 Goal/To-do 데이터 관리

data/goals/<id>.md 마크다운 파일로 Goal을 관리한다.
YAML frontmatter + 체크박스(- [ ] / - [x]) 기반.

HTTP 핸들러는 handler_goals.py에 분리되어 있다.
"""

import os
import re
import time

from config import GOALS_DIR


def ensure_dir():
    GOALS_DIR.mkdir(parents=True, exist_ok=True)


def parse_frontmatter(content):
    """YAML frontmatter를 간이 파싱한다. (외부 의존성 없음)"""
    meta = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                line = line.strip()
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip()
            body = parts[2].strip()
    return meta, body


def build_frontmatter(meta):
    lines = ["---"]
    for k, v in meta.items():
        v = str(v).replace('\n', ' ').strip()
        if ':' in v or v.startswith('{') or v.startswith('[') or '---' in v:
            v = '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def count_tasks(body):
    """본문에서 체크박스 태스크 수를 센다."""
    total = 0
    done = 0
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [x]") or stripped.startswith("- [X]"):
            total += 1
            done += 1
        elif stripped.startswith("- [ ]"):
            total += 1
    return total, done


def extract_pending_tasks(body):
    """본문에서 미완료 체크박스 항목의 텍스트를 추출한다."""
    pending = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            task_text = stripped[5:].strip()
            if task_text:
                pending.append(task_text)
    return pending


def goal_id_safe(goal_id):
    """파일명으로 안전한 ID인지 확인."""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', goal_id))


def read_goal(goal_id):
    """Goal 파일을 읽어 dict로 반환한다."""
    path = GOALS_DIR / f"{goal_id}.md"
    if not path.exists():
        return None
    content = path.read_text("utf-8")
    meta, body = parse_frontmatter(content)
    total, done = count_tasks(body)
    return {
        "id": goal_id,
        "title": meta.get("title", goal_id),
        "status": meta.get("status", "active"),
        "project": meta.get("project", ""),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "body": body,
        "tasks_total": total,
        "tasks_done": done,
    }


def create_goal(goal_id: str, title: str, project: str, body: str = "") -> dict:
    """새 Goal 파일을 생성하고 읽어서 반환한다.

    Args:
        goal_id: 고유 ID (파일명으로 사용)
        title: 목표 제목
        project: 프로젝트 경로
        body: 마크다운 본문 (비어있으면 기본 템플릿)
    """
    import time
    ensure_dir()

    if not body:
        body = f"## {title}\n\n- [ ] "

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "title": title,
        "status": "active",
        "project": project,
        "created_at": now,
        "updated_at": now,
    }

    file_content = build_frontmatter(meta) + "\n\n" + body + "\n"
    (GOALS_DIR / f"{goal_id}.md").write_text(file_content, "utf-8")
    return read_goal(goal_id)


def list_goals(status=None, project=None):
    """Goal 파일 목록을 반환한다. project/status로 필터링 가능."""
    ensure_dir()
    goals = []
    project_norm = os.path.normpath(project) if project else None

    for f in sorted(GOALS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        goal_id = f.stem
        goal = read_goal(goal_id)
        if goal is None:
            continue
        if status and goal["status"] != status:
            continue
        if project_norm:
            gp = os.path.normpath(goal["project"]) if goal["project"] else ""
            if gp != project_norm:
                continue
        summary = goal.copy()
        summary.pop("body", None)
        goals.append(summary)
    return goals


def build_execute_prompt(goal: dict, goal_file: str, pending_tasks: list[str]) -> tuple[str, str]:
    """Goal 실행용 프롬프트와 시스템 프롬프트를 생성한다.

    Returns:
        (prompt, system_prompt) 튜플
    """
    task_list = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(pending_tasks))
    prompt = f"""[Goal 기반 작업 실행]

목표: {goal["title"]}
파일: {goal_file}

미완료 태스크:
{task_list}

위 태스크를 순서대로 수행하세요.
각 태스크를 완료하면, Goal 파일({goal_file})을 Edit 도구로 열어 해당 항목의 체크박스를 - [ ] → - [x] 로 업데이트하세요.
모든 태스크 완료 후 결과를 요약하세요."""

    system_prompt = f"""[실행 중인 Goal]
제목: {goal["title"]}
프로젝트: {goal["project"]}
파일: {goal_file}
진행률: {goal["tasks_done"]}/{goal["tasks_total"]}

아래는 Goal 파일의 전체 내용입니다:
---
{goal["body"]}
---

규칙:
1. 위 태스크 목록에서 미완료 항목(- [ ])을 순서대로 작업하세요.
2. 각 항목 완료 시 Goal 파일의 체크박스를 - [x]로 업데이트하세요.
3. 작업 범위를 벗어나는 일은 하지 마세요."""

    return prompt, system_prompt
