"""
Goal 관련 HTTP 핸들러 Mixin

포함 엔드포인트:
  - GET    /api/goals              # 목표 목록 (status 필터 가능)
  - GET    /api/goals/:id          # 목표 상세 (DAG 포함)
  - POST   /api/goals              # 목표 생성
  - POST   /api/goals/:id/update   # 목표 수정 (mode, budget 변경)
  - POST   /api/goals/:id/approve  # Gate 모드: 다음 단계 승인
  - DELETE /api/goals/:id          # 목표 취소
"""

import sys
import time
from urllib.parse import parse_qs

from config import CONTROLLER_DIR, DATA_DIR

# cognitive 패키지를 import 경로에 추가
if str(CONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_DIR))

from cognitive.goal_engine import GoalEngine, GoalStatus, ExecutionMode

# 모듈 수준 싱글턴
_goal_engine = None


def _get_engine():
    global _goal_engine
    if _goal_engine is None:
        _goal_engine = GoalEngine(str(DATA_DIR))
    return _goal_engine


class GoalHandlerMixin:

    def _handle_list_goals(self, parsed):
        """GET /api/goals — 목표 목록"""
        qs = parse_qs(parsed.query)
        status = qs.get("status", [None])[0]
        goals = _get_engine().list_goals(status=status)
        self._json_response(goals)

    def _handle_get_goal(self, goal_id):
        """GET /api/goals/:id — 목표 상세 (DAG, 진행률 포함)"""
        goal = _get_engine().get_goal(goal_id)
        if goal is None:
            return self._error_response(
                "목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")
        # 실행 가능한 다음 태스크 정보도 포함
        next_tasks = _get_engine().get_next_tasks(goal_id)
        goal["next_tasks"] = next_tasks
        self._json_response(goal)

    def _handle_create_goal(self):
        """POST /api/goals — 목표 생성"""
        body = self._read_body()
        objective = body.get("objective", "").strip()
        if not objective:
            return self._error_response(
                "objective 필드가 필요합니다", 400, code="MISSING_FIELD")

        mode_str = body.get("mode", "gate")
        try:
            mode = ExecutionMode(mode_str)
        except ValueError:
            valid = [m.value for m in ExecutionMode]
            return self._error_response(
                f"유효하지 않은 mode: {mode_str}. 가능한 값: {valid}",
                400, code="INVALID_MODE")

        context = body.get("context", {})
        if not isinstance(context, dict):
            return self._error_response(
                "context는 JSON 객체여야 합니다", 400, code="INVALID_PARAM")

        try:
            budget_usd = float(body.get("budget_usd", 5.0))
            max_tasks = int(body.get("max_tasks", 20))
        except (ValueError, TypeError):
            return self._error_response(
                "budget_usd 또는 max_tasks 값이 유효하지 않습니다",
                400, code="INVALID_PARAM")

        if budget_usd <= 0:
            return self._error_response(
                "budget_usd는 0보다 커야 합니다", 400, code="INVALID_PARAM")
        if max_tasks < 1:
            return self._error_response(
                "max_tasks는 1 이상이어야 합니다", 400, code="INVALID_PARAM")

        goal = _get_engine().create_goal(
            objective=objective,
            mode=mode,
            context=context,
            budget_usd=budget_usd,
            max_tasks=max_tasks,
        )
        self._json_response(goal, 201)

    def _handle_update_goal(self, goal_id):
        """POST /api/goals/:id/update — 목표 수정 (mode, budget 변경)"""
        engine = _get_engine()
        goal = engine.get_goal(goal_id)
        if goal is None:
            return self._error_response(
                "목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")

        if goal["status"] in (GoalStatus.COMPLETED.value,
                              GoalStatus.FAILED.value,
                              GoalStatus.CANCELLED.value):
            return self._error_response(
                f"종료된 목표({goal['status']})는 수정할 수 없습니다",
                409, code="GOAL_ALREADY_FINISHED")

        body = self._read_body()
        changed = False

        if "mode" in body:
            try:
                mode = ExecutionMode(body["mode"])
                goal["mode"] = mode.value
                changed = True
            except ValueError:
                valid = [m.value for m in ExecutionMode]
                return self._error_response(
                    f"유효하지 않은 mode: {body['mode']}. 가능한 값: {valid}",
                    400, code="INVALID_MODE")

        if "budget_usd" in body:
            try:
                budget = float(body["budget_usd"])
                if budget <= 0:
                    raise ValueError
                goal["budget_usd"] = budget
                changed = True
            except (ValueError, TypeError):
                return self._error_response(
                    "budget_usd는 0보다 큰 숫자여야 합니다",
                    400, code="INVALID_PARAM")

        if "max_tasks" in body:
            try:
                mt = int(body["max_tasks"])
                if mt < 1:
                    raise ValueError
                goal["max_tasks"] = mt
                changed = True
            except (ValueError, TypeError):
                return self._error_response(
                    "max_tasks는 1 이상의 정수여야 합니다",
                    400, code="INVALID_PARAM")

        if not changed:
            return self._error_response(
                "변경할 필드가 없습니다. mode, budget_usd, max_tasks 중 하나를 지정하세요.",
                400, code="NO_CHANGES")

        goal["updated_at"] = time.time()
        engine._save_goal(goal)
        self._json_response(goal)

    def _handle_approve_goal(self, goal_id):
        """POST /api/goals/:id/approve — Gate 모드: 다음 단계 승인"""
        engine = _get_engine()
        goal = engine.get_goal(goal_id)
        if goal is None:
            return self._error_response(
                "목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")

        if goal["status"] != GoalStatus.GATE_WAITING.value:
            return self._error_response(
                f"현재 상태({goal['status']})에서는 승인할 수 없습니다. "
                "gate_waiting 상태일 때만 가능합니다.",
                409, code="INVALID_STATE_TRANSITION")

        engine.update_status(goal_id, GoalStatus.RUNNING)
        next_tasks = engine.get_next_tasks(goal_id)
        goal = engine.get_goal(goal_id)

        self._json_response({
            "goal": goal,
            "next_tasks": next_tasks,
        })

    def _handle_cancel_goal(self, goal_id):
        """DELETE /api/goals/:id — 목표 취소"""
        engine = _get_engine()
        goal = engine.get_goal(goal_id)
        if goal is None:
            return self._error_response(
                "목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")

        if goal["status"] in (GoalStatus.COMPLETED.value,
                              GoalStatus.FAILED.value,
                              GoalStatus.CANCELLED.value):
            return self._error_response(
                f"이미 종료된 목표({goal['status']})는 취소할 수 없습니다",
                409, code="GOAL_ALREADY_FINISHED")

        goal = engine.cancel_goal(goal_id)
        self._json_response(goal)
