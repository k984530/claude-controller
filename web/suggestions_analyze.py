"""
Suggestion Analyzers — 작업 이력 분석 및 제안 생성 엔진

suggestions.py 의 코어 CRUD 와 분리하여 분석 로직만 담당한다.
generate_suggestions() 는 suggestions 모듈에서 re-export 된다.
"""

import os
import re
import time
import uuid
from collections import Counter, defaultdict

from config import LOGS_DIR
from utils import parse_meta_file

from suggestions import (
    _load_suggestions,
    _save_suggestions,
    _load_skills,
)


# ── 분석 & 제안 생성 ────────────────────────────

def generate_suggestions() -> list[dict]:
    """작업 이력을 분석하여 새로운 제안을 생성한다.

    기존 pending 제안과 중복되지 않도록 필터링한다.
    """
    existing = _load_suggestions()
    existing_pending_keys = {
        s.get("dedup_key") for s in existing
        if s.get("status") == "pending" and s.get("dedup_key")
    }

    jobs = _load_recent_jobs(limit=200)
    skills = _load_skills()
    new_suggestions = []

    # 1. 반복 프롬프트 → 스킬 제안
    new_suggestions.extend(_analyze_repeated_prompts(jobs, skills, existing_pending_keys))

    # 2. 실패 패턴 → 개선 제안
    new_suggestions.extend(_analyze_failure_patterns(jobs, skills, existing_pending_keys))

    # 3. 주기적 수동 작업 → 파이프라인 제안
    new_suggestions.extend(_analyze_periodic_tasks(jobs, existing_pending_keys))

    # 4. 스킬 커버리지 분석
    new_suggestions.extend(_analyze_skill_coverage(jobs, skills, existing_pending_keys))

    if new_suggestions:
        all_suggestions = existing + new_suggestions
        _save_suggestions(all_suggestions)

    return new_suggestions


def _load_recent_jobs(limit: int = 200) -> list[dict]:
    """최근 작업 메타 데이터를 로드한다."""
    if not LOGS_DIR.exists():
        return []
    meta_files = sorted(
        LOGS_DIR.glob("job_*.meta"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]
    jobs = []
    for mf in meta_files:
        meta = parse_meta_file(mf)
        if meta:
            jobs.append(meta)
    return jobs


def _normalize_prompt(prompt: str) -> str:
    """프롬프트를 정규화하여 유사도 비교에 사용한다."""
    # 경로, 숫자, 해시 등 제거
    text = re.sub(r'/[\w/.-]+', '<PATH>', prompt)
    text = re.sub(r'\b[0-9a-f]{8,}\b', '<HASH>', text)
    text = re.sub(r'\b\d+\b', '<NUM>', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def _extract_keywords(prompt: str, top_n: int = 5) -> list[str]:
    """프롬프트에서 주요 키워드를 추출한다."""
    stop_words = {
        '이', '그', '저', '을', '를', '에', '의', '은', '는', '가', '으로', '로',
        '해', '해서', '하고', '하세요', '합니다', '해주세요', '것', '수',
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of',
        'and', 'in', 'that', 'have', 'for', 'it', 'with', 'as', 'do',
        'this', 'but', 'or', 'if', 'from', 'they', 'we', 'you',
    }
    words = re.findall(r'[가-힣]+|[a-zA-Z_]\w{2,}', prompt.lower())
    words = [w for w in words if w not in stop_words and len(w) > 1]
    counts = Counter(words)
    return [w for w, _ in counts.most_common(top_n)]


def _make_suggestion(
    stype: str,
    title: str,
    description: str,
    action: dict,
    dedup_key: str,
    confidence: float = 0.5,
) -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "type": stype,
        "title": title,
        "description": description,
        "action": action,
        "status": "pending",
        "confidence": round(confidence, 2),
        "dedup_key": dedup_key,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── 분석 1: 반복 프롬프트 패턴 ────────────────

def _analyze_repeated_prompts(
    jobs: list[dict], skills: list[dict], existing_keys: set
) -> list[dict]:
    """유사한 프롬프트가 3회 이상 사용된 패턴을 찾아 스킬 생성을 제안한다."""
    suggestions = []

    # 프롬프트를 정규화하여 그룹핑
    prompt_groups: dict[str, list[dict]] = defaultdict(list)
    for job in jobs:
        prompt = job.get("PROMPT", "").strip()
        if not prompt or len(prompt) < 10:
            continue
        key = _normalize_prompt(prompt)
        if len(key) < 8:
            continue
        prompt_groups[key].append(job)

    # 기존 스킬 프롬프트 키워드 수집 (중복 방지용)
    skill_keywords = set()
    for cat in skills:
        for skill in cat.get("skills", []):
            for kw in _extract_keywords(skill.get("prompt", "") + " " + skill.get("name", "")):
                skill_keywords.add(kw)

    for norm_key, group_jobs in prompt_groups.items():
        if len(group_jobs) < 3:
            continue

        # 대표 프롬프트에서 키워드 추출
        sample_prompt = group_jobs[0].get("PROMPT", "")
        keywords = _extract_keywords(sample_prompt)

        # 기존 스킬과 키워드 겹침이 많으면 스킵
        overlap = len(set(keywords) & skill_keywords)
        if overlap >= len(keywords) * 0.6 and keywords:
            continue

        dedup = f"new_skill:{norm_key[:60]}"
        if dedup in existing_keys:
            continue

        # 카테고리 추론
        category = _infer_category(sample_prompt)
        name_hint = " ".join(keywords[:3]) if keywords else "반복 작업"

        # 대표 프롬프트에서 공통 패턴 추출
        common_parts = _extract_common_pattern(
            [j.get("PROMPT", "") for j in group_jobs[:5]]
        )

        confidence = min(0.4 + len(group_jobs) * 0.1, 0.95)

        suggestions.append(_make_suggestion(
            stype="new_skill",
            title=f"새 스킬 제안: {name_hint}",
            description=(
                f"유사한 프롬프트가 {len(group_jobs)}회 반복되었습니다. "
                f"스킬로 등록하면 매번 입력할 필요가 없습니다."
            ),
            action={
                "type": "new_skill",
                "payload": {
                    "category": category,
                    "name": name_hint,
                    "desc": f"반복 패턴 기반 자동 생성 ({len(group_jobs)}회 사용)",
                    "prompt": common_parts or sample_prompt[:300],
                },
            },
            dedup_key=dedup,
            confidence=confidence,
        ))

    return suggestions[:5]  # 최대 5개


# ── 분석 2: 실패 패턴 ────────────────

def _analyze_failure_patterns(
    jobs: list[dict], skills: list[dict], existing_keys: set
) -> list[dict]:
    """실패한 작업의 공통 패턴을 분석하여 개선을 제안한다."""
    suggestions = []
    failed_jobs = [j for j in jobs if j.get("STATUS") == "failed"]

    if len(failed_jobs) < 2:
        return suggestions

    # 프로젝트별 실패율 분석
    project_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "failed": 0})
    for job in jobs:
        cwd = job.get("CWD", "")
        if not cwd:
            continue
        project_stats[cwd]["total"] += 1
        if job.get("STATUS") == "failed":
            project_stats[cwd]["failed"] += 1

    for cwd, stats in project_stats.items():
        if stats["total"] < 5:
            continue
        fail_rate = stats["failed"] / stats["total"]
        if fail_rate < 0.3:
            continue

        dedup = f"failure_pattern:{cwd}"
        if dedup in existing_keys:
            continue

        project_name = os.path.basename(cwd.rstrip("/")) or cwd

        # 실패한 작업의 프롬프트에서 공통 키워드 추출
        failed_prompts = [
            j.get("PROMPT", "") for j in failed_jobs
            if j.get("CWD", "") == cwd
        ]
        keywords = _extract_keywords(" ".join(failed_prompts[:10]))

        suggestions.append(_make_suggestion(
            stype="improve_skill",
            title=f"실패율 높음: {project_name}",
            description=(
                f"프로젝트 '{project_name}'의 실패율이 {fail_rate:.0%}입니다 "
                f"({stats['failed']}/{stats['total']}건). "
                f"시스템 프롬프트에 에러 처리 지시를 추가하면 도움이 될 수 있습니다."
            ),
            action={
                "type": "new_skill",
                "payload": {
                    "category": "verify",
                    "name": f"{project_name} 에러 방지",
                    "desc": f"실패율 {fail_rate:.0%} 개선용",
                    "prompt": (
                        f"이 프로젝트({project_name})에서 작업할 때 다음을 주의하세요:\n"
                        f"1. 변경 전 기존 코드를 먼저 읽고 이해하세요\n"
                        f"2. 에러 발생 시 원인을 분석한 후 수정하세요\n"
                        f"3. 수정 후 관련 테스트를 실행하여 검증하세요"
                    ),
                },
            },
            dedup_key=dedup,
            confidence=min(0.5 + fail_rate * 0.4, 0.9),
        ))

    return suggestions[:3]


# ── 분석 3: 주기적 수동 작업 ────────────────

def _analyze_periodic_tasks(
    jobs: list[dict], existing_keys: set
) -> list[dict]:
    """수동으로 반복 실행된 작업을 찾아 파이프라인을 제안한다."""
    suggestions = []

    # 프로젝트+정규화프롬프트 조합으로 그룹핑
    task_groups: dict[str, list[float]] = defaultdict(list)
    task_prompts: dict[str, str] = {}
    task_cwds: dict[str, str] = {}

    for job in jobs:
        prompt = job.get("PROMPT", "").strip()
        cwd = job.get("CWD", "").strip()
        if not prompt or not cwd:
            continue

        # 타임스탬프 추출 (JOB_ID는 epoch 기반)
        try:
            job_id = job.get("JOB_ID", "")
            ts = float(job_id) if job_id else 0
        except (ValueError, TypeError):
            ts = 0

        if ts == 0:
            continue

        norm = _normalize_prompt(prompt)
        group_key = f"{cwd}::{norm[:80]}"
        task_groups[group_key].append(ts)
        task_prompts[group_key] = prompt
        task_cwds[group_key] = cwd

    for group_key, timestamps in task_groups.items():
        if len(timestamps) < 3:
            continue

        timestamps.sort()
        intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        if not intervals:
            continue

        avg_interval = sum(intervals) / len(intervals)
        # 최소 5분, 최대 7일 간격인 경우만
        if avg_interval < 300 or avg_interval > 604800:
            continue

        # 간격의 표준편차가 평균의 50% 이내 → 규칙적
        if len(intervals) >= 2:
            variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
            std_dev = variance ** 0.5
            if std_dev > avg_interval * 0.5:
                continue

        dedup = f"periodic:{group_key[:80]}"
        if dedup in existing_keys:
            continue

        prompt = task_prompts[group_key]
        cwd = task_cwds[group_key]
        interval_str = _seconds_to_interval(avg_interval)
        project_name = os.path.basename(cwd.rstrip("/")) or cwd

        suggestions.append(_make_suggestion(
            stype="new_pipeline",
            title=f"자동화 제안: {project_name}",
            description=(
                f"약 {interval_str} 간격으로 {len(timestamps)}회 수동 실행된 작업입니다. "
                f"파이프라인으로 등록하면 자동 실행됩니다."
            ),
            action={
                "type": "new_pipeline",
                "payload": {
                    "project": cwd,
                    "command": prompt[:500],
                    "interval": interval_str,
                    "name": f"[자동생성] {_extract_keywords(prompt, 3)}",
                },
            },
            dedup_key=dedup,
            confidence=min(0.5 + len(timestamps) * 0.08, 0.9),
        ))

    return suggestions[:3]


# ── 분석 4: 스킬 커버리지 ────────────────

def _analyze_skill_coverage(
    jobs: list[dict], skills: list[dict], existing_keys: set
) -> list[dict]:
    """빈 카테고리나 미사용 스킬을 분석한다."""
    suggestions = []

    # 빈 카테고리 확인
    category_names = {
        "plan": "기획", "dev": "개발", "design": "디자인",
        "verify": "검증", "etc": "기타",
    }
    for cat in skills:
        cat_id = cat.get("id", "")
        if not cat.get("skills") and cat_id in category_names:
            dedup = f"empty_cat:{cat_id}"
            if dedup in existing_keys:
                continue

            # 작업 이력에서 해당 카테고리와 관련된 프롬프트가 있는지
            cat_keywords = _category_keywords(cat_id)
            related_count = sum(
                1 for j in jobs
                if any(kw in j.get("PROMPT", "").lower() for kw in cat_keywords)
            )
            if related_count < 2:
                continue

            suggestions.append(_make_suggestion(
                stype="new_skill",
                title=f"'{category_names[cat_id]}' 카테고리에 스킬 추가",
                description=(
                    f"'{category_names[cat_id]}' 카테고리에 스킬이 없지만, "
                    f"관련 작업이 {related_count}건 발견되었습니다. "
                    f"자주 사용하는 지시사항을 스킬로 등록하면 효율적입니다."
                ),
                action={
                    "type": "new_skill",
                    "payload": {
                        "category": cat_id,
                        "name": f"{category_names[cat_id]} 기본",
                        "desc": f"작업 패턴 기반 자동 제안",
                        "prompt": _generate_category_prompt(cat_id),
                    },
                },
                dedup_key=dedup,
                confidence=0.4 + min(related_count * 0.05, 0.3),
            ))

    return suggestions[:2]


# ── 유틸리티 ────────────────────────────────

def _infer_category(prompt: str) -> str:
    """프롬프트 내용으로 스킬 카테고리를 추론한다."""
    p = prompt.lower()
    dev_kw = ['코드', '구현', '함수', '클래스', 'implement', 'code', 'fix', 'bug',
              'refactor', '리팩', '수정', '개발', 'feature', 'add', 'create']
    plan_kw = ['설계', '기획', 'plan', 'design doc', '문서', '스펙', '요구사항',
               'architecture', '아키텍']
    design_kw = ['UI', 'CSS', '스타일', 'layout', '디자인', 'figma', '화면']
    verify_kw = ['테스트', 'test', '검증', 'lint', '점검', 'review', 'check', '보안']

    scores = {
        'dev': sum(1 for kw in dev_kw if kw in p),
        'plan': sum(1 for kw in plan_kw if kw in p),
        'design': sum(1 for kw in design_kw if kw in p),
        'verify': sum(1 for kw in verify_kw if kw in p),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'etc'


def _category_keywords(cat_id: str) -> list[str]:
    """카테고리별 탐지 키워드를 반환한다."""
    mapping = {
        "plan": ["기획", "설계", "plan", "spec", "문서", "요구사항"],
        "dev": ["코드", "구현", "fix", "bug", "리팩", "개발", "feature"],
        "design": ["ui", "css", "스타일", "디자인", "layout", "화면"],
        "verify": ["테스트", "test", "검증", "lint", "점검", "review"],
        "etc": [],
    }
    return mapping.get(cat_id, [])


def _generate_category_prompt(cat_id: str) -> str:
    """카테고리별 기본 스킬 프롬프트를 생성한다."""
    prompts = {
        "plan": "작업을 시작하기 전에 구현 계획을 먼저 작성하세요. 변경할 파일 목록, 예상 영향 범위, 테스트 방안을 포함하세요.",
        "dev": "코드 변경 시 기존 패턴과 컨벤션을 따르세요. 불필요한 주석이나 로그를 추가하지 마세요. 변경 범위를 최소화하세요.",
        "design": "UI 변경 시 기존 디자인 시스템(CSS 변수, 컴포넌트 패턴)을 따르세요. 반응형 레이아웃을 고려하세요.",
        "verify": "코드 변경 후 관련 테스트를 실행하세요. 테스트가 없으면 주요 기능에 대한 테스트를 작성하세요.",
        "etc": "명확하고 간결하게 작업을 수행하세요.",
    }
    return prompts.get(cat_id, prompts["etc"])


def _extract_common_pattern(prompts: list[str]) -> str:
    """여러 프롬프트에서 공통 패턴을 추출한다."""
    if not prompts:
        return ""
    if len(prompts) == 1:
        return prompts[0][:300]

    # 단어 빈도 기반 공통 패턴 추출
    word_counts: Counter = Counter()
    for p in prompts:
        words = set(re.findall(r'[가-힣]+|[a-zA-Z_]\w{2,}', p.lower()))
        word_counts.update(words)

    # 모든 프롬프트에 등장하는 단어
    threshold = len(prompts) * 0.6
    common_words = {w for w, c in word_counts.items() if c >= threshold}

    if not common_words:
        return prompts[0][:300]

    # 첫 번째 프롬프트에서 공통 단어가 포함된 문장 추출
    sentences = re.split(r'[.\n]', prompts[0])
    relevant = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        sent_words = set(re.findall(r'[가-힣]+|[a-zA-Z_]\w{2,}', sent.lower()))
        if sent_words & common_words:
            relevant.append(sent)

    return "\n".join(relevant[:5]) if relevant else prompts[0][:300]


def _seconds_to_interval(seconds: float) -> str:
    """초를 사람이 읽을 수 있는 간격 문자열로 변환한다."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h"
    else:
        return f"{int(seconds / 86400)}d"
