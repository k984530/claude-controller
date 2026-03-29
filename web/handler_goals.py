"""
Goal 관련 HTTP 핸들러 Mixin

포함 엔드포인트:
  - GET    /api/goals              # 목표 목록 (status 필터 가능)
  - GET    /api/goals/:id          # 목표 상세 (DAG 포함)
  - POST   /api/goals              # 목표 생성
  - POST   /api/goals/:id/update   # 목표 수정 (mode, budget 변경)
  - POST   /api/goals/:id/approve  # Gate 모드: Orchestrator 승인 → 백그라운드 실행
  - POST   /api/goals/:id/plan     # 계획 생성 트리거
  - POST   /api/goals/:id/execute  # 실행 트리거
  - DELETE /api/goals/:id          # 목표 취소
"""

import logging
import sys
import threading
import time
from urllib.parse import parse_qs

from config import CONTROLLER_DIR, DATA_DIR

# cognitive 패키지를 import 경로에 추가
if str(CONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_DIR))

from cognitive.goal_engine import GoalEngine, GoalStatus, ExecutionMode
from cognitive.orchestrator import Orchestrator

logger = logging.getLogger("handler_goals")

# 모듈 수준 싱글턴
_goal_engine = None
_orchestrator = None
_running_goals = {}  # goal_id → Thread


def _get_engine():
    global _goal_engine
    if _goal_engine is None:
        _goal_engine = GoalEngine(str(DATA_DIR))
    return _goal_engine


def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(base_dir=str(CONTROLLER_DIR))
    return _orchestrator


def _is_goal_running(goal_id):
    """목표가 현재 백그라운드에서 실행 중인지 확인한다."""
    thread = _running_goals.get(goal_id)
    return thread is not None and thread.is_alive()


def _run_in_background(goal_id, fn, *args):
    """Orchestrator 작업을 백그라운드 스레드로 실행한다.

    중복 실행 방지: 동일 goal_id에 대해 이미 실행 중이면 무시한다.
    실패 시 goal 상태를 FAILED로 전이한다.
    """
    if _is_goal_running(goal_id):
        logger.warning(f"Goal {goal_id} already running, skipping")
        return False

    def _worker():
        try:
            fn(*args)
        except Exception:
            logger.exception(f"Background task failed for goal {goal_id}")
            try:
                _get_engine().update_status(goal_id, GoalStatus.FAILED)
            except Exception:
                pass
        finally:
            _running_goals.pop(goal_id, None)

    t = threading.Thread(target=_worker, daemon=True, name=f"goal-{goal_id[:8]}")
    _running_goals[goal_id] = t
    t.start()
    return True


_FINISHED_STATUSES = frozenset({
    GoalStatus.COMPLETED.value,
    GoalStatus.FAILED.value,
    GoalStatus.CANCELLED.value,
})


def _require_goal(handler, goal_id, *, reject_finished=False, reject_running=False):
    """목표를 조회하고 공통 검증을 수행한다.

    Returns:
        (goal dict, None) — 성공
        (None, True) — 에러 응답 이미 전송됨
    """
    engine = _get_engine()
    goal = engine.get_goal(goal_id)
    if goal is None:
        handler._error_response("목표를 찾을 수 없습니다", 404, code="GOAL_NOT_FOUND")
        return None, True
    if reject_finished and goal["status"] in _FINISHED_STATUSES:
        handler._error_response(
            f"종료된 목표({goal['status']})에는 이 작업을 수행할 수 없습니다",
            409, code="GOAL_ALREADY_FINISHED")
        return None, True
    if reject_running and _is_goal_running(goal_id):
        handler._error_response(
            "이 목표는 이미 실행 중입니다.", 409, code="GOAL_ALREADY_RUNNING")
        return None, True
    return goal, None


class GoalHandlerMixin:

    def _handle_list_goals(self, parsed):
        """GET /api/goals — 목표 목록"""
        qs = parse_qs(parsed.query)
        status = qs.get("status", [None])[0]
        goals = _get_engine().list_goals(status=status)
        self._json_response(goals)

    def _handle_get_goal(self, goal_id):
        """GET /api/goals/:id — 목표 상세 (DAG, 진행률 포함)"""
        goal, err = _require_goal(self, goal_id)
        if err:
            return
        goal["next_tasks"] = _get_engine().get_next_tasks(goal_id)
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

        # auto 모드: 생성 즉시 백그라운드로 인지 루프 시작
        if mode == ExecutionMode.FULL_AUTO:
            orch = _get_orchestrator()
            _run_in_background(goal["id"], orch.run, goal["id"])

        self._json_response(goal, 201)

    def _handle_update_goal(self, goal_id):
        """POST /api/goals/:id/update — 목표 수정 (mode, budget 변경)"""
        goal, err = _require_goal(self, goal_id, reject_finished=True)
        if err:
            return
        engine = _get_engine()

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
        """POST /api/goals/:id/approve — Gate 모드: Orchestrator 승인 → 백그라운드 실행"""
        goal, err = _require_goal(self, goal_id, reject_running=True)
        if err:
            return

        if goal["status"] != GoalStatus.GATE_WAITING.value:
            return self._error_response(
                f"현재 상태({goal['status']})에서는 승인할 수 없습니다. "
                "gate_waiting 상태일 때만 가능합니다.",
                409, code="INVALID_STATE_TRANSITION")

        orch = _get_orchestrator()
        _run_in_background(goal_id, orch.approve_gate, goal_id)

        goal = _get_engine().get_goal(goal_id)
        self._json_response({"status": "executing", "goal": goal})

    def _handle_plan_goal(self, goal_id):
        """POST /api/goals/:id/plan — 계획 생성 트리거"""
        goal, err = _require_goal(self, goal_id, reject_finished=True, reject_running=True)
        if err:
            return

        orch = _get_orchestrator()
        _run_in_background(goal_id, orch.plan, goal_id)
        self._json_response({"status": "planning", "goal_id": goal_id})

    def _handle_execute_goal(self, goal_id):
        """POST /api/goals/:id/execute — 실행 트리거"""
        goal, err = _require_goal(self, goal_id, reject_finished=True, reject_running=True)
        if err:
            return

        if not goal.get("dag"):
            return self._error_response(
                "계획이 없습니다. plan을 먼저 실행하세요.", 409, code="NO_PLAN")

        orch = _get_orchestrator()
        _run_in_background(goal_id, orch.execute, goal_id)
        self._json_response({"status": "executing", "goal_id": goal_id})

    def _handle_cancel_goal(self, goal_id):
        """DELETE /api/goals/:id — 목표 취소"""
        goal, err = _require_goal(self, goal_id, reject_finished=True)
        if err:
            return
        goal = _get_engine().cancel_goal(goal_id)
        self._json_response(goal)
