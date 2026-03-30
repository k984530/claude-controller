"""
Suggestion Engine — 스킬/자동화 개선 제안 생성 및 관리

작업 이력(logs/job_*.meta)과 현재 스킬/파이프라인을 분석하여
개선 제안을 자동 생성한다. 사용자가 각 제안을 적용 또는 무시할 수 있다.

제안 유형:
  - new_skill     : 반복 프롬프트 패턴 → 새 스킬 생성 제안
  - improve_skill : 실패율 높은 스킬 → 프롬프트 개선 제안
  - new_pipeline  : 주기적 수동 작업 → 자동화 파이프라인 제안
  - cleanup       : 미사용 스킬/파이프라인 정리 제안
"""

import json
import time
from pathlib import Path

from config import SKILLS_FILE, DATA_DIR


SUGGESTIONS_FILE = DATA_DIR / "suggestions.json"

# ── JSON list I/O (공통 헬퍼) ─────────────────

def _load_json_list(filepath: Path) -> list[dict]:
    if not filepath.exists():
        return []
    try:
        data = json.loads(filepath.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_json_list(filepath: Path, items: list[dict]):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), "utf-8",
    )


def _load_suggestions() -> list[dict]:
    return _load_json_list(SUGGESTIONS_FILE)


def _save_suggestions(suggestions: list[dict]):
    _save_json_list(SUGGESTIONS_FILE, suggestions)


def list_suggestions(status: str | None = None) -> list[dict]:
    """제안 목록을 반환한다. status 필터 가능 (pending/applied/dismissed)."""
    suggestions = _load_suggestions()
    if status:
        suggestions = [s for s in suggestions if s.get("status") == status]
    return suggestions



def dismiss_suggestion(suggestion_id: str) -> bool:
    suggestions = _load_suggestions()
    for s in suggestions:
        if s.get("id") == suggestion_id:
            s["status"] = "dismissed"
            s["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_suggestions(suggestions)
            return True
    return False


def delete_suggestion(suggestion_id: str) -> bool:
    suggestions = _load_suggestions()
    before = len(suggestions)
    suggestions = [s for s in suggestions if s.get("id") != suggestion_id]
    if len(suggestions) < before:
        _save_suggestions(suggestions)
        return True
    return False


def clear_dismissed():
    """무시된 제안을 모두 삭제한다."""
    suggestions = _load_suggestions()
    suggestions = [s for s in suggestions if s.get("status") != "dismissed"]
    _save_suggestions(suggestions)
    return True


# ── 제안 적용 ────────────────────────────────

def apply_suggestion(suggestion_id: str) -> tuple[dict | None, str | None]:
    """제안을 적용한다. 성공 시 (result_dict, None), 실패 시 (None, error_msg)."""
    suggestions = _load_suggestions()
    target = None
    for s in suggestions:
        if s.get("id") == suggestion_id:
            target = s
            break
    if not target:
        return None, "제안을 찾을 수 없습니다"
    if target.get("status") != "pending":
        return None, "이미 처리된 제안입니다"

    action = target.get("action", {})
    action_type = action.get("type", "")

    try:
        if action_type == "new_skill":
            result = _apply_new_skill(action.get("payload", {}))
        elif action_type == "improve_skill":
            result = _apply_improve_skill(action.get("payload", {}))
        elif action_type == "new_pipeline":
            result = _apply_new_pipeline(action.get("payload", {}))
        elif action_type == "cleanup_skill":
            result = _apply_cleanup_skill(action.get("payload", {}))
        else:
            return None, f"알 수 없는 액션 유형: {action_type}"

        target["status"] = "applied"
        target["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_suggestions(suggestions)
        return result, None

    except Exception as e:
        return None, f"적용 실패: {e}"


def _apply_new_skill(payload: dict) -> dict:
    """새 스킬을 skills.json에 추가한다."""
    skills = _load_skills()
    category_id = payload.get("category", "etc")
    skill_data = {
        "id": f"{category_id}-{int(time.time())}",
        "name": payload.get("name", "새 스킬"),
        "desc": payload.get("desc", ""),
        "prompt": payload.get("prompt", ""),
    }

    # 해당 카테고리 찾기
    for cat in skills:
        if cat.get("id") == category_id:
            cat.setdefault("skills", []).append(skill_data)
            break
    else:
        # 카테고리 없으면 '기타'에 추가
        for cat in skills:
            if cat.get("id") == "etc":
                cat.setdefault("skills", []).append(skill_data)
                break

    _save_skills(skills)
    return {"created_skill": skill_data}


def _apply_improve_skill(payload: dict) -> dict:
    """기존 스킬의 프롬프트를 개선한다."""
    skills = _load_skills()
    skill_id = payload.get("skill_id", "")
    new_prompt = payload.get("prompt", "")
    append_text = payload.get("append", "")

    for cat in skills:
        for skill in cat.get("skills", []):
            if skill.get("id") == skill_id:
                if new_prompt:
                    skill["prompt"] = new_prompt
                elif append_text:
                    skill["prompt"] = (skill.get("prompt", "") + "\n\n" + append_text).strip()
                _save_skills(skills)
                return {"updated_skill": skill}

    return {"error": "스킬을 찾을 수 없습니다"}


def _apply_new_pipeline(payload: dict) -> dict:
    """새 파이프라인을 생성한다."""
    from pipeline_crud import create_pipeline
    pipe, err = create_pipeline(
        project_path=payload.get("project", ""),
        command=payload.get("command", ""),
        interval=payload.get("interval", "5m"),
        name=payload.get("name", ""),
    )
    if err:
        raise RuntimeError(err)
    return {"created_pipeline": pipe}


def _apply_cleanup_skill(payload: dict) -> dict:
    """미사용 스킬을 삭제한다."""
    skills = _load_skills()
    skill_id = payload.get("skill_id", "")
    removed = None
    for cat in skills:
        original_len = len(cat.get("skills", []))
        cat["skills"] = [s for s in cat.get("skills", []) if s.get("id") != skill_id]
        if len(cat["skills"]) < original_len:
            removed = skill_id
            break
    if removed:
        _save_skills(skills)
    return {"removed_skill": removed}


# ── Skills I/O ────────────────────────────────

def _load_skills() -> list[dict]:
    return _load_json_list(SKILLS_FILE)


def _save_skills(skills: list[dict]):
    _save_json_list(SKILLS_FILE, skills)


# ── 분석 엔진 (suggestions_analyze 에서 re-export) ────────────
from suggestions_analyze import generate_suggestions  # noqa: F401
