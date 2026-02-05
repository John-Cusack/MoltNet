"""Tests for task generation and verification."""

import pytest
from clawdbot.fitness.tasks import (
    MathTask,
    JSONTask,
    LogicTask,
    CodeTask,
    TaskTier,
    TaskType,
    TaskResult,
)
from clawdbot.fitness.verifiers import (
    MathVerifier,
    JSONVerifier,
    LogicVerifier,
    CodeVerifier,
    get_verifier,
)
from clawdbot.fitness.task_pool import TaskPool, TaskPoolConfig
from clawdbot.fitness.rewards import RewardCalculator, VerificationResult


class TestMathTask:
    """Tests for MathTask generation and verification."""

    def test_generate_simple_arithmetic(self):
        """Test generation of simple arithmetic tasks."""
        task = MathTask.generate(difficulty=0.1)

        assert task.tier == TaskTier.SIMPLE
        assert task.task_type == TaskType.MATH
        assert task.expression != ""
        assert isinstance(task.answer, (int, float))

    def test_generate_multi_step(self):
        """Test generation of multi-step arithmetic."""
        task = MathTask.generate(difficulty=0.45)

        assert task.expression != ""
        assert "(" in task.expression or task.word_problem != ""

    def test_generate_word_problem(self):
        """Test generation of word problems."""
        task = MathTask.generate(difficulty=0.8)

        # At high difficulty, should generate word problems
        prompt = task.get_prompt()
        assert "Answer:" in prompt

    def test_prompt_format(self):
        """Test that prompts are properly formatted."""
        task = MathTask.generate(difficulty=0.2)
        prompt = task.get_prompt()

        assert "Answer:" in prompt
        assert isinstance(prompt, str)
        assert len(prompt) > 10

    def test_verification_data(self):
        """Test that verification data is correct."""
        task = MathTask.generate(difficulty=0.3)
        data = task.get_verification_data()

        assert "expected" in data
        assert "tolerance" in data
        assert data["expected"] == task.answer


class TestMathVerifier:
    """Tests for MathVerifier."""

    @pytest.fixture
    def verifier(self):
        return MathVerifier()

    @pytest.mark.asyncio
    async def test_correct_answer(self, verifier):
        """Test verification of correct answer."""
        task = MathTask()
        task.expression = "5 + 3"
        task.answer = 8

        result = TaskResult(
            task_id=task.id,
            answer=8,
            raw_response="8",
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is True
        assert verification.score == 1.0

    @pytest.mark.asyncio
    async def test_wrong_answer(self, verifier):
        """Test verification of wrong answer."""
        task = MathTask()
        task.expression = "5 + 3"
        task.answer = 8

        result = TaskResult(
            task_id=task.id,
            answer=10,
            raw_response="10",
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is False
        assert verification.score == 0.0

    @pytest.mark.asyncio
    async def test_answer_with_prefix(self, verifier):
        """Test parsing answer with 'The answer is' prefix."""
        task = MathTask()
        task.expression = "10 * 5"
        task.answer = 50

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="The answer is 50",
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is True

    @pytest.mark.asyncio
    async def test_close_answer_partial_credit(self, verifier):
        """Test partial credit for close answers."""
        task = MathTask()
        task.answer = 100

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="95",  # Within 10%
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is False
        assert verification.score == 0.5  # Partial credit


class TestJSONTask:
    """Tests for JSONTask generation and verification."""

    def test_generate_simple(self):
        """Test simple JSON extraction task."""
        task = JSONTask.generate(difficulty=0.1)

        assert task.input_text != ""
        assert task.schema != {}
        assert task.expected_output != {}

    def test_generate_nested(self):
        """Test nested JSON extraction."""
        task = JSONTask.generate(difficulty=0.5)

        prompt = task.get_prompt()
        assert "Schema:" in prompt
        assert "Text:" in prompt

    def test_verification_data(self):
        """Test verification data structure."""
        task = JSONTask.generate(difficulty=0.3)
        data = task.get_verification_data()

        assert "schema" in data
        assert "expected" in data


class TestJSONVerifier:
    """Tests for JSONVerifier."""

    @pytest.fixture
    def verifier(self):
        return JSONVerifier()

    @pytest.mark.asyncio
    async def test_correct_json(self, verifier):
        """Test verification of correct JSON."""
        task = JSONTask()
        task.input_text = "John is 30 years old."
        task.schema = {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}
        task.expected_output = {"name": "John", "age": 30}

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response='{"name": "John", "age": 30}',
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is True
        assert verification.score >= 0.9

    @pytest.mark.asyncio
    async def test_json_in_code_block(self, verifier):
        """Test extraction of JSON from code block."""
        task = JSONTask()
        task.expected_output = {"value": 42}

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response='```json\n{"value": 42}\n```',
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is True

    @pytest.mark.asyncio
    async def test_partial_match(self, verifier):
        """Test partial credit for partial match."""
        task = JSONTask()
        task.expected_output = {"a": 1, "b": 2, "c": 3}

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response='{"a": 1, "b": 2}',  # Missing "c"
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        # Should have partial score for 2/3 correct
        assert 0.5 < verification.score < 1.0


class TestLogicTask:
    """Tests for LogicTask generation."""

    def test_generate_sequence(self):
        """Test sequence puzzle generation."""
        task = LogicTask.generate(difficulty=0.2)

        assert task.puzzle != ""
        assert task.answer != ""

    def test_generate_deduction(self):
        """Test deduction puzzle generation."""
        task = LogicTask.generate(difficulty=0.5)

        prompt = task.get_prompt()
        assert len(prompt) > 20


class TestCodeTask:
    """Tests for CodeTask generation and verification."""

    def test_generate_simple(self):
        """Test simple code task generation."""
        task = CodeTask.generate(difficulty=0.1)

        assert task.function_name != ""
        assert task.description != ""
        assert task.signature != ""
        assert len(task.test_cases) > 0

    def test_generate_medium(self):
        """Test medium code task generation."""
        task = CodeTask.generate(difficulty=0.45)

        assert task.function_name != ""
        assert len(task.test_cases) >= 2

    def test_generate_hard(self):
        """Test hard code task generation."""
        task = CodeTask.generate(difficulty=0.8)

        assert task.function_name != ""
        prompt = task.get_prompt()
        assert "def " in task.signature

    def test_prompt_includes_examples(self):
        """Test that prompt includes examples."""
        task = CodeTask.generate(difficulty=0.5)
        prompt = task.get_prompt()

        assert ">>>" in prompt  # Contains example calls
        assert task.function_name in prompt


class TestCodeVerifier:
    """Tests for CodeVerifier."""

    @pytest.fixture
    def verifier(self):
        return CodeVerifier(timeout_seconds=5.0)

    @pytest.mark.asyncio
    async def test_correct_solution(self, verifier):
        """Test verification of correct code solution."""
        task = CodeTask()
        task.function_name = "double"
        task.description = "Return twice the input"
        task.signature = "def double(n: int) -> int:"
        task.test_cases = [
            {"input": [5], "output": 10},
            {"input": [0], "output": 0},
        ]
        task.solution = "def double(n: int) -> int:\n    return n * 2"

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="def double(n: int) -> int:\n    return n * 2",
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is True
        assert verification.score == 1.0

    @pytest.mark.asyncio
    async def test_code_in_markdown(self, verifier):
        """Test extraction of code from markdown block."""
        task = CodeTask()
        task.function_name = "add_one"
        task.test_cases = [{"input": [5], "output": 6}]

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="```python\ndef add_one(n):\n    return n + 1\n```",
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is True

    @pytest.mark.asyncio
    async def test_partial_test_pass(self, verifier):
        """Test partial credit for some tests passing."""
        task = CodeTask()
        task.function_name = "broken"
        task.test_cases = [
            {"input": [5], "output": 10},
            {"input": [0], "output": 0},  # This will fail
        ]

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="def broken(n):\n    return 10 if n == 5 else 999",
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is False
        assert verification.score == 0.5  # 1/2 tests pass

    @pytest.mark.asyncio
    async def test_timeout_handling(self, verifier):
        """Test that infinite loops are handled."""
        task = CodeTask()
        task.function_name = "infinite"
        task.test_cases = [{"input": [], "output": 1}]

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="def infinite():\n    while True: pass",
            execution_time_seconds=1.0,
        )

        verification = await verifier.verify(task, result)

        assert verification.passed is False
        assert verification.feedback == "Code execution timed out"


class TestTaskPool:
    """Tests for TaskPool."""

    @pytest.fixture
    def pool(self):
        return TaskPool()

    def test_sample_default(self, pool):
        """Test sampling with defaults."""
        task = pool.sample()

        assert task is not None
        assert isinstance(task.id, str)

    def test_sample_by_difficulty(self, pool):
        """Test sampling by difficulty."""
        # Low difficulty should give simple or medium tier (near boundary)
        task = pool.sample(difficulty=0.1)
        assert task.tier in (TaskTier.SIMPLE, TaskTier.MEDIUM)

        # Medium difficulty should give simple, medium, or hard tier
        task = pool.sample(difficulty=0.5)
        assert task.tier in (TaskTier.SIMPLE, TaskTier.MEDIUM, TaskTier.HARD)

        # High difficulty should give hard/expert tier
        task = pool.sample(difficulty=0.9)
        assert task.tier in (TaskTier.MEDIUM, TaskTier.HARD, TaskTier.EXPERT)

    def test_sample_by_tier(self, pool):
        """Test explicit tier selection."""
        task = pool.sample(tier=TaskTier.SIMPLE)
        assert task.tier == TaskTier.SIMPLE

        task = pool.sample(tier=TaskTier.MEDIUM)
        assert task.tier == TaskTier.MEDIUM

    def test_sample_by_type(self, pool):
        """Test explicit task type selection."""
        task = pool.sample(task_type=TaskType.MATH)
        assert task.task_type == TaskType.MATH

    def test_sample_with_preferences(self, pool):
        """Test sampling with preferences."""
        preferences = {"math": 0.9, "json": 0.1, "logic": 0.1}

        # Sample many and check distribution
        math_count = 0
        for _ in range(20):
            task = pool.sample(difficulty=0.2, preferences=preferences)
            if task.task_type == TaskType.MATH:
                math_count += 1

        # Should be biased toward math
        assert math_count > 5

    def test_sample_batch(self, pool):
        """Test batch sampling."""
        tasks = pool.sample_batch(count=5, difficulty=0.3)

        assert len(tasks) == 5
        for task in tasks:
            assert task is not None


class TestRewardCalculator:
    """Tests for RewardCalculator."""

    @pytest.fixture
    def calculator(self):
        return RewardCalculator()

    def test_reward_for_success(self, calculator):
        """Test reward calculation for successful task."""
        task = MathTask.generate(difficulty=0.5)
        task.tier = TaskTier.SIMPLE

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="42",
            execution_time_seconds=2.0,
        )

        verification = VerificationResult(passed=True, score=1.0, feedback="Correct")

        reward = calculator.calculate(task, result, verification)

        assert reward > 0
        # Math base is 0.001, difficulty bonus is 0.002 * 0.5 = 0.001, tier mult is 1.0
        assert 0.001 <= reward <= 0.01

    def test_no_reward_for_failure(self, calculator):
        """Test no reward for failed task."""
        task = MathTask.generate(difficulty=0.5)

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="wrong",
            execution_time_seconds=2.0,
        )

        verification = VerificationResult(passed=False, score=0.0, feedback="Wrong")

        reward = calculator.calculate(task, result, verification)

        assert reward == 0.0

    def test_partial_reward(self, calculator):
        """Test partial reward for partial success."""
        task = CodeTask.generate(difficulty=0.5)
        task.tier = TaskTier.MEDIUM

        result = TaskResult(
            task_id=task.id,
            answer=None,
            raw_response="def f(): pass",
            execution_time_seconds=5.0,
        )

        verification = VerificationResult(passed=False, score=0.5, feedback="Half tests pass")

        reward = calculator.calculate(task, result, verification)

        # Should get partial reward
        assert reward > 0
        assert reward < calculator.calculate(
            task, result, VerificationResult(passed=True, score=1.0, feedback="")
        )

    def test_tier_multiplier(self, calculator):
        """Test that higher tiers give higher rewards."""
        result = TaskResult(
            task_id="test",
            answer=None,
            raw_response="42",
            execution_time_seconds=2.0,
        )
        verification = VerificationResult(passed=True, score=1.0, feedback="Correct")

        # Create tasks at different tiers
        simple_task = CodeTask.generate(difficulty=0.3)
        simple_task.tier = TaskTier.SIMPLE

        hard_task = CodeTask.generate(difficulty=0.7)
        hard_task.tier = TaskTier.HARD

        simple_reward = calculator.calculate(simple_task, result, verification)
        hard_reward = calculator.calculate(hard_task, result, verification)

        # Hard tier should give more
        assert hard_reward > simple_reward

    def test_estimate_reward(self, calculator):
        """Test reward estimation."""
        min_r, max_r = calculator.estimate_reward(TaskType.MATH, TaskTier.SIMPLE, 0.5)

        assert min_r > 0
        assert max_r >= min_r


class TestGetVerifier:
    """Tests for verifier factory function."""

    def test_math_verifier(self):
        """Test getting math verifier."""
        verifier = get_verifier(TaskType.MATH)
        assert isinstance(verifier, MathVerifier)

    def test_json_verifier(self):
        """Test getting JSON verifier."""
        verifier = get_verifier(TaskType.JSON)
        assert isinstance(verifier, JSONVerifier)

    def test_logic_verifier(self):
        """Test getting logic verifier."""
        verifier = get_verifier(TaskType.LOGIC)
        assert isinstance(verifier, LogicVerifier)

    def test_code_verifier(self):
        """Test getting code verifier."""
        verifier = get_verifier(TaskType.CODE)
        assert isinstance(verifier, CodeVerifier)

    def test_humaneval_uses_code_verifier(self):
        """Test that humaneval uses code verifier."""
        verifier = get_verifier(TaskType.HUMANEVAL)
        assert isinstance(verifier, CodeVerifier)
