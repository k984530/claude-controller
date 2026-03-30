"""
Goal 관련 HTTP 핸들러 Mixin — 파일 기반, 프로젝트 단위

data/goals/<id>.md 마크다운 파일로 Goal/To-do를 관리한다.
YAML frontmatter + 체크박스(- [ ] / - [x]) 기반.
각 Goal은 frontmatter의 project 필드로 프로젝트에 귀속된다.

포함 엔드포인트:
  - GET    /api/goals              # 목표 목록 (?project=<path>&status=active)
  - GET    /api/goals/:id          # 목표 상세 (마크다운 원문)
  - POST   /api/goals              # 목표 생성 (project 필수)
  - POST   /api/goals/:id/update   # 목표 수정
  - POST   /api/goals/:id/execute  # AI 실행 (goal → job 디스패치)
  - DELETE /api/goals/:id          # 목표 삭제
"""

import os
import random
import re
import time

from config import GOALS_DIR, CONTROLLER_DIR


def _ensure_dir():
    GOALS_DIR.mkdir(parents=True, exist_ok=True)


def _parse_frontmatter(content):
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


def _build_frontmatter(meta):
    lines = ["---"]
    for k, v in meta.items():
        v = str(v).replace('\n', ' ').strip()
        if ':' in v or v.startswith('{') or v.startswith('[') or '---' in v:
            v = '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _count_tasks(body):
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


def _extract_pending_tasks(body):
    """본문에서 미완료 체크박스 항목의 텍스트를 추출한다."""
    pending = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            task_text = stripped[5:].strip()
            if task_text:
                pending.append(task_text)
    return pending


def _goal_id_safe(goal_id):
    """파일명으로 안전한 ID인지 확인."""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', goal_id))


def _read_goal(goal_id):
    """Goal 파일을 읽어 dict로 반환한다."""
    path = GOALS_DIR / f"{goal_id}.md"
    if not path.exists():
        return None
    content = path.read_text("utf-8")
    meta, body = _parse_frontmatter(content)
    total, done = _count_tasks(body)
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


def list_goals(status=None, project=None):
    """Goal 파일 목록을 반환한다. project/status로 필터링 가능."""
    _ensure_dir()
    goals = []
    project_norm = os.path.normpath(project) if project else None

    for f in sorted(GOALS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        goal_id = f.stem
        goal = _read_goal(goal_id)
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


def auto_create_goal(prompt, project):
    """프롬프트 전송 시 자동으로 Goal 파일을 생성한다.

    Returns:
        (goal_id, goal_file_path) — 생성된 Goal의 ID와 파일 경로
    """
    _ensure_dir()
    goal_id = f"goal-{int(time.time())}-{os.getpid() % 1000}-{random.randint(0, 9999):04d}"
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # 프롬프트에서 제목 추출 (첫 줄, 최대 60자)
    title = prompt.split("\n")[0].strip()
    if len(title) > 60:
        title = title[:57] + "..."

    meta = {
        "title": title,
        "status": "active",
        "project": project or "",
        "created_at": now,
        "updated_at": now,
    }
    body = f"## {title}\n\n- [ ] {title}"
    file_content = _build_frontmatter(meta) + "\n\n" + body + "\n"

    goal_path = GOALS_DIR / f"{goal_id}.md"
    goal_path.write_text(file_content, "utf-8")
    return goal_id, str(goal_path)


class GoalHandlerMixin:

    def _handle_list_goals(self, parsed):
        """GET /api/goals?project=<path>&status=active"""
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        status = qs.get("status", [None])[0]
        project = qs.get("project", [None])[0]
        self._json_response(list_goals(status=status, project=project))

    def _handle_get_goal(self, goal_id):
        """GET /api/goals/:id"""
        if not _goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")
        goal = _read_goal(goal_id)
        if goal is None:
            return self._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")
        self._json_response(goal)

    def _handle_create_goal(self):
        """POST /api/goals — project 필드 필수"""
        body = self._read_body()
        title = body.get("title", "").strip()
        project = body.get("project", "").strip()
        if not title:
            return self._error_response("title 필드가 필요합니다", 400, code="MISSING_FIELD")
        if not project:
            return self._error_response("project 필드가 필요합니다 (프로젝트 경로)", 400, code="MISSING_FIELD")

        _ensure_dir()
        goal_id = f"goal-{int(time.time())}-{os.getpid() % 1000}-{random.randint(0, 9999):04d}"
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        content_body = body.get("body", "").strip()
        if not content_body:
            content_body = f"## {title}\n\n- [ ] "

        meta = {
            "title": title,
            "status": "active",
            "project": project,
            "created_at": now,
            "updated_at": now,
        }

        file_content = _build_frontmatter(meta) + "\n\n" + content_body + "\n"
        (GOALS_DIR / f"{goal_id}.md").write_text(file_content, "utf-8")

        goal = _read_goal(goal_id)
        self._json_response(goal, 201)

    def _handle_update_goal(self, goal_id):
        """POST /api/goals/:id/update"""
        if not _goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")

        path = GOALS_DIR / f"{goal_id}.md"
        if not path.exists():
            return self._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")

        body = self._read_body()
        content = path.read_text("utf-8")
        meta, old_body = _parse_frontmatter(content)

        if "title" in body:
            meta["title"] = body["title"].strip()
        if "status" in body:
            if body["status"] in ("active", "completed", "archived"):
                meta["status"] = body["status"]
        meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        new_body = body.get("body", old_body)
        file_content = _build_frontmatter(meta) + "\n\n" + new_body.strip() + "\n"
        path.write_text(file_content, "utf-8")

        goal = _read_goal(goal_id)
        self._json_response(goal)

    def _handle_execute_goal(self, goal_id):
        """POST /api/goals/:id/execute — Goal의 미완료 태스크를 AI에게 디스패치"""
        if not _goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")

        goal = _read_goal(goal_id)
        if goal is None:
            return self._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")
        if goal["status"] != "active":
            return self._error_response("active 상태의 목표만 실행할 수 있습니다", 409, code="GOAL_NOT_ACTIVE")

        pending = _extract_pending_tasks(goal["body"])
        if not pending:
            return self._error_response("미완료 태스크가 없습니다", 409, code="NO_PENDING_TASKS")

        # cwd는 Goal의 project 경로 사용
        cwd = goal["project"]
        goal_file = str(GOALS_DIR / f"{goal_id}.md")

        task_list = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(pending))
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
프로젝트: {cwd}
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

        import jobs
        result, err = jobs.send_to_fifo(
            prompt,
            cwd=cwd or None,
            system_prompt=system_prompt,
        )
        if err:
            return self._error_response(err, 502, code="DISPATCH_FAILED")

        self._json_response({
            "dispatched": True,
            "goal_id": goal_id,
            "pending_tasks": pending,
            "job": result,
        })

    def _handle_dispatch_next(self):
        """POST /api/goals/dispatch-next — 프로젝트의 다음 미완료 태스크를 자동 디스패치

        자동화(파이프라인)에서 반복 호출하면 Goal 기반 자율 실행이 된다.
        body: { project: "/path/to/project" }
        """
        body = self._read_body()
        project = (body.get("project", "") if body else "").strip()
        if not project:
            return self._error_response("project 필드가 필요합니다", 400, code="MISSING_FIELD")

        # 이 프로젝트의 active goals 중 미완료 태스크가 있는 첫 번째 Goal 선택
        goals = list_goals(status="active", project=project)
        target_goal = None
        target_task = None
        for g in goals:
            full = _read_goal(g["id"])
            if not full:
                continue
            pending = _extract_pending_tasks(full["body"])
            if pending:
                target_goal = full
                target_task = pending[0]  # 첫 번째 미완료 태스크
                break

        if not target_goal or not target_task:
            return self._json_response({
                "dispatched": False,
                "reason": "미완료 태스크가 없습니다",
                "project": project,
            })

        goal_file = str(GOALS_DIR / f"{target_goal['id']}.md")

        prompt = f"""[Goal 기반 작업]
목표: {target_goal["title"]}
파일: {goal_file}
프로젝트: {project}

다음 태스크를 수행하세요:
  → {target_task}

완료 후:
1. Goal 파일({goal_file})에서 이 항목의 체크박스를 - [x]로 업데이트하세요.
2. 모든 태스크가 완료되었다면 frontmatter의 status를 completed로 변경하세요.
3. 결과를 간결하게 요약하세요."""

        system_prompt = f"""[실행 중인 Goal]
제목: {target_goal["title"]}
프로젝트: {project}
파일: {goal_file}
진행률: {target_goal["tasks_done"]}/{target_goal["tasks_total"]}

현재 태스크: {target_task}

규칙:
1. 위 태스크만 수행하세요. 범위를 벗어나지 마세요.
2. 완료 시 Goal 파일의 체크박스를 업데이트하세요."""

        import jobs
        result, err = jobs.send_to_fifo(
            prompt,
            cwd=project,
            system_prompt=system_prompt,
        )
        if err:
            return self._error_response(err, 502, code="DISPATCH_FAILED")

        self._json_response({
            "dispatched": True,
            "goal_id": target_goal["id"],
            "goal_title": target_goal["title"],
            "task": target_task,
            "remaining": target_goal["tasks_total"] - target_goal["tasks_done"] - 1,
            "job": result,
        })

    def _handle_cancel_goal(self, goal_id):
        """DELETE /api/goals/:id"""
        if not _goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")

        path = GOALS_DIR / f"{goal_id}.md"
        if not path.exists():
            return self._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")

        try:
            path.unlink()
            self._json_response({"deleted": True, "id": goal_id})
        except OSError as e:
            self._error_response(f"삭제 실패: {e}", 500, code="DELETE_FAILED")
