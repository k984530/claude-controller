"""
Presets — 전송 폼 프리셋 저장/불러오기
스킬 + 자동화 설정 조합을 저장했다가 재사용.
"""

import json
import time

from config import PRESETS_FILE
from utils import load_json_list, save_json_list, find_skills_by_ids

# ── 저장소 I/O ──────────────────────────────────────────────

def _load() -> list[dict]:
    return load_json_list(PRESETS_FILE)


def _save(presets: list[dict]):
    save_json_list(PRESETS_FILE, presets)


def _find(preset_id: str) -> tuple[list[dict], dict | None, int]:
    presets = _load()
    for i, p in enumerate(presets):
        if p.get("id") == preset_id:
            return presets, p, i
    return presets, None, -1


# ── 스킬 해석 ───────────────────────────────────────────────

def _resolve_skill_names(skill_ids: list[str]) -> list[str]:
    """skill_ids → 사람이 읽을 수 있는 이름 목록."""
    return [s.get("name", s["id"]) for s in find_skills_by_ids(skill_ids)]


# ── 공개 API ────────────────────────────────────────────────

def list_presets() -> list[dict]:
    return _load()


def get_preset(preset_id: str) -> tuple[dict | None, str | None]:
    _, preset, _ = _find(preset_id)
    if preset is None:
        return None, "프리셋을 찾을 수 없습니다"
    return preset, None


def create_preset(name: str, config: dict, description: str = "") -> tuple[dict | None, str | None]:
    if not name:
        return None, "name 필드가 필요합니다"
    presets = _load()
    preset_id = f"preset-{int(time.time() * 1000)}"
    skill_ids = config.get("skill_ids", [])
    preset = {
        "id": preset_id,
        "name": name,
        "description": description,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config": {
            "prompt": config.get("prompt", ""),
            "cwd": config.get("cwd", ""),
            "skill_ids": skill_ids,
            "skill_names": _resolve_skill_names(skill_ids),
            "automation_mode": config.get("automation_mode", False),
            "automation_interval": config.get("automation_interval"),
            "context_mode": config.get("context_mode", "new"),
        },
    }
    presets.insert(0, preset)
    _save(presets)
    return preset, None


def update_preset(preset_id: str, **kwargs) -> tuple[dict | None, str | None]:
    presets, preset, idx = _find(preset_id)
    if preset is None:
        return None, "프리셋을 찾을 수 없습니다"
    if "name" in kwargs:
        preset["name"] = kwargs["name"]
    if "description" in kwargs:
        preset["description"] = kwargs["description"]
    if "config" in kwargs:
        cfg = kwargs["config"]
        preset["config"].update(cfg)
        skill_ids = preset["config"].get("skill_ids", [])
        preset["config"]["skill_names"] = _resolve_skill_names(skill_ids)
    preset["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    presets[idx] = preset
    _save(presets)
    return preset, None


def delete_preset(preset_id: str) -> tuple[dict | None, str | None]:
    presets, preset, idx = _find(preset_id)
    if preset is None:
        return None, "프리셋을 찾을 수 없습니다"
    presets.pop(idx)
    _save(presets)
    return preset, None
