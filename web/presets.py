"""
Preset Engine -- 자동화 구조 프리셋

프리셋 = 여러 파이프라인을 묶은 템플릿.
한 번에 적용하면 프로젝트에 맞게 파이프라인 세트가 생성된다.

내장 프리셋:
  1. continuous-dev   -- 지속적 개발 (이슈 수정 + 코드 품질 + 유지보수)
  2. code-review      -- 코드 리뷰 자동화 (리뷰 + 리팩터링 사이클)
  3. docs-and-tests   -- 문서화 + 테스트 커버리지 강화
  4. security-ops     -- 보안 감사 + 취약점 모니터링
  5. full-lifecycle   -- 전체 라이프사이클 (기획 -> 개발 -> 검증 -> 정리)

사용자 정의 프리셋:
  data/presets.json에 저장 (내장 프리셋을 복제/수정하거나 새로 생성)
"""

import json
import os
import time
from pathlib import Path

from config import DATA_DIR
import pipeline as _pipeline_mod

PRESETS_FILE = DATA_DIR / "presets.json"


# ==================================================================
#  내장(built-in) 프리셋 정의
# ==================================================================

BUILTIN_PRESETS = [
    {
        "id": "continuous-dev",
        "name": "지속적 개발",
        "name_en": "Continuous Dev",
        "description": "이슈 수정, 코드 품질 개선, 유지보수를 자동 순환하는 3-파이프라인 세트",
        "description_en": "3-pipeline set: issue fix -> code quality -> maintenance cycle",
        "icon": "rocket",
        "builtin": True,
        "pipelines": [
            {
                "ref": "issue-fix",
                "name": "이슈 수정",
                "command": (
                    "프로젝트의 TODO, FIXME, 알려진 버그를 찾아 가장 중요한 1개를 수정해.\n\n"
                    "작업 순서:\n"
                    "1. grep -rn 'TODO\\|FIXME\\|HACK\\|BUG' --include='*.py' --include='*.js' --include='*.ts' --include='*.sh' . 로 이슈 목록 파악\n"
                    "2. 가장 심각한 1개를 선택\n"
                    "3. 관련 코드를 읽고 분석\n"
                    "4. 최소 범위로 수정\n\n"
                    "규칙: 한 번에 1개만. 기존 동작을 깨뜨리지 말 것."
                ),
                "interval": "5m",
                "on_complete_ref": "quality",
            },
            {
                "ref": "quality",
                "name": "코드 품질",
                "command": (
                    "코드 품질과 UX를 개선해.\n\n"
                    "작업 순서:\n"
                    "1. git log --oneline -10 으로 최근 변경사항 파악\n"
                    "2. 최근 변경된 파일을 읽고 다음 중 1가지 개선:\n"
                    "   - 에러 핸들링 보강\n"
                    "   - 코드 중복 제거\n"
                    "   - 타입/유효성 검증 추가\n"
                    "   - 사용자 경험 개선\n"
                    "3. 최소 범위로 구현\n\n"
                    "규칙: 한 번에 1가지만. 새 파일 생성보다 기존 파일 수정 우선."
                ),
                "interval": "10m",
                "on_complete_ref": None,
            },
            {
                "ref": "maintenance",
                "name": "유지보수",
                "command": (
                    "프로젝트 상태를 점검하고 유지보수 작업을 수행해.\n\n"
                    "1. 오래된 임시 파일, 로그 정리 대상 확인\n"
                    "2. 설정 파일의 일관성 점검\n"
                    "3. 의존성 버전 확인\n"
                    "4. 발견된 문제 중 안전하게 처리 가능한 1가지 수행\n\n"
                    "실제 삭제는 불필요함이 확실한 파일만. 현재 사용 중인 파일은 절대 건드리지 말 것."
                ),
                "interval": "20m",
                "on_complete_ref": None,
            },
        ],
    },
    {
        "id": "code-review",
        "name": "코드 리뷰",
        "name_en": "Code Review",
        "description": "최근 변경사항을 자동 리뷰하고 리팩터링 제안을 실행하는 2-파이프라인 세트",
        "description_en": "2-pipeline set: auto-review recent changes + execute refactoring",
        "icon": "search",
        "builtin": True,
        "pipelines": [
            {
                "ref": "review",
                "name": "코드 리뷰",
                "command": (
                    "최근 변경사항을 리뷰해.\n\n"
                    "1. git diff HEAD~3 --stat 으로 최근 변경 파일 확인\n"
                    "2. 변경된 파일들을 읽고 다음 관점에서 리뷰:\n"
                    "   - 보안 취약점 (인젝션, XSS, 경로 탈출 등)\n"
                    "   - 성능 문제 (N+1 쿼리, 불필요한 루프 등)\n"
                    "   - 에러 핸들링 누락\n"
                    "   - 코드 스타일 일관성\n"
                    "3. 발견된 문제를 심각도순으로 정리하여 보고\n"
                    "4. 가장 심각한 문제 1개를 직접 수정\n\n"
                    "리뷰 결과는 구체적 파일명:라인 형태로 지적할 것."
                ),
                "interval": "5m",
                "on_complete_ref": "refactor",
            },
            {
                "ref": "refactor",
                "name": "리팩터링",
                "command": (
                    "코드 구조를 개선하는 리팩터링을 1건 수행해.\n\n"
                    "1. git log --oneline -5 로 최근 작업 맥락 파악\n"
                    "2. 다음 중 하나를 선택하여 수행:\n"
                    "   - 긴 함수 분리 (30줄 이상)\n"
                    "   - 매직 넘버를 상수로 추출\n"
                    "   - 중복 코드 공통 함수로 추출\n"
                    "   - 네이밍 개선\n"
                    "3. 리팩터링 후 동작이 동일한지 확인\n\n"
                    "규칙: 한 번에 1건만. 동작 변경 없이 구조만 개선."
                ),
                "interval": "10m",
                "on_complete_ref": None,
            },
        ],
    },
    {
        "id": "docs-and-tests",
        "name": "문서 + 테스트",
        "name_en": "Docs & Tests",
        "description": "문서화와 테스트 커버리지를 자동으로 강화하는 2-파이프라인 세트",
        "description_en": "2-pipeline set: auto-documentation + test coverage improvement",
        "icon": "book",
        "builtin": True,
        "pipelines": [
            {
                "ref": "docs",
                "name": "문서화",
                "command": (
                    "프로젝트 문서를 개선해.\n\n"
                    "1. README.md 또는 주요 문서 파일을 읽어서 현재 상태 파악\n"
                    "2. 코드와 문서 사이의 불일치를 찾음:\n"
                    "   - 문서에 없는 새 기능\n"
                    "   - 변경된 API/설정 반영 누락\n"
                    "   - 설치/사용 방법 업데이트 필요\n"
                    "3. 가장 중요한 불일치 1건을 수정\n\n"
                    "규칙: 기존 문서 스타일 유지. 과도한 내용 추가 금지."
                ),
                "interval": "10m",
                "on_complete_ref": None,
            },
            {
                "ref": "tests",
                "name": "테스트",
                "command": (
                    "테스트 커버리지를 강화해.\n\n"
                    "1. 기존 테스트 파일들을 확인 (test_*, *_test.*, *_spec.*)\n"
                    "2. 테스트가 없거나 부족한 핵심 모듈을 식별\n"
                    "3. 가장 중요한 모듈에 대해 테스트 1-2개 추가\n"
                    "4. 추가한 테스트가 통과하는지 실행하여 확인\n\n"
                    "규칙: 기존 테스트 프레임워크/스타일 따를 것. 실행 가능한 테스트만 작성."
                ),
                "interval": "10m",
                "on_complete_ref": None,
            },
        ],
    },
    {
        "id": "security-ops",
        "name": "보안 감사",
        "name_en": "Security Ops",
        "description": "보안 취약점 스캔과 하드닝을 자동 수행하는 2-파이프라인 세트",
        "description_en": "2-pipeline set: vulnerability scanning + security hardening",
        "icon": "shield",
        "builtin": True,
        "pipelines": [
            {
                "ref": "scan",
                "name": "보안 스캔",
                "command": (
                    "보안 취약점을 스캔해.\n\n"
                    "1. 다음 패턴을 grep으로 검색:\n"
                    "   - eval(, exec(, subprocess.call(shell=True\n"
                    "   - innerHTML, dangerouslySetInnerHTML\n"
                    "   - password, secret, token 이 하드코딩된 곳\n"
                    "   - os.path.join에 사용자 입력이 직접 들어가는 곳\n"
                    "2. 발견된 항목을 OWASP 분류에 따라 심각도 판정\n"
                    "3. 가장 심각한 1건을 직접 수정\n\n"
                    "규칙: 테스트/예제 파일은 무시. 실제 서비스 코드만 대상."
                ),
                "interval": "10m",
                "on_complete_ref": "harden",
            },
            {
                "ref": "harden",
                "name": "보안 강화",
                "command": (
                    "서비스 보안을 강화해.\n\n"
                    "1. 입력 검증 로직이 빠진 API 엔드포인트를 찾음\n"
                    "2. 파일 접근 시 경로 탈출(path traversal) 방어 확인\n"
                    "3. CORS, CSP 등 보안 헤더 설정 점검\n"
                    "4. 발견된 취약점 중 1건을 방어 코드 추가로 해결\n\n"
                    "규칙: 기존 동작 깨뜨리지 않을 것. 방어 코드는 최소한으로."
                ),
                "interval": "20m",
                "on_complete_ref": None,
            },
        ],
    },
    {
        "id": "full-lifecycle",
        "name": "전체 라이프사이클",
        "name_en": "Full Lifecycle",
        "description": "기획 -> 개발 -> 검증 -> 정리 의 전체 개발 사이클을 자동화하는 4-파이프라인 세트",
        "description_en": "4-pipeline set: plan -> develop -> verify -> cleanup full cycle",
        "icon": "layers",
        "builtin": True,
        "pipelines": [
            {
                "ref": "plan",
                "name": "기획/분석",
                "command": (
                    "프로젝트를 분석하고 다음 작업을 기획해.\n\n"
                    "1. 프로젝트 구조와 최근 변경사항(git log -10) 파악\n"
                    "2. README, PLAN, TODO 등 기획 문서 확인\n"
                    "3. 현재 가장 필요한 개선사항 3가지를 우선순위별로 정리\n"
                    "4. 1순위 항목의 구현 계획을 구체적으로 작성 (파일명, 변경 내용)\n\n"
                    "결과는 PLAN.md나 TODO에 반영. 실제 코드 변경은 하지 말 것."
                ),
                "interval": "10m",
                "on_complete_ref": "develop",
            },
            {
                "ref": "develop",
                "name": "개발",
                "command": (
                    "기획된 항목 중 1개를 구현해.\n\n"
                    "1. PLAN.md, TODO 등에서 가장 우선순위 높은 미완료 항목 확인\n"
                    "2. 해당 항목의 관련 코드를 모두 읽고 분석\n"
                    "3. 최소 범위로 구현\n"
                    "4. 구현 후 해당 항목 상태를 업데이트\n\n"
                    "규칙: 한 번에 1개만. 범위 확장 금지."
                ),
                "interval": "5m",
                "on_complete_ref": "verify",
            },
            {
                "ref": "verify",
                "name": "검증",
                "command": (
                    "최근 변경사항을 검증해.\n\n"
                    "1. git diff HEAD~1 으로 최근 변경 내용 확인\n"
                    "2. 변경된 코드에 대해:\n"
                    "   - 문법 오류 확인\n"
                    "   - 엣지 케이스 검토\n"
                    "   - 기존 기능과의 호환성 확인\n"
                    "3. 테스트가 있으면 실행\n"
                    "4. 문제 발견 시 즉시 수정\n\n"
                    "규칙: 검증 범위를 최근 변경으로 한정. 무관한 코드 수정 금지."
                ),
                "interval": "5m",
                "on_complete_ref": "cleanup",
            },
            {
                "ref": "cleanup",
                "name": "정리",
                "command": (
                    "코드와 프로젝트를 정리해.\n\n"
                    "1. dead code 검출 (사용되지 않는 import, 함수, 변수)\n"
                    "2. 불필요한 console.log, print, 디버그 코드 제거\n"
                    "3. 코드 포매팅 일관성 확인\n"
                    "4. 발견된 것 중 1건 정리\n\n"
                    "규칙: 한 번에 1건만. 주석은 의미 있는 것만 남길 것."
                ),
                "interval": "10m",
                "on_complete_ref": None,
            },
        ],
    },
]


# ==================================================================
#  유틸리티
# ==================================================================

def _load_custom_presets() -> list[dict]:
    try:
        if PRESETS_FILE.exists():
            return json.loads(PRESETS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_custom_presets(presets: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(
        json.dumps(presets, ensure_ascii=False, indent=2), "utf-8"
    )


# ==================================================================
#  CRUD
# ==================================================================

def list_presets() -> list[dict]:
    """내장 + 사용자 정의 프리셋 모두 반환 (파이프라인 상세는 제외한 요약)."""
    result = []
    for p in BUILTIN_PRESETS:
        result.append({
            "id": p["id"],
            "name": p["name"],
            "name_en": p.get("name_en", ""),
            "description": p["description"],
            "description_en": p.get("description_en", ""),
            "icon": p.get("icon", "layers"),
            "builtin": True,
            "pipeline_count": len(p["pipelines"]),
            "pipeline_names": [pp["name"] for pp in p["pipelines"]],
        })
    for p in _load_custom_presets():
        result.append({
            "id": p["id"],
            "name": p["name"],
            "name_en": p.get("name_en", ""),
            "description": p["description"],
            "description_en": p.get("description_en", ""),
            "icon": p.get("icon", "layers"),
            "builtin": False,
            "pipeline_count": len(p.get("pipelines", [])),
            "pipeline_names": [pp["name"] for pp in p.get("pipelines", [])],
        })
    return result


def get_preset(preset_id: str) -> tuple[dict | None, str | None]:
    """프리셋 상세 조회 (파이프라인 템플릿 포함)."""
    for p in BUILTIN_PRESETS:
        if p["id"] == preset_id:
            return p, None
    for p in _load_custom_presets():
        if p["id"] == preset_id:
            return p, None
    return None, "프리셋을 찾을 수 없습니다"


def apply_preset(
    preset_id: str,
    project_path: str,
    overrides: dict | None = None,
) -> tuple[dict | None, str | None]:
    """프리셋을 프로젝트에 적용 -- 파이프라인 세트를 생성한다.

    Args:
        preset_id: 적용할 프리셋 ID
        project_path: 대상 프로젝트 경로
        overrides: 파이프라인별 오버라이드 (선택)
            예: {"issue-fix": {"interval": "10m"}, "quality": {"command": "..."}}

    Returns:
        (결과 dict, 에러 문자열)
    """
    preset, err = get_preset(preset_id)
    if err:
        return None, err

    project_path = os.path.abspath(os.path.expanduser(project_path))
    if not os.path.isdir(project_path):
        return None, f"디렉토리가 존재하지 않습니다: {project_path}"

    overrides = overrides or {}
    created_pipes = []
    ref_to_id = {}  # ref -> 생성된 pipeline ID (체이닝용)

    # 1단계: 파이프라인 생성 (on_complete 없이)
    for tmpl in preset["pipelines"]:
        ref = tmpl["ref"]
        ovr = overrides.get(ref, {})

        command = ovr.get("command", tmpl["command"])
        interval = ovr.get("interval", tmpl.get("interval", ""))
        name = ovr.get("name", tmpl["name"])

        pipe, pipe_err = _pipeline_mod.create_pipeline(
            project_path=project_path,
            command=command,
            interval=interval,
            name=name,
        )
        if pipe_err:
            return None, f"파이프라인 '{name}' 생성 실패: {pipe_err}"

        created_pipes.append(pipe)
        ref_to_id[ref] = pipe["id"]

    # 2단계: 체이닝 연결 (on_complete_ref -> 실제 ID)
    for tmpl, pipe in zip(preset["pipelines"], created_pipes):
        target_ref = tmpl.get("on_complete_ref")
        if target_ref and target_ref in ref_to_id:
            _pipeline_mod.update_pipeline(
                pipe["id"],
                on_complete=ref_to_id[target_ref],
            )

    return {
        "preset_id": preset_id,
        "preset_name": preset["name"],
        "project_path": project_path,
        "pipelines_created": len(created_pipes),
        "pipelines": [
            {"id": p["id"], "name": p["name"], "interval": p.get("interval")}
            for p in created_pipes
        ],
    }, None


def save_as_preset(
    name: str,
    description: str = "",
    pipeline_ids: list[str] | None = None,
) -> tuple[dict | None, str | None]:
    """현재 활성 파이프라인들을 사용자 정의 프리셋으로 저장한다.

    Args:
        name: 프리셋 이름
        description: 설명
        pipeline_ids: 저장할 파이프라인 ID 목록 (None이면 전체)
    """
    all_pipes = _pipeline_mod.list_pipelines()
    if pipeline_ids:
        pipes = [p for p in all_pipes if p["id"] in pipeline_ids]
    else:
        pipes = all_pipes

    if not pipes:
        return None, "저장할 파이프라인이 없습니다"

    # ID -> ref 매핑 생성
    id_to_ref = {}
    templates = []
    for i, p in enumerate(pipes):
        ref = f"p{i}"
        id_to_ref[p["id"]] = ref
        templates.append({
            "ref": ref,
            "name": p["name"],
            "command": p["command"],
            "interval": p.get("interval") or "",
            "on_complete_ref": None,  # 아래에서 연결
        })

    # 체이닝 복원
    for p, tmpl in zip(pipes, templates):
        chain_id = p.get("on_complete")
        if chain_id and chain_id in id_to_ref:
            tmpl["on_complete_ref"] = id_to_ref[chain_id]

    preset_id = f"custom-{int(time.time())}"
    new_preset = {
        "id": preset_id,
        "name": name,
        "name_en": "",
        "description": description,
        "description_en": "",
        "icon": "bookmark",
        "builtin": False,
        "pipelines": templates,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    customs = _load_custom_presets()
    customs.append(new_preset)
    _save_custom_presets(customs)

    return {
        "id": preset_id,
        "name": name,
        "pipeline_count": len(templates),
    }, None


def delete_preset(preset_id: str) -> tuple[dict | None, str | None]:
    """사용자 정의 프리셋 삭제. 내장 프리셋은 삭제 불가."""
    for p in BUILTIN_PRESETS:
        if p["id"] == preset_id:
            return None, "내장 프리셋은 삭제할 수 없습니다"

    customs = _load_custom_presets()
    for i, p in enumerate(customs):
        if p["id"] == preset_id:
            removed = customs.pop(i)
            _save_custom_presets(customs)
            return removed, None
    return None, "프리셋을 찾을 수 없습니다"
