"""
Evaluator — 자동 평가기
Worker 산출물의 품질을 자동으로 검증한다.

평가 파이프라인:
  1. 정적 분석 (lint, type check)
  2. 테스트 실행
  3. AI 코드 리뷰 (Reviewer Worker)
  4. 성공 기준 검증

Gate 모드에서는 각 단계 후 사용자 승인을 요청한다.
"""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class EvalResult:
    """단일 평가 단계의 결과."""
    step: str
    passed: bool
    details: str
    score: float = 0.0  # 0.0 ~ 1.0


@dataclass
class EvaluationReport:
    """전체 평가 보고서."""
    goal_id: str
    task_id: Optional[str]
    results: list[EvalResult] = field(default_factory=list)
    overall_pass: bool = False
    summary: str = ""

    @property
    def total_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "overall_pass": self.overall_pass,
            "total_score": round(self.total_score, 2),
            "summary": self.summary,
            "results": [
                {
                    "step": r.step,
                    "passed": r.passed,
                    "details": r.details,
                    "score": r.score,
                }
                for r in self.results
            ],
        }


class Evaluator:
    """태스크 산출물을 자동으로 평가한다."""

    def __init__(self, claude_bin: str, cwd: str):
        self.claude_bin = claude_bin
        self.cwd = cwd

    def evaluate_task(
        self,
        goal_id: str,
        task_id: str,
        worker_type: str,
        changed_files: list[str] = None,
    ) -> EvaluationReport:
        """개별 태스크의 결과를 평가한다."""
        report = EvaluationReport(goal_id=goal_id, task_id=task_id)

        # Worker 유형에 따른 평가 단계 선택
        if worker_type == "coder":
            self._eval_lint(report, changed_files)
            self._eval_tests(report)
        elif worker_type == "tester":
            self._eval_tests(report)
        elif worker_type == "reviewer":
            # Reviewer 자체는 평가 생략
            report.results.append(EvalResult(
                step="review_complete",
                passed=True,
                details="리뷰 완료",
                score=1.0,
            ))

        report.overall_pass = all(r.passed for r in report.results)
        report.summary = self._generate_summary(report)
        return report

    def evaluate_goal(
        self,
        goal_id: str,
        success_criteria: list[str],
    ) -> EvaluationReport:
        """목표 전체의 성공 기준을 검증한다.

        Claude에게 성공 기준 목록을 주고 각각 충족 여부를 판단하게 한다.
        """
        report = EvaluationReport(goal_id=goal_id, task_id=None)

        prompt = self._build_criteria_prompt(success_criteria)
        result = self._call_claude_eval(prompt)

        try:
            data = json.loads(result)
            for criterion in data.get("criteria", []):
                report.results.append(EvalResult(
                    step=f"criterion: {criterion['name']}",
                    passed=criterion.get("met", False),
                    details=criterion.get("reason", ""),
                    score=1.0 if criterion.get("met") else 0.0,
                ))
        except (json.JSONDecodeError, KeyError):
            report.results.append(EvalResult(
                step="criteria_parse",
                passed=False,
                details=f"평가 응답 파싱 실패: {result[:200]}",
                score=0.0,
            ))

        report.overall_pass = all(r.passed for r in report.results)
        report.summary = self._generate_summary(report)
        return report

    def _eval_lint(self, report: EvaluationReport, changed_files: list[str] = None):
        """린트/정적 분석을 실행한다."""
        # 프로젝트에서 사용 가능한 린터 감지
        checks = []

        # Python: ruff 또는 flake8
        if self._has_command("ruff"):
            checks.append(("ruff check .", "ruff"))
        elif self._has_command("flake8"):
            checks.append(("flake8 .", "flake8"))

        # JavaScript/TypeScript: eslint
        if Path(self.cwd, "node_modules/.bin/eslint").exists():
            checks.append(("npx eslint .", "eslint"))

        if not checks:
            report.results.append(EvalResult(
                step="lint",
                passed=True,
                details="린터 미설치 — 건너뜀",
                score=0.5,
            ))
            return

        for cmd, name in checks:
            try:
                result = subprocess.run(
                    cmd, shell=True, cwd=self.cwd,
                    capture_output=True, text=True, timeout=60,
                )
                passed = result.returncode == 0
                report.results.append(EvalResult(
                    step=f"lint_{name}",
                    passed=passed,
                    details=result.stdout[:500] if not passed else "통과",
                    score=1.0 if passed else 0.0,
                ))
            except subprocess.TimeoutExpired:
                report.results.append(EvalResult(
                    step=f"lint_{name}",
                    passed=False,
                    details="타임아웃 (60초)",
                    score=0.0,
                ))

    def _eval_tests(self, report: EvaluationReport):
        """테스트를 실행한다."""
        test_cmds = []

        # 프로젝트 유형에 따른 테스트 명령 감지
        if Path(self.cwd, "pytest.ini").exists() or Path(self.cwd, "pyproject.toml").exists():
            test_cmds.append(("python -m pytest --tb=short -q", "pytest"))
        if Path(self.cwd, "package.json").exists():
            test_cmds.append(("npm test", "npm_test"))

        if not test_cmds:
            report.results.append(EvalResult(
                step="test",
                passed=True,
                details="테스트 설정 없음 — 건너뜀",
                score=0.5,
            ))
            return

        for cmd, name in test_cmds:
            try:
                result = subprocess.run(
                    cmd, shell=True, cwd=self.cwd,
                    capture_output=True, text=True, timeout=120,
                )
                passed = result.returncode == 0
                report.results.append(EvalResult(
                    step=f"test_{name}",
                    passed=passed,
                    details=result.stdout[-500:] if not passed else "모든 테스트 통과",
                    score=1.0 if passed else 0.0,
                ))
            except subprocess.TimeoutExpired:
                report.results.append(EvalResult(
                    step=f"test_{name}",
                    passed=False,
                    details="타임아웃 (120초)",
                    score=0.0,
                ))

    def _build_criteria_prompt(self, criteria: list[str]) -> str:
        """성공 기준 검증용 프롬프트를 생성한다."""
        criteria_text = "\n".join(f"- {c}" for c in criteria)
        return f"""다음 성공 기준의 충족 여부를 코드베이스를 분석하여 판단하세요.

## 성공 기준
{criteria_text}

## 출력 형식 (JSON만)
```json
{{
  "criteria": [
    {{"name": "기준 내용", "met": true/false, "reason": "판단 근거"}}
  ]
}}
```
"""

    def _call_claude_eval(self, prompt: str) -> str:
        """Claude를 호출하여 평가를 수행한다."""
        cmd = [
            self.claude_bin,
            "-p", prompt,
            "--output-format", "json",
            "--allowedTools", "Read,Glob,Grep,Bash",
        ]

        result = subprocess.run(
            cmd, cwd=self.cwd,
            capture_output=True, text=True,
            timeout=180,
        )

        if result.returncode != 0:
            return json.dumps({"criteria": []})

        # JSON 응답에서 텍스트 추출
        try:
            outer = json.loads(result.stdout)
            if "result" in outer:
                return outer["result"]
            for block in outer.get("content", []):
                if block.get("type") == "text":
                    return block["text"]
        except (json.JSONDecodeError, TypeError):
            pass

        return result.stdout

    def _generate_summary(self, report: EvaluationReport) -> str:
        """평가 보고서의 요약을 생성한다."""
        total = len(report.results)
        passed = sum(1 for r in report.results if r.passed)
        failed_steps = [r.step for r in report.results if not r.passed]

        if report.overall_pass:
            return f"모든 평가 통과 ({passed}/{total})"
        else:
            return f"평가 실패 ({passed}/{total}) — 실패 항목: {', '.join(failed_steps)}"

    def _has_command(self, cmd: str) -> bool:
        """시스템에 명령어가 존재하는지 확인한다."""
        try:
            subprocess.run(
                ["which", cmd], capture_output=True, timeout=5,
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
