"""
Persona Engine -- 직군별 전문가 페르소나 관리

페르소나 = 특정 전문 분야의 역할 정의 + 시스템 프롬프트.
작업(Job)이나 파이프라인에 페르소나를 배정하면,
해당 전문가의 관점/방법론이 프롬프트에 자동 주입된다.

내장 페르소나 정의: personas_builtin.py
사용자 정의 페르소나: data/personas.json에 저장
"""

import json
import os
import time

from config import DATA_DIR
from personas_builtin import BUILTIN_PERSONAS

PERSONAS_FILE = DATA_DIR / "personas.json"


# ==================================================================
#  유틸리티
# ==================================================================

def _load_custom() -> list[dict]:
    try:
        if PERSONAS_FILE.exists():
            return json.loads(PERSONAS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_custom(personas: list[dict]):
    from utils import atomic_json_save
    atomic_json_save(PERSONAS_FILE, personas)


# ==================================================================
#  CRUD
# ==================================================================

def list_personas() -> list[dict]:
    """내장 + 사용자 정의 페르소나 목록 반환 (system_prompt 제외한 요약)."""
    result = []
    for p in BUILTIN_PERSONAS:
        result.append({
            "id": p["id"],
            "name": p["name"],
            "name_en": p.get("name_en", ""),
            "role": p["role"],
            "icon": p.get("icon", "user"),
            "color": p.get("color", "#6366f1"),
            "builtin": True,
            "description": p["description"],
            "description_en": p.get("description_en", ""),
        })
    for p in _load_custom():
        result.append({
            "id": p["id"],
            "name": p["name"],
            "name_en": p.get("name_en", ""),
            "role": p.get("role", "custom"),
            "icon": p.get("icon", "user"),
            "color": p.get("color", "#6366f1"),
            "builtin": False,
            "description": p.get("description", ""),
            "description_en": p.get("description_en", ""),
        })
    return result


def get_persona(persona_id: str) -> tuple[dict | None, str | None]:
    """페르소나 상세 조회 (system_prompt 포함)."""
    for p in BUILTIN_PERSONAS:
        if p["id"] == persona_id:
            return p, None
    for p in _load_custom():
        if p["id"] == persona_id:
            return p, None
    return None, "페르소나를 찾을 수 없습니다"


def get_system_prompt(persona_id: str) -> str | None:
    """페르소나의 system_prompt만 반환. 없으면 None."""
    p, _ = get_persona(persona_id)
    if p:
        return p.get("system_prompt", "")
    return None


def create_persona(
    name: str,
    role: str = "custom",
    description: str = "",
    system_prompt: str = "",
    icon: str = "user",
    color: str = "#6366f1",
) -> tuple[dict, None]:
    """사용자 정의 페르소나 생성."""
    persona_id = f"custom-{int(time.time())}-{os.getpid()}"
    persona = {
        "id": persona_id,
        "name": name,
        "name_en": "",
        "role": role,
        "icon": icon,
        "color": color,
        "builtin": False,
        "description": description,
        "description_en": "",
        "system_prompt": system_prompt,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    customs = _load_custom()
    customs.append(persona)
    _save_custom(customs)
    return persona, None


def update_persona(persona_id: str, updates: dict) -> tuple[dict | None, str | None]:
    """사용자 정의 페르소나 수정. 내장 페르소나는 수정 불가."""
    for p in BUILTIN_PERSONAS:
        if p["id"] == persona_id:
            return None, "내장 페르소나는 수정할 수 없습니다"

    customs = _load_custom()
    for p in customs:
        if p["id"] == persona_id:
            for key in ("name", "role", "description", "system_prompt", "icon", "color"):
                if key in updates:
                    p[key] = updates[key]
            p["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save_custom(customs)
            return p, None
    return None, "페르소나를 찾을 수 없습니다"


def delete_persona(persona_id: str) -> tuple[dict | None, str | None]:
    """사용자 정의 페르소나 삭제. 내장 페르소나는 삭제 불가."""
    for p in BUILTIN_PERSONAS:
        if p["id"] == persona_id:
            return None, "내장 페르소나는 삭제할 수 없습니다"

    customs = _load_custom()
    for i, p in enumerate(customs):
        if p["id"] == persona_id:
            removed = customs.pop(i)
            _save_custom(customs)
            return removed, None
    return None, "페르소나를 찾을 수 없습니다"


def apply_persona_to_prompt(persona_id: str, user_prompt: str) -> str:
    """페르소나의 system_prompt를 사용자 프롬프트 앞에 주입한다."""
    sp = get_system_prompt(persona_id)
    if not sp:
        return user_prompt
    return f"{sp}\n\n---\n\n{user_prompt}"
