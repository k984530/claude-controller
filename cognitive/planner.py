"""
Planner — 목표를 실행 가능한 태스크 DAG로 변환
Claude를 사용하여 목표를 분석하고, 태스크를 분해하며, 의존성을 추론한다.

동작 방식:
  1. Goal + 코드베이스 맥락 + Memory를 수집
  2. Claude -p에게 구조화된 프롬프트로 DAG 생성 요청
  3. 응답 JSON을 파싱하여 TaskDAG 객체 생성
  4. DAG 유효성 검증 후 Goal에 연결
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from dag.graph import TaskDAG, TaskNode


PLANNER_SYSTEM_PROMPT = """당신은 소프트웨어 개발 프로젝트의 태스크 플래너입니다.

주어진 목표(Goal)를 분석하여 실행 가능한 태스크들로 분해하고,
각 태스크 간의 의존성을 DAG(방향성 비순환 그래프)로 구성합니다.

## 규칙

1. 각 태스크는 하나의 Claude headless 세션에서 완료 가능한 크기여야 한다
2. 태스크 간 의존성을 명확히 정의한다 (같은 파일 수정 시 직렬화)
3. 병렬 실행 가능한 태스크는 가능한 병렬로 구성한다
4. Worker 유형을 적절히 배정한다: analyst, coder, tester, reviewer, writer
5. 총 태스크 수는 {max_tasks}개 이하로 유지한다
6. 각 태스크의 프롬프트는 구체적이고 실행 가능해야 한다

## Worker 유형

- **analyst**: 코드 분석, 구조 파악, 영향 범위 조사 (읽기 전용)
- **coder**: 코드 작성/수정 (쓰기 작업)
- **tester**: 테스트 작성 및 실행
- **reviewer**: 코드 리뷰, 품질 검증
- **writer**: 문서 작성

## 출력 형식

반드시 아래 JSON 형식으로만 응답하세요:

```json
{{
  "success_criteria": ["기준1", "기준2"],
  "tasks": [
    {{
      "id": "t1",
      "name": "짧은 태스크 이름",
      "worker_type": "analyst|coder|tester|reviewer|writer",
      "prompt": "구체적인 실행 프롬프트",
      "depends_on": []
    }},
    {{
      "id": "t2",
      "name": "다음 태스크",
      "worker_type": "coder",
      "prompt": "구체적인 프롬프트",
      "depends_on": ["t1"]
    }}
  ]
}}
```
"""


class Planner:
    """목표를 태스크 DAG로 변환하는 계획 엔진."""

    def __init__(self, claude_bin: str, config: Optional[dict] = None):
        self.claude_bin = claude_bin
        self.config = config or {}
        self.prompts_dir = Path(__file__).parent / "prompts"

    def create_plan(
        self,
        objective: str,
        cwd: str,
        memory_context: list[dict] = None,
        max_tasks: int = 20,
    ) -> tuple[TaskDAG, list[str]]:
        """목표로부터 태스크 DAG를 생성한다.

        Args:
            objective: 자연어 목표
            cwd: 작업 디렉토리
            memory_context: 관련 메모리 목록
            max_tasks: 최대 태스크 수

        Returns:
            (TaskDAG, success_criteria)
        """
        prompt = self._build_prompt(objective, cwd, memory_context, max_tasks)
        response = self._call_claude(prompt, cwd)
        dag, criteria = self._parse_response(response)
        return dag, criteria

    def _build_prompt(
        self,
        objective: str,
        cwd: str,
        memory_context: Optional[list[dict]],
        max_tasks: int,
    ) -> str:
        """Planner용 프롬프트를 조립한다."""
        parts = [
            f"# 목표\n{objective}\n",
            f"# 작업 디렉토리\n{cwd}\n",
        ]

        if memory_context:
            parts.append("# 관련 지식 (Memory)\n")
            for mem in memory_context[:5]:
                parts.append(
                    f"- [{mem['type']}] {mem['title']}: {mem['content'][:200]}\n"
                )

        parts.append(
            f"\n위 목표를 달성하기 위한 태스크 DAG를 생성하세요. "
            f"최대 {max_tasks}개 태스크로 제한합니다."
        )

        return "\n".join(parts)

    def _call_claude(self, prompt: str, cwd: str) -> str:
        """Claude headless를 호출하여 계획을 생성한다."""
        system_prompt = PLANNER_SYSTEM_PROMPT.format(
            max_tasks=self.config.get("max_tasks", 20)
        )

        cmd = [
            self.claude_bin,
            "-p", prompt,
            "--output-format", "json",
            "--allowedTools", "Read,Glob,Grep,Bash",
        ]

        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])

        env = os.environ.copy()
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Planner claude call failed: {result.stderr[:500]}")

        return result.stdout

    def _parse_response(self, response: str) -> tuple[TaskDAG, list[str]]:
        """Claude 응답에서 DAG를 파싱한다."""
        # JSON 블록 추출 (```json ... ``` 또는 순수 JSON)
        text = response.strip()

        # output-format json일 경우 최상위 JSON 파싱
        try:
            outer = json.loads(text)
            if "result" in outer:
                text = outer["result"]
            elif "content" in outer:
                # content 배열에서 텍스트 추출
                for block in outer.get("content", []):
                    if block.get("type") == "text":
                        text = block["text"]
                        break
        except (json.JSONDecodeError, TypeError):
            pass

        # ```json``` 블록 추출
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        data = json.loads(text)
        criteria = data.get("success_criteria", [])

        dag = TaskDAG()
        for td in data.get("tasks", []):
            dag.add_task(TaskNode(
                task_id=td["id"],
                name=td["name"],
                worker_type=td["worker_type"],
                prompt=td["prompt"],
                depends_on=td.get("depends_on", []),
            ))

        valid, msg = dag.validate()
        if not valid:
            raise ValueError(f"Invalid DAG: {msg}")

        return dag, criteria
