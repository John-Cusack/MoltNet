"""Server-side verification for Task Shop assignments.

Verifies bot submissions by running test cases (coding) or comparing
against ground truth (math). Works with text responses from any backend.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from clawdbot.fitness.sandbox import Sandbox, SandboxResult
from taskshop.config import settings


@dataclass
class VerificationResult:
    """Result of verifying a submission."""

    passed: bool
    score: float  # 0.0-1.0
    feedback: str
    details: dict[str, Any] | None = None


def extract_python_code(response: str) -> str | None:
    """Extract Python code from a bot's text response.

    Looks for ```python ... ``` blocks. Falls back to the entire
    response if no code block is found but it looks like Python code.
    """
    # Try to find ```python blocks
    pattern = r"```python\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        # Return the last code block (most likely the final answer)
        return matches[-1].strip()

    # Try generic ``` blocks
    pattern = r"```\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        # Check if any look like Python
        for match in reversed(matches):
            if "def " in match or "import " in match or "return " in match:
                return match.strip()

    # If response itself looks like Python code
    lines = response.strip().split("\n")
    if any(line.strip().startswith(("def ", "class ", "import ", "from ")) for line in lines):
        return response.strip()

    return None


def extract_math_answer(response: str) -> str | None:
    r"""Extract numeric answer from a bot's text response.

    Looks for:
    - ANSWER: <value>
    - \boxed{<value>}
    - The answer is <value>
    - Final answer: <value>
    """
    # Try ANSWER: pattern first
    match = re.search(r"ANSWER:\s*(.+?)(?:\n|$)", response)
    if match:
        return match.group(1).strip()

    # Try \boxed{} pattern
    match = re.search(r"\\boxed\{(.+?)\}", response)
    if match:
        return match.group(1).strip()

    # Try "the answer is" / "final answer:" pattern
    match = re.search(
        r"(?:the|final)\s+answer\s*(?:is|:)\s*(.+?)(?:\.|,|\n|$)", response, re.I
    )
    if match:
        return match.group(1).strip()

    # Try "= <number>" at end of lines (use last match)
    matches = re.findall(r"=\s*([-+]?\d+\.?\d*)\s*$", response, re.MULTILINE)
    if matches:
        return matches[-1].strip()

    return None


def normalize_math_answer(answer: str) -> float | None:
    """Normalize a math answer string to a float for comparison."""
    # Remove common formatting
    answer = answer.strip().replace(",", "").replace("$", "").replace("%", "")
    answer = answer.replace("\\", "").replace("{", "").replace("}", "")

    # Handle fractions like "3/4"
    if "/" in answer:
        parts = answer.split("/")
        if len(parts) == 2:
            try:
                return float(parts[0]) / float(parts[1])
            except (ValueError, ZeroDivisionError):
                pass

    try:
        return float(answer)
    except ValueError:
        return None


async def verify_coding_task(
    code: str,
    test_code: str,
    setup_code: str | None = None,
) -> VerificationResult:
    """Verify a coding task by running test cases in sandbox.

    Args:
        code: The bot's submitted code
        test_code: Test code with assertions (from benchmark)
        setup_code: Optional setup code to run before tests

    Returns:
        VerificationResult with pass/fail and score
    """
    sandbox = Sandbox(timeout_seconds=settings.verification_timeout)

    # Combine setup + user code + tests
    full_code = ""
    if setup_code:
        full_code += setup_code + "\n\n"
    full_code += code

    result: SandboxResult = await sandbox.execute(full_code, test_code)

    if result.timed_out:
        return VerificationResult(
            passed=False,
            score=0.0,
            feedback="Code execution timed out.",
            details={"timed_out": True, "timeout": settings.verification_timeout},
        )

    if result.success:
        return VerificationResult(
            passed=True,
            score=1.0,
            feedback="All tests passed.",
            details={
                "execution_time": result.execution_time_seconds,
                "output": result.output[:500] if result.output else "",
            },
        )

    return VerificationResult(
        passed=False,
        score=0.0,
        feedback=f"Tests failed: {result.error[:500]}",
        details={
            "error": result.error[:1000],
            "output": result.output[:500] if result.output else "",
        },
    )


async def verify_math_task(
    response: str,
    ground_truth: str,
    tolerance: float = 1e-6,
) -> VerificationResult:
    """Verify a math task by comparing against ground truth.

    Args:
        response: The bot's full text response
        ground_truth: The expected answer
        tolerance: Numeric comparison tolerance

    Returns:
        VerificationResult with pass/fail and score
    """
    extracted = extract_math_answer(response)
    if extracted is None:
        return VerificationResult(
            passed=False,
            score=0.0,
            feedback="Could not extract answer from response. "
            "Use 'ANSWER: <value>' format.",
        )

    # Try numeric comparison
    bot_value = normalize_math_answer(extracted)
    truth_value = normalize_math_answer(ground_truth)

    if bot_value is not None and truth_value is not None:
        if truth_value == 0:
            is_close = abs(bot_value) < tolerance
        else:
            is_close = abs(bot_value - truth_value) / max(abs(truth_value), 1e-10) < tolerance

        if is_close:
            return VerificationResult(
                passed=True,
                score=1.0,
                feedback="Correct answer.",
                details={"extracted": extracted, "expected": ground_truth},
            )
        else:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback=f"Incorrect. Got {extracted}, expected {ground_truth}.",
                details={"extracted": extracted, "expected": ground_truth},
            )

    # Fall back to exact string comparison (for symbolic answers)
    if extracted.strip().lower() == ground_truth.strip().lower():
        return VerificationResult(
            passed=True,
            score=1.0,
            feedback="Correct answer (exact match).",
            details={"extracted": extracted, "expected": ground_truth},
        )

    return VerificationResult(
        passed=False,
        score=0.0,
        feedback=f"Incorrect. Got '{extracted}', expected '{ground_truth}'.",
        details={"extracted": extracted, "expected": ground_truth},
    )


def extract_reading_answer(response: str) -> str | None:
    """Extract answer from a reading comprehension response.

    Looks for ANSWER: <value> pattern.
    """
    match = re.search(r"ANSWER:\s*(.+?)(?:\n|$)", response)
    if match:
        return match.group(1).strip()

    # Try "the answer is" pattern
    match = re.search(
        r"(?:the|my|final)\s+answer\s*(?:is|:)\s*(.+?)(?:\.|,|\n|$)", response, re.I
    )
    if match:
        return match.group(1).strip()

    return None


def _normalize_and_tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into tokens."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text.split()


def compute_f1(prediction: str, ground_truth: str) -> float:
    """Compute token-level F1 between prediction and ground truth."""
    pred_tokens = _normalize_and_tokenize(prediction)
    truth_tokens = _normalize_and_tokenize(ground_truth)
    if not pred_tokens or not truth_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(truth_tokens)
    num_common = sum(common.values())
    if num_common == 0:
        return 0.0
    precision = num_common / len(pred_tokens)
    recall = num_common / len(truth_tokens)
    return 2 * precision * recall / (precision + recall)


async def verify_reading_task(
    response: str,
    ground_truth: str,
    metadata: dict[str, Any] | None = None,
) -> VerificationResult:
    """Verify a reading comprehension task.

    Routes by answer type:
    - multiple_choice: exact letter match (A/B/C/D)
    - boolean: exact yes/no match
    - extractive/abstractive: F1 token overlap
    - unanswerable: check if response indicates unanswerable
    """
    metadata = metadata or {}
    answer_type = metadata.get("answer_type", "")

    extracted = extract_reading_answer(response)
    if extracted is None:
        return VerificationResult(
            passed=False,
            score=0.0,
            feedback="Could not extract answer from response. "
            "Use 'ANSWER: <your answer>' format.",
        )

    # Multiple choice (SciQ)
    if answer_type == "multiple_choice":
        # Normalize: take just the first letter
        pred_letter = extracted.strip().upper()[:1]
        expected_letter = ground_truth.strip().upper()[:1]
        correct = pred_letter == expected_letter
        feedback = (
            "Correct!" if correct
            else f"Incorrect. Expected {expected_letter}, got {pred_letter}."
        )
        return VerificationResult(
            passed=correct,
            score=1.0 if correct else 0.0,
            feedback=feedback,
            details={"extracted": pred_letter, "expected": expected_letter},
        )

    # Boolean (yes/no)
    if answer_type == "boolean":
        pred = extracted.strip().lower()
        expected = ground_truth.strip().lower()
        correct = pred == expected
        return VerificationResult(
            passed=correct,
            score=1.0 if correct else 0.0,
            feedback="Correct!" if correct else f"Incorrect. Expected '{expected}', got '{pred}'.",
            details={"extracted": pred, "expected": expected},
        )

    # Unanswerable
    if answer_type == "unanswerable":
        unanswerable_indicators = [
            "unanswerable", "cannot be answered", "not answerable",
            "no answer", "not enough information", "cannot determine",
        ]
        pred_lower = extracted.lower()
        is_unanswerable = any(ind in pred_lower for ind in unanswerable_indicators)
        feedback = (
            "Correct - question is unanswerable." if is_unanswerable
            else "Incorrect. This question is unanswerable."
        )
        return VerificationResult(
            passed=is_unanswerable,
            score=1.0 if is_unanswerable else 0.0,
            feedback=feedback,
            details={"extracted": extracted, "expected": "unanswerable"},
        )

    # Extractive / Abstractive: F1 scoring
    f1 = compute_f1(extracted, ground_truth)
    passed = f1 >= 0.4
    return VerificationResult(
        passed=passed,
        score=f1,
        feedback=f"F1 score: {f1:.2f}" + (" (passed)" if passed else " (below 0.4 threshold)"),
        details={"extracted": extracted, "expected": ground_truth, "f1": f1},
    )


async def verify_submission(
    category: str,
    response: str,
    test_code: str | None,
    ground_truth: str | None,
    setup_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> VerificationResult:
    """Verify a submission based on task category.

    Routes to the appropriate verification method.
    """
    if category == "coding":
        code = extract_python_code(response)
        if code is None:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No Python code found in response. "
                "Include code in a ```python block.",
            )
        if test_code is None:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No test code available for this task.",
            )
        return await verify_coding_task(code, test_code, setup_code)

    elif category == "math":
        if ground_truth is None:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No ground truth available for this task.",
            )
        return await verify_math_task(response, ground_truth)

    elif category == "reading":
        if ground_truth is None:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No ground truth available for this task.",
            )
        return await verify_reading_task(response, ground_truth, metadata)

    return VerificationResult(
        passed=False,
        score=0.0,
        feedback=f"Unknown category: {category}",
    )
