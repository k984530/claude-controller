"""
Pipeline 결과 분류 + 프롬프트 개선 — pipeline.py에서 분리

기능:
  - 실행 결과를 no_change / has_change / unknown으로 분류
  - 연속 무변경 시 프롬프트 개선 힌트 생성
"""

import re

# ── 결과 분류 패턴 ──────────────────────────────────────────────

NO_CHANGE_PATTERNS = [
    r"변경.*없",
    r"이슈.*없",
    r"문제.*없",
    r"no\s+(issues?|changes?|problems?)",
    r"nothing\s+to",
    r"all\s+ok",
    r"삭제\s*대상\s*없",
    r"개선.*없",
    r"이미.*해결",
    r"already",
    r"회귀.*없",
    r"오류\s*없",
    r"고임팩트.*없",
    # 테스트 결과 패턴
    r"(?:test|테스트).*(?:pass|통과|성공)",
    r"0\s*(?:fail|error|오류)",
    r"(?:all|모든).*(?:pass|통과|ok|정상)",
    r"ran\s+\d+\s+test.*\nok",
    # 유지보수 결과 패턴
    r"정리.*(?:없|0개|완료)",
    r"(?:디스크|disk).*(?:ok|정상|양호)",
    r"(?:상태|status).*(?:정상|양호|ok|healthy)",
    r"(?:점검|확인).*(?:완료|이상\s*없)",
    r"불필요.*없",
    r"(?:특이|이상)\s*(?:사항|점)\s*없",
    # 코드 분석 결과 패턴
    r"(?:품질|quality).*(?:양호|good|ok)",
    r"(?:취약|vuln).*(?:없|0)",
    r"(?:개선|수정)\s*(?:사항|할\s*것)\s*없",
    r"(?:추가|변경)\s*(?:불필요|사항\s*없)",
    # 일반적 무변경 표현
    r"현재\s*(?:상태|코드).*(?:적절|양호|충분)",
    r"(?:작업|할\s*것).*없",
]

# 개별 분리 — 각 키워드가 독립적으로 1점씩 기여하여
# change_score >= 2 조건이 정확하게 동작한다.
CHANGE_PATTERNS = [
    r"수정",
    r"변경",
    r"추가",
    r"개선",
    r"구현",
    r"삭제",
    r"교체",
    r"리팩",
    r"fix|change|add|remov|improv|implement|refactor",
    r"Edit|Write",  # 도구 사용 흔적
    r"작성.*완료",
    r"생성.*완료",
    r"파일.*(?:생성|작성|수정)",
    r"커밋|commit",
]


def classify_result(result_text: str) -> str:
    """결과를 분류한다: 'no_change', 'has_change', 'unknown'

    양쪽 패턴을 모두 체크한 뒤 점수로 판정한다.
    change_score >= 2 이면 no_change 패턴이 있어도 has_change 우선.
    """
    if not result_text:
        return "unknown"
    text = result_text[:2000].lower()

    # 변경 있음 점수 집계
    change_score = 0
    for pat in CHANGE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            change_score += 1

    # 변경 있음이 강하면 (2개 이상 매칭) 우선 반환
    if change_score >= 2:
        return "has_change"

    # 변경 없음 패턴 체크
    for pat in NO_CHANGE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "no_change"

    if change_score >= 1:
        return "has_change"

    return "unknown"


def count_consecutive_idle(pipe: dict) -> int:
    """히스토리에서 최근 연속 무변경 횟수를 계산한다."""
    count = 0
    for h in reversed(pipe.get("history", [])):
        if h.get("classification", "unknown") in ("no_change", "unknown"):
            count += 1
        else:
            break
    return count


def build_refinement_hint(consecutive_idle: int) -> str:
    """연속 무변경 횟수에 따라 프롬프트 개선 힌트를 생성한다."""
    if consecutive_idle <= 0:
        return ""
    if consecutive_idle == 1:
        return (
            "[프롬프트 개선] 이전 실행에서 변경사항을 발견하지 못했습니다. "
            "더 꼼꼼히 점검하고, 사소한 개선점도 찾아보세요."
        )
    if consecutive_idle == 2:
        return (
            "[프롬프트 개선] 연속 2회 변경사항 없음. 다른 관점에서 접근하세요: "
            "코드 품질, 성능, 보안, 문서화 등 이전에 확인하지 않은 영역을 살펴보세요."
        )
    return (
        f"[프롬프트 개선] 연속 {consecutive_idle}회 변경사항 없음. "
        "근본적으로 다른 접근이 필요합니다. 최근 변경 이력을 분석하고, "
        "잠재적 기술 부채나 아키텍처 개선점을 발굴하세요. "
        "새로운 문제를 찾지 못하면 현재 상태가 양호한 이유를 구체적으로 설명하세요."
    )
