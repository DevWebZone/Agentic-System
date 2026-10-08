from __future__ import annotations

import re
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PASSED_PATTERN = re.compile(r"(\d+) passed")
FAILED_PATTERN = re.compile(r"(\d+) failed")


@dataclass(frozen=True)
class PytestRunResult:
    passed: bool
    exit_code: int
    tests_passed: int
    tests_failed: int
    duration_seconds: float
    output_tail: list[str]
    command: list[str]
    reason: str | None = None

    def to_artifact(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "exit_code": self.exit_code,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "duration_seconds": self.duration_seconds,
            "output_tail": self.output_tail,
            "command": self.command,
            "reason": self.reason,
        }


def run_pytest(
    *,
    working_directory: Path,
    targets: list[str],
    timeout_seconds: int = 120,
    env: Mapping[str, str] | None = None,
) -> PytestRunResult:
    command = [sys.executable, "-m", "pytest", *targets]
    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=working_directory,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return PytestRunResult(
            passed=False,
            exit_code=-1,
            tests_passed=0,
            tests_failed=0,
            duration_seconds=round(time.perf_counter() - started_at, 3),
            output_tail=_tail_lines(output),
            command=command,
            reason="timeout",
        )

    output = completed.stdout + completed.stderr
    tests_passed, tests_failed = _parse_summary(output)
    return PytestRunResult(
        passed=completed.returncode == 0,
        exit_code=completed.returncode,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        duration_seconds=round(time.perf_counter() - started_at, 3),
        output_tail=_tail_lines(output),
        command=command,
        reason=None,
    )


def _parse_summary(output: str) -> tuple[int, int]:
    tests_passed = 0
    tests_failed = 0
    for line in output.splitlines():
        passed_match = PASSED_PATTERN.search(line)
        failed_match = FAILED_PATTERN.search(line)
        if passed_match is not None:
            tests_passed = int(passed_match.group(1))
        if failed_match is not None:
            tests_failed = int(failed_match.group(1))
    return tests_passed, tests_failed


def _tail_lines(output: str, *, line_count: int = 40) -> list[str]:
    lines = output.splitlines()
    return lines[-line_count:]