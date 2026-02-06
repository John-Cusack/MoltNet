"""Tests for OpenClaw tasks and verifiers."""

import tempfile
from pathlib import Path

import pytest

from clawdbot.fitness.openclaw_tasks import (
    OpenClawTask,
    OpenClawTaskType,
    VerificationType,
    CodeGenerationTask,
    FileOrganizationTask,
    DataExtractionTask,
    ScriptCreationTask,
    MathProblemTask,
    generate_openclaw_task,
)
from clawdbot.fitness.openclaw_verifiers import (
    FileOutcomeVerifier,
    CodeTestVerifier,
    SchemaVerifier,
    ExactMatchVerifier,
    get_openclaw_verifier,
    verify_openclaw_task,
)
from clawdbot.fitness.tasks import TaskResult, TaskTier


class TestCodeGenerationTask:
    """Tests for CodeGenerationTask."""

    def test_generate_simple(self):
        """Test simple code task generation."""
        task = CodeGenerationTask.generate(difficulty=0.1)

        assert task.function_name != ""
        assert task.description != ""
        assert task.signature != ""
        assert len(task.test_cases) > 0
        assert task.tier == TaskTier.MEDIUM

    def test_generate_medium(self):
        """Test medium code task generation."""
        task = CodeGenerationTask.generate(difficulty=0.5)

        assert task.function_name != ""
        assert len(task.test_cases) > 0

    def test_generate_hard(self):
        """Test hard code task generation."""
        task = CodeGenerationTask.generate(difficulty=0.8)

        assert task.function_name != ""
        assert task.tier == TaskTier.HARD

    def test_get_prompt(self):
        """Test prompt generation."""
        task = CodeGenerationTask.generate(difficulty=0.3)
        prompt = task.get_prompt()

        assert task.function_name in prompt
        assert task.description in prompt
        assert "def " in prompt

    def test_verification_data(self):
        """Test verification data structure."""
        task = CodeGenerationTask.generate(difficulty=0.5)
        data = task.get_verification_data()

        assert "function_name" in data
        assert "test_cases" in data
        assert data["verification_type"] == VerificationType.TEST_CASES.value


class TestFileOrganizationTask:
    """Tests for FileOrganizationTask."""

    def test_generate_by_extension(self):
        """Test file organization by extension."""
        task = FileOrganizationTask.generate(difficulty=0.2)

        assert task.organization_criteria == "extension"
        assert len(task.source_files) > 0
        assert len(task.expected_structure) > 0

    def test_generate_by_date(self):
        """Test file organization by date."""
        task = FileOrganizationTask.generate(difficulty=0.5)

        assert task.organization_criteria == "date"
        assert len(task.source_files) > 0

    def test_workspace_setup(self):
        """Test workspace setup files."""
        task = FileOrganizationTask.generate(difficulty=0.2)
        setup = task.get_workspace_setup()

        assert len(setup) > 0
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in setup.items())


class TestDataExtractionTask:
    """Tests for DataExtractionTask."""

    def test_generate_simple(self):
        """Test simple extraction task."""
        task = DataExtractionTask.generate(difficulty=0.1)

        assert task.input_text != ""
        assert task.schema != {}
        assert task.expected_output != {}
        assert task.tier == TaskTier.SIMPLE

    def test_generate_nested(self):
        """Test nested extraction task."""
        task = DataExtractionTask.generate(difficulty=0.5)

        assert task.input_text != ""
        assert task.expected_output != {}

    def test_get_prompt_includes_schema(self):
        """Test that prompt includes schema."""
        task = DataExtractionTask.generate(difficulty=0.3)
        prompt = task.get_prompt()

        assert "schema" in prompt.lower() or "Schema" in prompt
        assert "JSON" in prompt or "json" in prompt


class TestMathProblemTask:
    """Tests for MathProblemTask."""

    def test_generate_arithmetic(self):
        """Test arithmetic problem generation."""
        task = MathProblemTask.generate(difficulty=0.1)

        assert task.problem != ""
        assert isinstance(task.answer, (int, float))

    def test_generate_algebra(self):
        """Test algebra problem generation."""
        task = MathProblemTask.generate(difficulty=0.5)

        assert task.problem != ""
        assert isinstance(task.answer, (int, float))

    def test_generate_word_problem(self):
        """Test word problem generation."""
        task = MathProblemTask.generate(difficulty=0.8)

        assert task.problem != ""
        assert isinstance(task.answer, (int, float))


class TestGenerateOpenClawTask:
    """Tests for the task generator function."""

    def test_generate_random_task(self):
        """Test generating a random task."""
        task = generate_openclaw_task()

        assert isinstance(task, OpenClawTask)
        assert task.id != ""

    def test_generate_specific_type(self):
        """Test generating a specific task type."""
        task = generate_openclaw_task(
            task_type=OpenClawTaskType.CODE_GENERATION,
            difficulty=0.5,
        )

        assert isinstance(task, CodeGenerationTask)

    def test_generate_with_difficulty(self):
        """Test difficulty affects task."""
        easy_task = generate_openclaw_task(difficulty=0.1)
        hard_task = generate_openclaw_task(difficulty=0.9)

        # Both should be valid tasks
        assert easy_task.difficulty < hard_task.difficulty


class TestFileOutcomeVerifier:
    """Tests for FileOutcomeVerifier."""

    @pytest.mark.asyncio
    async def test_verify_file_organization(self):
        """Test file organization verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            # Create task
            task = FileOrganizationTask()
            task.organization_criteria = "extension"
            task.expected_structure = {"txt": ["file.txt"]}

            # Create expected file structure
            txt_dir = workspace / "txt"
            txt_dir.mkdir()
            (txt_dir / "file.txt").write_text("content")

            verifier = FileOutcomeVerifier(workspace=workspace)
            result = TaskResult(task_id=task.id, answer="", raw_response="", execution_time_seconds=1.0)

            verification = await verifier.verify(task, result)

            assert verification.passed
            assert verification.score == 1.0

    @pytest.mark.asyncio
    async def test_verify_missing_files(self):
        """Test verification with missing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            task = FileOrganizationTask()
            task.organization_criteria = "extension"
            task.expected_structure = {"txt": ["missing.txt"]}

            verifier = FileOutcomeVerifier(workspace=workspace)
            result = TaskResult(task_id=task.id, answer="", raw_response="", execution_time_seconds=1.0)

            verification = await verifier.verify(task, result)

            assert not verification.passed
            assert verification.score == 0.0


class TestCodeTestVerifier:
    """Tests for CodeTestVerifier."""

    @pytest.mark.asyncio
    async def test_verify_correct_code(self):
        """Test verification of correct code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            # Create task
            task = CodeGenerationTask()
            task.function_name = "double"
            task.test_cases = [
                {"input": [5], "output": 10},
                {"input": [0], "output": 0},
            ]

            # Write correct solution
            (workspace / "solution.py").write_text(
                "def double(n):\n    return n * 2\n"
            )

            verifier = CodeTestVerifier(workspace=workspace)
            result = TaskResult(task_id=task.id, answer="", raw_response="", execution_time_seconds=1.0)

            verification = await verifier.verify(task, result)

            assert verification.passed
            assert verification.score == 1.0

    @pytest.mark.asyncio
    async def test_verify_wrong_code(self):
        """Test verification of incorrect code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            task = CodeGenerationTask()
            task.function_name = "double"
            task.test_cases = [
                {"input": [5], "output": 10},
            ]

            # Write wrong solution
            (workspace / "solution.py").write_text(
                "def double(n):\n    return n + 1\n"
            )

            verifier = CodeTestVerifier(workspace=workspace)
            result = TaskResult(task_id=task.id, answer="", raw_response="", execution_time_seconds=1.0)

            verification = await verifier.verify(task, result)

            assert not verification.passed

    @pytest.mark.asyncio
    async def test_verify_no_solution_file(self):
        """Test verification when no solution file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            task = CodeGenerationTask()
            task.function_name = "double"
            task.test_cases = [{"input": [5], "output": 10}]

            verifier = CodeTestVerifier(workspace=workspace)
            result = TaskResult(task_id=task.id, answer="", raw_response="", execution_time_seconds=1.0)

            verification = await verifier.verify(task, result)

            assert not verification.passed
            assert verification.score == 0.0


class TestExactMatchVerifier:
    """Tests for ExactMatchVerifier."""

    @pytest.mark.asyncio
    async def test_verify_correct_answer(self):
        """Test verification of correct math answer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            task = MathProblemTask()
            task.answer = 42

            # Write correct answer
            (workspace / "answer.txt").write_text("42")

            verifier = ExactMatchVerifier(workspace=workspace)
            result = TaskResult(task_id=task.id, answer="", raw_response="", execution_time_seconds=1.0)

            verification = await verifier.verify(task, result)

            assert verification.passed
            assert verification.score == 1.0

    @pytest.mark.asyncio
    async def test_verify_wrong_answer(self):
        """Test verification of wrong math answer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            task = MathProblemTask()
            task.answer = 42

            (workspace / "answer.txt").write_text("100")

            verifier = ExactMatchVerifier(workspace=workspace)
            result = TaskResult(task_id=task.id, answer="", raw_response="", execution_time_seconds=1.0)

            verification = await verifier.verify(task, result)

            assert not verification.passed
            assert verification.score == 0.0


class TestGetOpenClawVerifier:
    """Tests for verifier selection."""

    def test_get_code_verifier(self):
        """Test getting verifier for code task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = CodeGenerationTask()
            verifier = get_openclaw_verifier(task, tmpdir)

            assert isinstance(verifier, CodeTestVerifier)

    def test_get_file_verifier(self):
        """Test getting verifier for file task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = FileOrganizationTask()
            verifier = get_openclaw_verifier(task, tmpdir)

            assert isinstance(verifier, FileOutcomeVerifier)

    def test_get_exact_match_verifier(self):
        """Test getting verifier for math task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = MathProblemTask()
            verifier = get_openclaw_verifier(task, tmpdir)

            assert isinstance(verifier, ExactMatchVerifier)
