"""OpenClaw Verifiers - Verify OpenClaw task outcomes.

Provides multiple verification strategies:
- FileOutcomeVerifier: Check filesystem state
- CodeTestVerifier: Run unit tests on generated code
- SchemaVerifier: Validate JSON against schema
- LLMJudgeVerifier: Use LLM to judge subjective tasks
- FactCheckVerifier: Verify claims against known sources
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawdbot.fitness.verifiers import VerificationResult, Verifier
from clawdbot.fitness.tasks import Task, TaskResult
from clawdbot.fitness.openclaw_tasks import (
    OpenClawTask,
    OpenClawTaskType,
    VerificationType,
    CodeGenerationTask,
    FileOrganizationTask,
    DataExtractionTask,
    ScriptCreationTask,
    MathProblemTask,
    ResearchTask,
)
from clawdbot.fitness.sandbox import Sandbox


class OpenClawVerifier(Verifier):
    """Base class for OpenClaw task verification."""

    def __init__(self, workspace: Path | str | None = None):
        self.workspace = Path(workspace) if workspace else None

    def set_workspace(self, workspace: Path | str) -> None:
        """Set the workspace path for verification."""
        self.workspace = Path(workspace)


class FileOutcomeVerifier(OpenClawVerifier):
    """Verify task outcomes by checking filesystem state."""

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify file-based task outcomes."""
        if not self.workspace:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No workspace set for verification",
            )

        if not isinstance(task, OpenClawTask):
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="Invalid task type for FileOutcomeVerifier",
            )

        verification_data = task.get_verification_data()

        # Check expected files exist
        if isinstance(task, FileOrganizationTask):
            return await self._verify_file_organization(task, verification_data)

        # Check file content
        if task.expected_files:
            return await self._verify_expected_files(task)

        return VerificationResult(
            passed=True,
            score=1.0,
            feedback="File verification passed",
        )

    async def _verify_file_organization(
        self,
        task: FileOrganizationTask,
        verification_data: dict[str, Any],
    ) -> VerificationResult:
        """Verify file organization task."""
        expected_structure = verification_data.get("expected_structure", {})
        score = 0.0
        total_files = 0
        found_files = 0
        missing = []

        for folder, files in expected_structure.items():
            folder_path = self.workspace / folder
            for filename in files:
                total_files += 1
                file_path = folder_path / filename

                if file_path.exists():
                    found_files += 1
                else:
                    # Check if file exists in root (not moved)
                    if (self.workspace / filename).exists():
                        missing.append(f"{filename} (not moved to {folder}/)")
                    else:
                        missing.append(f"{folder}/{filename}")

        if total_files > 0:
            score = found_files / total_files

        passed = score >= 0.9  # Allow some tolerance

        feedback = f"Found {found_files}/{total_files} files in correct locations"
        if missing:
            feedback += f". Missing: {missing[:3]}"
            if len(missing) > 3:
                feedback += f" (+{len(missing) - 3} more)"

        return VerificationResult(
            passed=passed,
            score=score,
            feedback=feedback,
            details={"expected": expected_structure, "missing": missing},
        )

    async def _verify_expected_files(self, task: OpenClawTask) -> VerificationResult:
        """Verify expected files exist and optionally check content."""
        found = 0
        missing = []

        for filepath in task.expected_files:
            full_path = self.workspace / filepath
            if full_path.exists():
                found += 1
            else:
                missing.append(filepath)

        score = found / len(task.expected_files) if task.expected_files else 1.0
        passed = len(missing) == 0

        # Check content if specified
        content_matches = 0
        content_total = len(task.expected_content) if task.expected_content else 0

        for filepath, expected_content in task.expected_content.items():
            full_path = self.workspace / filepath
            if full_path.exists():
                actual = full_path.read_text()
                if expected_content.strip() in actual or actual.strip() == expected_content.strip():
                    content_matches += 1

        if content_total > 0:
            content_score = content_matches / content_total
            score = (score + content_score) / 2
            passed = passed and content_score >= 0.8

        return VerificationResult(
            passed=passed,
            score=score,
            feedback=f"Files: {found}/{len(task.expected_files)}, Content matches: {content_matches}/{content_total}",
            details={"missing": missing},
        )


class CodeTestVerifier(OpenClawVerifier):
    """Verify code generation by running tests."""

    def __init__(
        self,
        workspace: Path | str | None = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(workspace)
        self.sandbox = Sandbox(timeout_seconds=timeout_seconds)

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify code by running unit tests."""
        if not self.workspace:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No workspace set for verification",
            )

        if isinstance(task, CodeGenerationTask):
            return await self._verify_code_generation(task)

        if isinstance(task, ScriptCreationTask):
            return await self._verify_script(task)

        return VerificationResult(
            passed=False,
            score=0.0,
            feedback="Invalid task type for CodeTestVerifier",
        )

    async def _verify_code_generation(self, task: CodeGenerationTask) -> VerificationResult:
        """Verify generated code with test cases."""
        # Find the solution file
        solution_files = ["solution.py", "main.py", f"{task.function_name}.py"]
        code = None

        for filename in solution_files:
            filepath = self.workspace / filename
            if filepath.exists():
                code = filepath.read_text()
                break

        if code is None:
            # Check if function exists in any .py file
            for pyfile in self.workspace.glob("*.py"):
                content = pyfile.read_text()
                if f"def {task.function_name}" in content:
                    code = content
                    break

        if code is None:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No solution file found",
                details={"searched": solution_files},
            )

        # Run tests
        verification_data = task.get_verification_data()
        test_cases = verification_data.get("test_cases", [])

        sandbox_result = await self.sandbox.run_tests(
            code=code,
            function_name=task.function_name,
            test_cases=test_cases,
        )

        if sandbox_result.timed_out:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="Code execution timed out",
            )

        if sandbox_result.success:
            return VerificationResult(
                passed=True,
                score=1.0,
                feedback="All tests passed",
                details={"test_results": sandbox_result.return_value},
            )

        # Calculate partial score
        test_results = sandbox_result.return_value or []
        if test_results:
            passed_count = sum(1 for t in test_results if t.get("passed", False))
            score = passed_count / len(test_results)
        else:
            score = 0.0

        return VerificationResult(
            passed=False,
            score=score,
            feedback=sandbox_result.error or "Tests failed",
            details={"test_results": test_results, "code": code[:500]},
        )

    async def _verify_script(self, task: ScriptCreationTask) -> VerificationResult:
        """Verify script creation task."""
        # Find script files
        script_names = {
            "word_counter": ["word_counter.py", "count_words.py", "counter.py"],
            "csv_to_json": ["csv_to_json.py", "converter.py", "transform.py"],
            "batch_rename": ["batch_rename.py", "rename.py", "renamer.py"],
        }

        candidates = script_names.get(task.script_description, ["script.py", "main.py"])
        script_path = None

        for name in candidates:
            path = self.workspace / name
            if path.exists():
                script_path = path
                break

        if script_path is None:
            # Check any .py file
            for pyfile in self.workspace.glob("*.py"):
                script_path = pyfile
                break

        if script_path is None:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No script file found",
            )

        # For now, just verify the script exists and is syntactically valid
        code = script_path.read_text()

        try:
            compile(code, str(script_path), "exec")
        except SyntaxError as e:
            return VerificationResult(
                passed=False,
                score=0.2,
                feedback=f"Script has syntax errors: {e}",
            )

        # Script exists and is valid Python
        return VerificationResult(
            passed=True,
            score=0.8,  # Partial credit - full verification would run the script
            feedback="Script created and has valid syntax",
            details={"script_path": str(script_path)},
        )


class SchemaVerifier(OpenClawVerifier):
    """Verify JSON output against a schema."""

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify JSON output matches expected schema and values."""
        if not self.workspace:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No workspace set for verification",
            )

        if not isinstance(task, DataExtractionTask):
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="Invalid task type for SchemaVerifier",
            )

        # Find output file
        output_files = ["output.json", "result.json", "data.json"]
        output_data = None

        for filename in output_files:
            filepath = self.workspace / filename
            if filepath.exists():
                try:
                    output_data = json.loads(filepath.read_text())
                    break
                except json.JSONDecodeError:
                    pass

        if output_data is None:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No valid JSON output file found",
            )

        # Compare with expected output
        expected = task.expected_output
        score, feedback = self._compare_json(output_data, expected)

        return VerificationResult(
            passed=score >= 0.9,
            score=score,
            feedback=feedback,
            details={"actual": output_data, "expected": expected},
        )

    def _compare_json(self, actual: Any, expected: Any, path: str = "") -> tuple[float, str]:
        """Compare two JSON values recursively."""
        if type(actual) != type(expected):
            return 0.0, f"Type mismatch at {path or 'root'}"

        if isinstance(expected, dict):
            if not expected:
                return 1.0 if not actual else 0.0, "Empty dict"

            scores = []
            for key in expected:
                if key not in actual:
                    scores.append(0.0)
                else:
                    score, _ = self._compare_json(
                        actual[key], expected[key], f"{path}.{key}" if path else key
                    )
                    scores.append(score)

            return sum(scores) / len(scores), "Dict comparison"

        elif isinstance(expected, list):
            if not expected:
                return 1.0 if not actual else 0.0, "Empty list"

            if len(actual) != len(expected):
                return 0.5, f"List length mismatch: {len(actual)} vs {len(expected)}"

            scores = []
            for i, (a, e) in enumerate(zip(actual, expected)):
                score, _ = self._compare_json(a, e, f"{path}[{i}]")
                scores.append(score)

            return sum(scores) / len(scores), "List comparison"

        else:
            if actual == expected:
                return 1.0, "Match"
            if isinstance(expected, str) and isinstance(actual, str):
                if expected.lower() == actual.lower():
                    return 0.9, "Case mismatch"
            if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                if abs(float(actual) - float(expected)) < 0.01:
                    return 0.95, "Numeric approximation"
            return 0.0, f"Value mismatch at {path}"


class LLMJudgeVerifier(OpenClawVerifier):
    """Use an LLM to judge subjective task outcomes."""

    def __init__(
        self,
        workspace: Path | str | None = None,
        judge_backend: Any | None = None,
    ):
        super().__init__(workspace)
        self.judge_backend = judge_backend

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify task using LLM judgment."""
        # For research tasks, use specialized verification
        if isinstance(task, ResearchTask):
            return await self._verify_research_task(task, result)

        if self.judge_backend is None:
            # Fallback to heuristic verification
            return await self._heuristic_verify(task, result)

        # Build judgment prompt
        prompt = self._build_judgment_prompt(task, result)

        try:
            response = await self.judge_backend.generate(
                prompt=prompt,
                system="You are a fair and objective judge evaluating task completion. "
                       "Respond with JSON: {\"score\": 0.0-1.0, \"passed\": true/false, \"feedback\": \"...\"}",
                max_tokens=500,
            )

            # Parse response
            judgment = json.loads(response.content)

            return VerificationResult(
                passed=judgment.get("passed", False),
                score=float(judgment.get("score", 0.0)),
                feedback=judgment.get("feedback", "LLM judgment"),
            )

        except Exception as e:
            return await self._heuristic_verify(task, result)

    async def _verify_research_task(self, task: ResearchTask, result: TaskResult) -> VerificationResult:
        """Verify research task quality using LLM judge.

        Research tasks are judged on:
        - Specificity: Does it provide concrete insights vs vague generalizations?
        - Actionability: Can other bots use this information?
        - Evidence: Does it cite examples or reasoning?
        - Structure: Is it well-organized?
        """
        # First check if output file exists
        if self.workspace:
            output_path = self.workspace / "research_output.md"
            if output_path.exists():
                research_content = output_path.read_text()
            else:
                research_content = result.raw_response
        else:
            research_content = result.raw_response

        # Basic quality checks (heuristic fallback)
        if not research_content or len(research_content.strip()) < 100:
            return VerificationResult(
                passed=False,
                score=0.1,
                feedback="Research output too short (< 100 chars)",
            )

        # Check for required sections based on research type
        verification_data = task.get_verification_data()
        quality_criteria = verification_data.get("quality_criteria", [])

        if self.judge_backend is None:
            # Heuristic verification for research
            return await self._heuristic_research_verify(task, research_content, quality_criteria)

        # Build research-specific judgment prompt
        prompt = self._build_research_judgment_prompt(task, research_content, quality_criteria)

        try:
            response = await self.judge_backend.generate(
                prompt=prompt,
                system=(
                    "You are a research quality evaluator for an AI agent colony. "
                    "Judge the quality of research insights that will be shared with other AI agents. "
                    "Be strict but fair. Good research is specific, actionable, and evidence-based. "
                    "Respond with JSON: {\"score\": 0.0-1.0, \"passed\": true/false, \"feedback\": \"...\", \"strengths\": [...], \"improvements\": [...]}"
                ),
                max_tokens=800,
            )

            # Parse response
            judgment = json.loads(response.content)

            return VerificationResult(
                passed=judgment.get("passed", False),
                score=float(judgment.get("score", 0.0)),
                feedback=judgment.get("feedback", "Research quality judgment"),
                details={
                    "strengths": judgment.get("strengths", []),
                    "improvements": judgment.get("improvements", []),
                    "research_topic": task.research_topic,
                },
            )

        except Exception as e:
            return await self._heuristic_research_verify(task, research_content, quality_criteria)

    async def _heuristic_research_verify(
        self,
        task: ResearchTask,
        content: str,
        quality_criteria: list[str],
    ) -> VerificationResult:
        """Heuristic verification for research when no LLM judge available."""
        score = 0.0
        feedback_parts = []

        # Check length (longer is generally better for research)
        if len(content) >= 500:
            score += 0.2
            feedback_parts.append("Good length")
        elif len(content) >= 200:
            score += 0.1
            feedback_parts.append("Moderate length")

        # Check for section headers (structured writing)
        if "#" in content or "##" in content:
            score += 0.2
            feedback_parts.append("Has structure")

        # Check for concrete language (numbers, specifics)
        concrete_indicators = ["specific", "example", "because", "when", "result", "%", "$"]
        concrete_count = sum(1 for ind in concrete_indicators if ind.lower() in content.lower())
        if concrete_count >= 3:
            score += 0.2
            feedback_parts.append("Includes specifics")
        elif concrete_count >= 1:
            score += 0.1

        # Check for actionable language
        action_words = ["should", "recommend", "suggest", "try", "improve", "optimize", "consider"]
        action_count = sum(1 for word in action_words if word.lower() in content.lower())
        if action_count >= 2:
            score += 0.2
            feedback_parts.append("Actionable insights")
        elif action_count >= 1:
            score += 0.1

        # Check for self-awareness (references to bot's own experience)
        self_ref = ["my", "i ", "i've", "my performance", "my experience"]
        if any(ref in content.lower() for ref in self_ref):
            score += 0.1
            feedback_parts.append("Shows self-reflection")

        # Bonus for avoiding filler
        filler_words = ["basically", "essentially", "very", "really", "actually"]
        filler_count = sum(content.lower().count(word) for word in filler_words)
        if filler_count < 3:
            score += 0.1
            feedback_parts.append("Concise writing")

        passed = score >= 0.5
        feedback = "; ".join(feedback_parts) if feedback_parts else "Basic research output"

        return VerificationResult(
            passed=passed,
            score=min(1.0, score),
            feedback=f"Heuristic research evaluation: {feedback}",
            details={"research_topic": task.research_topic},
        )

    def _build_research_judgment_prompt(
        self,
        task: ResearchTask,
        content: str,
        quality_criteria: list[str],
    ) -> str:
        """Build the prompt for LLM research judgment."""
        criteria_str = "\n".join(f"- {c}" for c in quality_criteria)

        return f"""Evaluate the quality of this AI research output.

RESEARCH TASK:
{task.get_prompt()}

QUALITY CRITERIA:
{criteria_str}

RESEARCH OUTPUT:
{content[:3000]}

Evaluate the research quality:
1. Does it provide specific, actionable insights?
2. Does it include evidence or examples?
3. Would other AI agents find this useful?
4. Is it well-structured and clear?

Score from 0.0 to 1.0 where:
- 0.0-0.3: Poor quality (vague, generic, no useful insights)
- 0.4-0.6: Moderate quality (some useful insights but lacking depth)
- 0.7-0.8: Good quality (specific, actionable, well-reasoned)
- 0.9-1.0: Excellent quality (exceptional insights, highly transferable)

Pass threshold: 0.5"""

    async def _heuristic_verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Fallback heuristic verification when no LLM judge available."""
        # Check if response has reasonable content
        response = result.raw_response

        if not response or len(response.strip()) < 10:
            return VerificationResult(
                passed=False,
                score=0.1,
                feedback="Response too short",
            )

        # Check for error indicators
        error_patterns = ["error", "failed", "cannot", "unable", "sorry"]
        has_errors = any(p in response.lower() for p in error_patterns)

        if has_errors:
            return VerificationResult(
                passed=False,
                score=0.3,
                feedback="Response indicates errors",
            )

        # Assume partial success for reasonable responses
        return VerificationResult(
            passed=True,
            score=0.7,
            feedback="Heuristic verification: appears reasonable",
        )

    def _build_judgment_prompt(self, task: Task, result: TaskResult) -> str:
        """Build the prompt for LLM judgment."""
        return f"""Evaluate the following task completion:

TASK:
{task.get_prompt()}

RESPONSE:
{result.raw_response}

Did the response successfully complete the task? Score from 0.0 to 1.0.
Consider accuracy, completeness, and quality."""


class ExactMatchVerifier(OpenClawVerifier):
    """Verify exact match answers (math, logic)."""

    async def verify(self, task: Task, result: TaskResult) -> VerificationResult:
        """Verify exact match answer."""
        if not self.workspace:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="No workspace set for verification",
            )

        if not isinstance(task, MathProblemTask):
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback="Invalid task type for ExactMatchVerifier",
            )

        # Find answer file
        answer_path = self.workspace / "answer.txt"
        if not answer_path.exists():
            # Check result content
            answer_str = result.raw_response.strip()
        else:
            answer_str = answer_path.read_text().strip()

        # Extract numeric answer
        try:
            # Remove common prefixes
            answer_str = re.sub(r"^(the answer is|answer:|result:)\s*", "", answer_str.lower())
            answer_str = answer_str.strip().rstrip(".")

            # Parse number
            answer = float(answer_str.replace(",", ""))

            expected = task.answer
            tolerance = task.get_verification_data().get("tolerance", 0.001)

            if abs(answer - expected) <= tolerance:
                return VerificationResult(
                    passed=True,
                    score=1.0,
                    feedback="Correct answer",
                    details={"answer": answer, "expected": expected},
                )

            # Partial credit for close answers
            error_pct = abs(answer - expected) / max(abs(expected), 1)
            if error_pct <= 0.1:
                return VerificationResult(
                    passed=False,
                    score=0.5,
                    feedback=f"Close but not exact: got {answer}, expected {expected}",
                )

            return VerificationResult(
                passed=False,
                score=0.0,
                feedback=f"Wrong answer: got {answer}, expected {expected}",
            )

        except (ValueError, TypeError) as e:
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback=f"Could not parse answer: {e}",
                details={"raw": answer_str},
            )


def get_openclaw_verifier(
    task: OpenClawTask,
    workspace: Path | str,
) -> OpenClawVerifier:
    """Get the appropriate verifier for an OpenClaw task.

    Args:
        task: The task to verify
        workspace: Path to the task workspace

    Returns:
        Appropriate verifier instance
    """
    verifier_map = {
        VerificationType.TEST_CASES: CodeTestVerifier,
        VerificationType.FILE_EXISTS: FileOutcomeVerifier,
        VerificationType.FILE_CONTENT: FileOutcomeVerifier,
        VerificationType.SCHEMA_VALIDATION: SchemaVerifier,
        VerificationType.LLM_JUDGE: LLMJudgeVerifier,
        VerificationType.EXACT_MATCH: ExactMatchVerifier,
    }

    verifier_class = verifier_map.get(task.verification_type, FileOutcomeVerifier)
    verifier = verifier_class(workspace=workspace)

    return verifier


async def verify_openclaw_task(
    task: OpenClawTask,
    result: TaskResult,
    workspace: Path | str,
) -> VerificationResult:
    """Convenience function to verify an OpenClaw task.

    Args:
        task: The task to verify
        result: The task result
        workspace: Path to the task workspace

    Returns:
        VerificationResult
    """
    verifier = get_openclaw_verifier(task, workspace)
    return await verifier.verify(task, result)
