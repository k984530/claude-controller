"""
Goal 관련 HTTP 핸들러 Mixin

데이터 로직은 goals.py에 분리되어 있다.

포함 엔드포인트:
  - GET    /api/goals              # 목표 목록 (?project=<path>&status=active)
  - GET    /api/goals/:id          # 목표 상세 (마크다운 원문)
  - POST   /api/goals              # 목표 생성 (project 필수)
  - POST   /api/goals/:id/update   # 목표 수정
  - POST   /api/goals/:id/execute  # AI 실행 (goal → job 디스패치)
  - DELETE /api/goals/:id          # 목표 삭제
"""

import time
from urllib.parse import parse_qs

from config import GOALS_DIR
from utils import generate_id
from goals import (
    ensure_dir, parse_frontmatter, build_frontmatter,
    extract_pending_tasks, goal_id_safe, read_goal, list_goals,
    build_execute_prompt, create_goal,
)


class GoalHandlerMixin:

    def _handle_list_goals(self, parsed):
        """GET /api/goals?project=<path>&status=active"""
        qs = parse_qs(parsed.query)
        status = qs.get("status", [None])[0]
        project = qs.get("project", [None])[0]
        self._json_response(list_goals(status=status, project=project))

    def _handle_get_goal(self, goal_id):
        """GET /api/goals/:id"""
        if not goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")
        goal = read_goal(goal_id)
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

        goal_id = generate_id("goal")
        goal = create_goal(goal_id, title, project, body=body.get("body", "").strip())
        self._json_response(goal, 201)

    def _handle_update_goal(self, goal_id):
        """POST /api/goals/:id/update"""
        if not goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")

        path = GOALS_DIR / f"{goal_id}.md"
        if not path.exists():
            return self._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")

        body = self._read_body()
        content = path.read_text("utf-8")
        meta, old_body = parse_frontmatter(content)

        if "title" in body:
            meta["title"] = body["title"].strip()
        if "status" in body:
            if body["status"] in ("active", "completed", "archived"):
                meta["status"] = body["status"]
        meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        new_body = body.get("body", old_body)
        file_content = build_frontmatter(meta) + "\n\n" + new_body.strip() + "\n"
        path.write_text(file_content, "utf-8")

        goal = read_goal(goal_id)
        self._json_response(goal)

    def _handle_execute_goal(self, goal_id):
        """POST /api/goals/:id/execute — Goal의 미완료 태스크를 AI에게 디스패치"""
        if not goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")

        goal = read_goal(goal_id)
        if goal is None:
            return self._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")
        if goal["status"] != "active":
            return self._error_response("active 상태의 목표만 실행할 수 있습니다", 409, code="GOAL_NOT_ACTIVE")

        pending = extract_pending_tasks(goal["body"])
        if not pending:
            return self._error_response("미완료 태스크가 없습니다", 409, code="NO_PENDING_TASKS")

        cwd = goal["project"]
        goal_file = str(GOALS_DIR / f"{goal_id}.md")
        prompt, system_prompt = build_execute_prompt(goal, goal_file, pending)

        result, err = self._jobs_mod().send_to_fifo(
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

    def _handle_cancel_goal(self, goal_id):
        """DELETE /api/goals/:id"""
        if not goal_id_safe(goal_id):
            return self._error_response("유효하지 않은 ID", 400, code="INVALID_ID")

        path = GOALS_DIR / f"{goal_id}.md"
        if not path.exists():
            return self._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")

        try:
            path.unlink()
            self._json_response({"deleted": True, "id": goal_id})
        except OSError as e:
            return self._error_response(f"삭제 실패: {e}", 500, code="DELETE_FAILED")
