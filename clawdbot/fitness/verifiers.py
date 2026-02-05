"""Verifiers - Verify task outcomes with multiple strategies."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from clawdbot.fitness.sandbox import Sandbox, SandboxResult
from clawdbot.fitness.tasks import (
    Task,
    TaskResult,
    TaskType,
    MathTask,
    JSONTask,
    LogicTask,
    CodeTask,
)


@dataclass
class VerificationResult:
    """Result of verifying a task response."""

    passed: bool
    score: float  # 0.0-1.0 partial credit
    feedback: str
    details: dict[str, Any] = field(default_factory=dict)


class Verifier(ABC):
    """Base class for task verification."""

    @abstractmethod
    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify a task result.

        Args:
            task: The original task
            result: The bot's result

        Returns:
            VerificationResult with pass/fail and score
        """
        pass

    def _extract_answer(self, response: str, task_type: TaskType) -> str:
        """Extract the answer from a response string.

        Handles common response patterns like "The answer is X" or just "X".
        """
        response = response.strip()

        # Remove common prefixes
        prefixes = [
            "the answer is",
            "answer:",
            "result:",
            "output:",
            "solution:",
        ]
        response_lower = response.lower()
        for prefix in prefixes:
            if response_lower.startswith(prefix):
                response = response[len(prefix) :].strip()
                break

        # Remove trailing punctuation
        response = response.rstrip(".")

        return response


class MathVerifier(Verifier):
    """Verify mathematical answers with tolerance."""

    def __init__(self, tolerance: float = 0.001):
        self.tolerance = tolerance

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify a math task result."""
        if not isinstance(task, MathTask):
            return VerificationResult(
                passed=False, score=0.0, feedback="Invalid task type for MathVerifier"
            )

        try:
            # Extract numerical answer
            answer_str = self._extract_answer(result.raw_response, TaskType.MATH)

            # Try to parse as number
            # Handle fractions like "5/2"
            if "/" in answer_str and answer_str.count("/") == 1:
                num, denom = answer_str.split("/")
                answer = float(num.strip()) / float(denom.strip())
            else:
                # Remove commas from numbers like "1,000"
                answer_str = answer_str.replace(",", "")
                answer = float(answer_str)

            expected = task.get_expected_answer()

            # Check with tolerance
            if abs(answer - expected) <= self.tolerance:
                return VerificationResult(
                    passed=True,
                    score=1.0,
                    feedback="Correct answer",
                    details={"answer": answer, "expected": expected},
                )
            else:
                # Partial credit for close answers (within 10%)
                error_pct = abs(answer - expected) / max(abs(expected), 1)
                if error_pct <= 0.1:
                    return VerificationResult(
                        passed=False,
                        score=0.5,
                        feedback=f"Close but not exact: got {answer}, expected {expected}",
                        details={"answer": answer, "expected": expected, "error_pct": error_pct},
                    )
                else:
                    return VerificationResult(
                        passed=False,
                        score=0.0,
                        feedback=f"Wrong answer: got {answer}, expected {expected}",
                        details={"answer": answer, "expected": expected},
                    )

        except (ValueError, ZeroDivisionError) as e:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback=f"Could not parse answer: {e}",
                details={"raw_response": result.raw_response},
            )


class JSONVerifier(Verifier):
    """Verify JSON extraction with schema validation."""

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify a JSON task result."""
        if not isinstance(task, JSONTask):
            return VerificationResult(
                passed=False, score=0.0, feedback="Invalid task type for JSONVerifier"
            )

        try:
            # Extract JSON from response
            response = result.raw_response.strip()

            # Try to find JSON in the response (handle markdown code blocks)
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
            if json_match:
                response = json_match.group(1)

            # Parse JSON
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                # Try to extract JSON object/array from response
                obj_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response)
                if obj_match:
                    parsed = json.loads(obj_match.group(1))
                else:
                    raise

            expected = task.get_expected_answer()

            # Compare structure and values
            score, feedback = self._compare_json(parsed, expected)

            return VerificationResult(
                passed=score >= 0.9,  # Allow small discrepancies
                score=score,
                feedback=feedback,
                details={"parsed": parsed, "expected": expected},
            )

        except json.JSONDecodeError as e:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback=f"Invalid JSON: {e}",
                details={"raw_response": result.raw_response},
            )

    def _compare_json(
        self, actual: Any, expected: Any, path: str = ""
    ) -> tuple[float, str]:
        """Compare two JSON values recursively.

        Returns (score, feedback) where score is 0.0-1.0.
        """
        if type(actual) != type(expected):
            return 0.0, f"Type mismatch at {path or 'root'}: {type(actual).__name__} vs {type(expected).__name__}"

        if isinstance(expected, dict):
            if not expected:
                return 1.0 if not actual else 0.0, "Empty dict comparison"

            scores = []
            messages = []
            for key in expected:
                if key not in actual:
                    scores.append(0.0)
                    messages.append(f"Missing key: {path}.{key}" if path else f"Missing key: {key}")
                else:
                    score, msg = self._compare_json(
                        actual[key], expected[key], f"{path}.{key}" if path else key
                    )
                    scores.append(score)
                    if score < 1.0:
                        messages.append(msg)

            avg_score = sum(scores) / len(scores) if scores else 1.0
            feedback = "; ".join(messages) if messages else "Match"
            return avg_score, feedback

        elif isinstance(expected, list):
            if not expected:
                return 1.0 if not actual else 0.0, "Empty list comparison"

            if len(actual) != len(expected):
                return 0.5, f"List length mismatch at {path or 'root'}: {len(actual)} vs {len(expected)}"

            scores = []
            messages = []
            for i, (a, e) in enumerate(zip(actual, expected)):
                score, msg = self._compare_json(a, e, f"{path}[{i}]")
                scores.append(score)
                if score < 1.0:
                    messages.append(msg)

            avg_score = sum(scores) / len(scores) if scores else 1.0
            feedback = "; ".join(messages) if messages else "Match"
            return avg_score, feedback

        else:
            # Scalar comparison
            if actual == expected:
                return 1.0, "Match"
            # Fuzzy string matching
            if isinstance(expected, str) and isinstance(actual, str):
                if expected.lower() == actual.lower():
                    return 0.9, "Case mismatch"
            return 0.0, f"Value mismatch at {path or 'root'}: {actual!r} vs {expected!r}"


class LogicVerifier(Verifier):
    """Verify logic puzzle answers."""

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify a logic task result."""
        if not isinstance(task, LogicTask):
            return VerificationResult(
                passed=False, score=0.0, feedback="Invalid task type for LogicVerifier"
            )

        answer = self._extract_answer(result.raw_response, TaskType.LOGIC)
        expected = task.get_expected_answer()

        # Normalize for comparison
        answer_norm = answer.lower().strip()
        expected_norm = expected.lower().strip()

        # Check exact match
        if answer_norm == expected_norm:
            return VerificationResult(
                passed=True,
                score=1.0,
                feedback="Correct answer",
                details={"answer": answer, "expected": expected},
            )

        # Check if answer contains the expected value
        if expected_norm in answer_norm:
            return VerificationResult(
                passed=True,
                score=0.9,
                feedback="Answer contains correct value",
                details={"answer": answer, "expected": expected},
            )

        return VerificationResult(
            passed=False,
            score=0.0,
            feedback=f"Wrong answer: got '{answer}', expected '{expected}'",
            details={"answer": answer, "expected": expected},
        )


class CodeVerifier(Verifier):
    """Verify code tasks by running unit tests in sandbox."""

    def __init__(self, timeout_seconds: float = 5.0):
        self.sandbox = Sandbox(timeout_seconds=timeout_seconds)

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify a code task by running tests."""
        if not isinstance(task, CodeTask):
            return VerificationResult(
                passed=False, score=0.0, feedback="Invalid task type for CodeVerifier"
            )

        # Extract code from response
        code = self._extract_code(result.raw_response)
        if not code:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No code found in response",
                details={"raw_response": result.raw_response},
            )

        # Run tests in sandbox
        verification = task.get_verification_data()
        sandbox_result = await self.sandbox.run_tests(
            code=code,
            function_name=verification["function_name"],
            test_cases=verification["test_cases"],
        )

        if sandbox_result.timed_out:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="Code execution timed out",
                details={"code": code, "timeout": self.sandbox.timeout_seconds},
            )

        if not sandbox_result.success:
            # Calculate partial credit based on tests passed
            test_results = sandbox_result.return_value or []
            if test_results:
                passed_count = sum(1 for t in test_results if t.get("passed", False))
                total_count = len(test_results)
                score = passed_count / total_count
            else:
                score = 0.0

            return VerificationResult(
                passed=False,
                score=score,
                feedback=sandbox_result.error or "Tests failed",
                details={
                    "code": code,
                    "test_results": test_results,
                    "output": sandbox_result.output,
                },
            )

        return VerificationResult(
            passed=True,
            score=1.0,
            feedback="All tests passed",
            details={
                "code": code,
                "test_results": sandbox_result.return_value,
                "execution_time": sandbox_result.execution_time_seconds,
            },
        )

    def _extract_code(self, response: str) -> str:
        """Extract Python code from response.

        Handles markdown code blocks and raw code.
        """
        response = response.strip()

        # Try to find Python code block
        code_match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", response)
        if code_match:
            return code_match.group(1).strip()

        # Try to find a function definition
        func_match = re.search(r"(def\s+\w+[\s\S]*)", response)
        if func_match:
            code = func_match.group(1)
            # Take only the function (stop at next top-level def or end)
            lines = code.split("\n")
            func_lines = []
            in_function = False
            indent_level = 0

            for line in lines:
                if line.startswith("def "):
                    if in_function:
                        break  # Next function starts
                    in_function = True
                    func_lines.append(line)
                    indent_level = len(line) - len(line.lstrip())
                elif in_function:
                    # Check if we've exited the function
                    if line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                        if not line.startswith("def "):
                            break
                    func_lines.append(line)

            return "\n".join(func_lines).strip()

        # Return as-is if no code block found
        return response


def get_verifier(task_type: TaskType) -> Verifier:
    """Get the appropriate verifier for a task type."""
    verifiers = {
        TaskType.MATH: MathVerifier(),
        TaskType.JSON: JSONVerifier(),
        TaskType.LOGIC: LogicVerifier(),
        TaskType.CODE: CodeVerifier(),
        TaskType.HUMANEVAL: CodeVerifier(),
        TaskType.MBPP: CodeVerifier(),
        TaskType.ALGORITHM: CodeVerifier(),
        TaskType.SWE_LITE: CodeVerifier(),
    }
    return verifiers.get(task_type, MathVerifier())
