"""
에러 분류 — 원시 에러 텍스트를 사용자 친화적 메시지로 변환

jobs.py에서 분리됨.
"""

import re


_ERROR_PATTERNS = [
    {
        "patterns": [r"rate.?limit", r"429", r"overloaded", r"too many requests", r"capacity"],
        "summary": "API 요청 한도 초과",
        "cause": "Claude API의 요청 제한에 도달했습니다. 단시간에 너무 많은 작업을 전송했을 수 있습니다.",
        "next_steps": ["잠시 후 다시 시도하세요 (1~2분 대기 권장)", "동시 실행 작업 수를 줄여보세요"],
    },
    {
        "patterns": [r"api.?key", r"unauthorized", r"401", r"authentication.*fail", r"invalid.*key", r"ANTHROPIC_API_KEY"],
        "summary": "API 인증 실패",
        "cause": "Claude API 키가 유효하지 않거나 설정되지 않았습니다.",
        "next_steps": ["ANTHROPIC_API_KEY 환경변수가 올바르게 설정되었는지 확인하세요", "API 키가 만료되지 않았는지 확인하세요"],
    },
    {
        "patterns": [r"permission.?denied", r"EACCES", r"Operation not permitted"],
        "summary": "파일 접근 권한 오류",
        "cause": "작업 대상 파일이나 디렉토리에 대한 읽기/쓰기 권한이 없습니다.",
        "next_steps": ["작업 디렉토리의 파일 권한을 확인하세요", "다른 프로세스가 파일을 잠그고 있지 않은지 확인하세요"],
    },
    {
        "patterns": [r"FIFO", r"Broken pipe", r"EPIPE", r"fifo.*not.*exist"],
        "summary": "서비스 통신 오류",
        "cause": "Controller 서비스와의 통신 파이프(FIFO)가 끊어졌습니다.",
        "next_steps": ["서비스를 재시작하세요", "서비스 상태를 확인하세요 (상단 연결 상태 참조)"],
    },
    {
        "patterns": [r"timed?\s*out", r"ETIMEDOUT", r"deadline.?exceeded", r"timeout"],
        "summary": "작업 시간 초과",
        "cause": "작업이 제한 시간 내에 완료되지 않았습니다. 프롬프트가 너무 복잡하거나 대상 파일이 너무 클 수 있습니다.",
        "next_steps": ["프롬프트를 더 작은 단위로 나눠서 시도하세요", "대상 범위를 줄여보세요 (특정 파일/함수 지정)"],
    },
    {
        "patterns": [r"ECONNREFUSED", r"ENOTFOUND", r"network", r"fetch.*fail", r"connection.*refused"],
        "summary": "네트워크 연결 오류",
        "cause": "외부 서비스에 연결할 수 없습니다. 네트워크가 불안정하거나 API 서버에 문제가 있을 수 있습니다.",
        "next_steps": ["인터넷 연결 상태를 확인하세요", "잠시 후 다시 시도하세요"],
    },
    {
        "patterns": [r"context.*(?:length|limit|window)", r"too.?long", r"max.*token", r"token.*limit", r"prompt.*too.*large"],
        "summary": "컨텍스트 길이 초과",
        "cause": "입력 프롬프트나 작업 대상 파일이 Claude의 처리 가능 범위를 초과했습니다.",
        "next_steps": ["프롬프트를 더 짧게 줄여보세요", "대상 파일 범위를 줄이세요 (특정 함수나 섹션만 지정)"],
    },
    {
        "patterns": [r"ENOSPC", r"no space", r"disk.*full"],
        "summary": "디스크 공간 부족",
        "cause": "서버 디스크에 여유 공간이 없어서 작업 결과를 저장할 수 없습니다.",
        "next_steps": ["불필요한 파일을 정리하세요", "'완료 삭제' 버튼으로 오래된 작업 로그를 제거하세요"],
    },
    {
        "patterns": [r"SIGKILL", r"killed", r"signal.*9", r"OOM", r"out of memory", r"ENOMEM"],
        "summary": "프로세스가 강제 종료됨",
        "cause": "작업 프로세스가 시스템에 의해 강제 종료되었습니다. 메모리 부족이 원인일 수 있습니다.",
        "next_steps": ["시스템 메모리 사용량을 확인하세요", "동시 실행 작업 수를 줄여보세요"],
    },
    {
        "patterns": [r"ENOENT", r"no such file", r"not found.*path", r"directory.*not.*exist"],
        "summary": "파일 또는 디렉토리를 찾을 수 없음",
        "cause": "작업에서 참조한 파일이나 디렉토리가 존재하지 않습니다.",
        "next_steps": ["작업 디렉토리(cwd) 경로가 올바른지 확인하세요", "대상 파일이 삭제되거나 이동되지 않았는지 확인하세요"],
    },
    {
        "patterns": [r"git.*conflict", r"merge conflict", r"CONFLICT"],
        "summary": "Git 충돌 발생",
        "cause": "작업 중 Git merge conflict가 발생했습니다.",
        "next_steps": ["충돌이 발생한 파일을 수동으로 해결하세요", "작업 전에 최신 코드를 pull하세요"],
    },
    {
        "patterns": [r"worktree.*(?:fail|error|lock)", r"already.*checked.*out"],
        "summary": "Git Worktree 오류",
        "cause": "격리 실행을 위한 Git worktree 생성에 실패했습니다.",
        "next_steps": ["기존 worktree가 정리되지 않았다면 'git worktree prune'을 실행하세요", "작업 디렉토리가 유효한 Git 저장소인지 확인하세요"],
    },
]


def classify_error(raw_text):
    """원시 에러 텍스트를 분류하여 사용자 친화적 메시지를 반환한다.

    Returns:
        dict: {"summary": str, "cause": str, "next_steps": list[str]}
        None이면 분류 불가 (에러가 아닌 경우).
    """
    if not raw_text:
        return None

    for rule in _ERROR_PATTERNS:
        for pattern in rule["patterns"]:
            if re.search(pattern, raw_text, re.IGNORECASE):
                return {
                    "summary": rule["summary"],
                    "cause": rule["cause"],
                    "next_steps": rule["next_steps"],
                }

    return {
        "summary": "작업이 실패했습니다",
        "cause": "예상하지 못한 오류가 발생했습니다.",
        "next_steps": ["아래 상세 로그를 확인하세요", "같은 프롬프트로 다시 실행해보세요"],
    }
