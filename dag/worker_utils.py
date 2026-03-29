"""
Worker 공통 유틸리티 — Dispatcher와 DAGExecutor가 공유하는 로직

추출 대상:
  - Worker 도구 맵 (_WORKER_TOOLS)
  - 비용 파싱 (parse_cost)
  - 시스템 프롬프트 로딩 (load_system_prompt)
  - 재시도 프롬프트 생성 (augment_retry_prompt)
  - CLI 명령 빌드 (build_claude_cmd)
"""

import json
from pathlib import Path

# Worker 유형별 허용 도구
WORKER_TOOLS = {
    "analyst": "Read,Glob,Grep,Bash",
    "coder": "Bash,Read,Write,Edit,Glob,Grep",
    "tester": "Bash,Read,Write,Edit,Glob,Grep",
    "reviewer": "Read,Glob,Grep,Bash",
    "writer": "Read,Write,Edit,Glob,Grep",
}
DEFAULT_TOOLS = "Bash,Read,Write,Edit,Glob,Grep"


def tools_for_worker(worker_type: str) -> str:
    """Worker 유형에 따른 허용 도구 문자열을 반환한다."""
    return WORKER_TOOLS.get(worker_type, DEFAULT_TOOLS)


def parse_cost(output_path: str) -> float:
    """claude --output-format json 출력 파일에서 비용을 추출한다."""
    try:
        with open(output_path) as f:
            data = json.load(f)
        return float(data.get("cost_usd", 0) or 0)
    except (json.JSONDecodeError, FileNotFoundError, KeyError, ValueError):
        return 0.0


def parse_result(output_path: str) -> str | None:
    """출력 파일에서 결과 텍스트를 추출한다."""
    try:
        with open(output_path) as f:
            data = json.load(f)
        return data.get("result", None)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def load_system_prompt(prompts_dir: Path, worker_type: str) -> str:
    """Worker 유형별 시스템 프롬프트를 파일에서 로드한다."""
    path = prompts_dir / f"{worker_type}.md"
    if path.exists():
        return path.read_text()
    return ""


def augment_retry_prompt(prompt: str, retries: int, max_retries: int) -> str:
    """재시도 시 프롬프트에 실패 맥락을 추가한다."""
    return (
        f"[재시도 {retries}/{max_retries}] "
        f"이전 시도가 실패했습니다. 다른 접근 방식을 시도하세요.\n\n"
        f"원래 태스크:\n{prompt}"
    )


def build_claude_cmd(
    claude_bin: str,
    prompt: str,
    worker_type: str,
    system_prompt: str = "",
) -> list[str]:
    """claude -p CLI 명령을 조립한다."""
    cmd = [
        claude_bin,
        "-p", prompt,
        "--output-format", "json",
        "--allowedTools", tools_for_worker(worker_type),
    ]
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])
    return cmd
