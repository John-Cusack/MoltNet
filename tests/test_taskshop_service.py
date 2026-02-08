"""Tests for the Task Shop service."""

from __future__ import annotations

import pytest

from taskshop.config import TaskShopSettings
from taskshop.database import TaskShopDatabase
from taskshop.payout import calculate_payout, get_difficulty_multiplier
from taskshop.verification import (
    compute_f1,
    extract_math_answer,
    extract_python_code,
    extract_reading_answer,
    normalize_math_answer,
    verify_coding_task,
    verify_math_task,
    verify_reading_task,
    verify_submission,
)

# ==================== Payout Tests ====================


class TestPayout:
    def test_base_payout_humaneval(self):
        payout = calculate_payout("humaneval", 0.5, 1.0, 1)
        assert payout == pytest.approx(0.025 * 1.5, abs=1e-6)

    def test_base_payout_gsm8k(self):
        payout = calculate_payout("gsm8k", 0.1, 1.0, 1)
        assert payout == pytest.approx(0.010 * 0.6, abs=1e-6)

    def test_cycle_decay(self):
        payout_1 = calculate_payout("humaneval", 0.5, 1.0, 1)
        payout_2 = calculate_payout("humaneval", 0.5, 1.0, 2)
        payout_3 = calculate_payout("humaneval", 0.5, 1.0, 3)
        assert payout_1 > payout_2 > payout_3

    def test_score_scaling(self):
        full = calculate_payout("humaneval", 0.5, 1.0, 1)
        half = calculate_payout("humaneval", 0.5, 0.5, 1)
        assert full == pytest.approx(half * 2, abs=1e-6)

    def test_zero_score(self):
        payout = calculate_payout("humaneval", 0.5, 0.0, 1)
        assert payout == 0.0

    def test_difficulty_multiplier_easy(self):
        assert get_difficulty_multiplier(0.1) == 0.6

    def test_difficulty_multiplier_expert(self):
        assert get_difficulty_multiplier(0.95) == 2.5

    def test_unknown_benchmark_uses_default(self):
        payout = calculate_payout("unknown_benchmark", 0.5, 1.0, 1)
        assert payout > 0  # Uses default base payout of 0.015


# ==================== Verification Tests ====================


class TestExtractPythonCode:
    def test_python_block(self):
        response = "Here's the solution:\n```python\ndef add(a, b):\n    return a + b\n```"
        code = extract_python_code(response)
        assert code == "def add(a, b):\n    return a + b"

    def test_multiple_python_blocks(self):
        response = "```python\nx = 1\n```\nActually:\n```python\ndef solve():\n    return 42\n```"
        code = extract_python_code(response)
        assert "def solve" in code

    def test_generic_code_block(self):
        response = "```\ndef foo():\n    return 1\n```"
        code = extract_python_code(response)
        assert code == "def foo():\n    return 1"

    def test_bare_python(self):
        response = "def add(a, b):\n    return a + b"
        code = extract_python_code(response)
        assert "def add" in code

    def test_no_code(self):
        response = "I don't know how to solve this."
        code = extract_python_code(response)
        assert code is None


class TestExtractMathAnswer:
    def test_answer_format(self):
        assert extract_math_answer("ANSWER: 42") == "42"

    def test_boxed_format(self):
        assert extract_math_answer("The answer is \\boxed{42}") == "42"

    def test_the_answer_is(self):
        assert extract_math_answer("So the answer is 42.") == "42"

    def test_final_answer(self):
        assert extract_math_answer("Final answer: 42") == "42"

    def test_equals_at_end(self):
        assert extract_math_answer("x + 5 = 10\n2 + 2 = 42") == "42"

    def test_no_answer(self):
        assert extract_math_answer("I can't solve this") is None


class TestNormalizeMathAnswer:
    def test_integer(self):
        assert normalize_math_answer("42") == 42.0

    def test_float(self):
        assert normalize_math_answer("3.14") == pytest.approx(3.14)

    def test_fraction(self):
        assert normalize_math_answer("3/4") == pytest.approx(0.75)

    def test_with_formatting(self):
        assert normalize_math_answer("$1,000") == 1000.0

    def test_invalid(self):
        assert normalize_math_answer("hello") is None


class TestVerifyCodingTask:
    async def test_passing_code(self):
        code = "def add(a, b):\n    return a + b"
        test_code = "assert add(1, 2) == 3\nassert add(0, 0) == 0"
        result = await verify_coding_task(code, test_code)
        assert result.passed
        assert result.score == 1.0

    async def test_failing_code(self):
        code = "def add(a, b):\n    return a - b"  # Bug: subtraction
        test_code = "assert add(1, 2) == 3"
        result = await verify_coding_task(code, test_code)
        assert not result.passed
        assert result.score == 0.0

    async def test_syntax_error(self):
        code = "def add(a, b):\n    retrun a + b"  # Typo
        test_code = "assert add(1, 2) == 3"
        result = await verify_coding_task(code, test_code)
        assert not result.passed


class TestVerifyMathTask:
    async def test_correct_integer(self):
        result = await verify_math_task("ANSWER: 42", "42")
        assert result.passed
        assert result.score == 1.0

    async def test_correct_float(self):
        result = await verify_math_task("ANSWER: 3.14", "3.14")
        assert result.passed

    async def test_incorrect(self):
        result = await verify_math_task("ANSWER: 43", "42")
        assert not result.passed

    async def test_no_answer_extracted(self):
        result = await verify_math_task("I have no idea", "42")
        assert not result.passed
        assert "extract" in result.feedback.lower()


class TestVerifySubmission:
    async def test_coding_submission(self):
        response = "```python\ndef add(a, b):\n    return a + b\n```\nACTION: SUBMIT"
        result = await verify_submission(
            category="coding",
            response=response,
            test_code="assert add(1, 2) == 3",
            ground_truth=None,
        )
        assert result.passed

    async def test_math_submission(self):
        result = await verify_submission(
            category="math",
            response="The answer is ANSWER: 42",
            test_code=None,
            ground_truth="42",
        )
        assert result.passed

    async def test_coding_no_code(self):
        result = await verify_submission(
            category="coding",
            response="I don't know how to solve this.",
            test_code="assert True",
            ground_truth=None,
        )
        assert not result.passed
        assert "No Python code" in result.feedback


# ==================== Database Tests ====================


class TestTaskShopDatabase:
    @pytest.fixture
    async def test_db(self, tmp_path):
        """Create a temporary database for testing."""
        db = TaskShopDatabase(tmp_path / "test_taskshop.db")
        await db.connect()
        yield db
        await db.close()

    async def test_insert_and_get_task(self, test_db):
        task_data = {
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.3,
            "title": "Test Task",
            "prompt": "Write a function that adds two numbers.",
            "test_code": "assert add(1, 2) == 3",
            "ground_truth": "def add(a, b): return a + b",
        }
        task_id = await test_db.insert_task(task_data)
        assert task_id

        task = await test_db.get_task(task_id)
        assert task is not None
        assert task["benchmark"] == "humaneval"
        assert task["title"] == "Test Task"

    async def test_insert_tasks_batch(self, test_db):
        tasks = [
            {
                "benchmark": "humaneval",
                "benchmark_id": f"HumanEval/{i}",
                "category": "coding",
                "difficulty": i * 0.2,
                "title": f"Task {i}",
                "prompt": f"Problem {i}",
            }
            for i in range(5)
        ]
        count = await test_db.insert_tasks_batch(tasks)
        assert count == 5

    async def test_browse_tasks(self, test_db):
        # Insert tasks
        for i in range(3):
            await test_db.insert_task({
                "benchmark": "humaneval",
                "benchmark_id": f"HumanEval/{i}",
                "category": "coding",
                "difficulty": 0.3 + i * 0.2,
                "title": f"Task {i}",
                "prompt": f"Problem {i}",
            })

        tasks, total = await test_db.browse_tasks()
        assert total == 3
        assert len(tasks) == 3

    async def test_browse_tasks_with_filters(self, test_db):
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.3,
            "title": "Easy",
            "prompt": "Easy problem",
        })
        await test_db.insert_task({
            "benchmark": "gsm8k",
            "benchmark_id": "gsm8k/0",
            "category": "math",
            "difficulty": 0.7,
            "title": "Hard math",
            "prompt": "Hard math problem",
        })

        # Filter by category
        tasks, total = await test_db.browse_tasks(category="coding")
        assert total == 1
        assert tasks[0]["category"] == "coding"

        # Filter by difficulty
        tasks, total = await test_db.browse_tasks(difficulty_min=0.5, difficulty_max=1.0)
        assert total == 1

    async def test_claim_task(self, test_db):
        # Insert a task
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.5,
            "title": "Test",
            "prompt": "Test problem",
        })

        # Claim it
        assignment = await test_db.claim_task("bot-1")
        assert assignment is not None
        assert assignment["bot_name"] == "bot-1"
        assert assignment["status"] == "active"

    async def test_claim_prevents_double_assignment(self, test_db):
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.5,
            "title": "Test",
            "prompt": "Test problem",
        })

        # First claim succeeds
        assignment1 = await test_db.claim_task("bot-1")
        assert assignment1 is not None

        # Second claim fails (bot already has active assignment)
        assignment2 = await test_db.claim_task("bot-1")
        assert assignment2 is None

    async def test_get_active_assignment(self, test_db):
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.5,
            "title": "Test",
            "prompt": "Test problem",
        })

        await test_db.claim_task("bot-1")

        assignment = await test_db.get_active_assignment("bot-1")
        assert assignment is not None
        assert assignment["status"] == "active"
        assert assignment["task"]["benchmark"] == "humaneval"

    async def test_submit_cycle_quit(self, test_db):
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.5,
            "title": "Test",
            "prompt": "Test problem",
            "test_code": "assert add(1, 2) == 3",
        })

        assignment = await test_db.claim_task("bot-1")

        result = await test_db.submit_cycle(
            assignment_id=assignment["assignment_id"],
            bot_name="bot-1",
            action="quit",
            response_content="I give up",
        )

        assert result is not None
        assert result["status"] == "abandoned"

    async def test_submit_cycle_submit_success(self, test_db):
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.3,
            "title": "Add Function",
            "prompt": "Write add function",
            "test_code": "assert add(1, 2) == 3\nassert add(0, 0) == 0",
        })

        assignment = await test_db.claim_task("bot-1")

        result = await test_db.submit_cycle(
            assignment_id=assignment["assignment_id"],
            bot_name="bot-1",
            action="submit",
            response_content="```python\ndef add(a, b):\n    return a + b\n```",
        )

        assert result is not None
        assert result["status"] == "completed"
        assert result["score"] == 1.0
        assert result["payout"] > 0

    async def test_submit_cycle_submit_failure(self, test_db):
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.3,
            "title": "Add Function",
            "prompt": "Write add function",
            "test_code": "assert add(1, 2) == 3",
        })

        assignment = await test_db.claim_task("bot-1")

        result = await test_db.submit_cycle(
            assignment_id=assignment["assignment_id"],
            bot_name="bot-1",
            action="submit",
            response_content="```python\ndef add(a, b):\n    return a - b\n```",
        )

        assert result is not None
        assert result["status"] == "failed"
        assert result["score"] == 0.0

    async def test_multi_cycle_continue_then_submit(self, test_db):
        await test_db.insert_task({
            "benchmark": "humaneval",
            "benchmark_id": "HumanEval/0",
            "category": "coding",
            "difficulty": 0.3,
            "title": "Add Function",
            "prompt": "Write add function",
            "test_code": "assert add(1, 2) == 3",
        })

        assignment = await test_db.claim_task("bot-1", max_cycles=3)

        # Cycle 1: continue
        result1 = await test_db.submit_cycle(
            assignment_id=assignment["assignment_id"],
            bot_name="bot-1",
            action="continue",
            response_content="Let me think about this...",
        )
        assert result1["status"] == "active"

        # Cycle 2: submit
        result2 = await test_db.submit_cycle(
            assignment_id=assignment["assignment_id"],
            bot_name="bot-1",
            action="submit",
            response_content="```python\ndef add(a, b):\n    return a + b\n```",
        )
        assert result2["status"] == "completed"

    async def test_math_task_verification(self, test_db):
        await test_db.insert_task({
            "benchmark": "gsm8k",
            "benchmark_id": "gsm8k/0",
            "category": "math",
            "difficulty": 0.3,
            "title": "Simple math",
            "prompt": "What is 6 * 7?",
            "ground_truth": "42",
        })

        assignment = await test_db.claim_task("bot-1")

        result = await test_db.submit_cycle(
            assignment_id=assignment["assignment_id"],
            bot_name="bot-1",
            action="submit",
            response_content="6 * 7 = 42. ANSWER: 42",
        )

        assert result["status"] == "completed"
        assert result["score"] == 1.0

    async def test_stats(self, test_db):
        stats = await test_db.get_stats()
        assert "total_tasks" in stats
        assert "total_assignments" in stats
        assert stats["total_tasks"] == 0

    async def test_bot_stats(self, test_db):
        stats = await test_db.get_bot_stats("nonexistent-bot")
        assert stats["total_assignments"] == 0
        assert stats["average_score"] == 0.0


# ==================== Client Tests ====================


class TestTaskShopClient:
    def test_client_disabled_without_url(self):
        from clawdbot.taskshop_client import TaskShopClient

        client = TaskShopClient(base_url="", bot_name="test")
        assert not client.is_enabled

    def test_client_enabled_with_url(self):
        from clawdbot.taskshop_client import TaskShopClient

        client = TaskShopClient(base_url="http://localhost:9104", bot_name="test")
        assert client.is_enabled

    async def test_disabled_client_returns_none(self):
        from clawdbot.taskshop_client import TaskShopClient

        client = TaskShopClient(base_url="", bot_name="test")
        assert await client.browse_tasks() == []
        assert await client.claim_task() is None
        assert await client.get_active_assignment() is None

    def test_factory_function(self):
        import os

        from clawdbot.taskshop_client import create_taskshop_client

        # Without env var
        os.environ.pop("TASKSHOP_URL", None)
        client = create_taskshop_client("test-bot")
        assert not client.is_enabled
        assert client.bot_name == "test-bot"


# ==================== Config Tests ====================


class TestConfig:
    def test_default_settings(self):
        settings = TaskShopSettings()
        assert settings.port == 9104
        assert settings.database_path == "taskshop.db"
        assert settings.verification_timeout == 30.0

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("TASKSHOP_PORT", "9200")
        monkeypatch.setenv("TASKSHOP_DATABASE_PATH", "custom.db")
        settings = TaskShopSettings.from_env()
        assert settings.port == 9200
        assert settings.database_path == "custom.db"


# ==================== Bot Integration Tests ====================


class TestBotIntegration:
    def test_parse_cycle_action_submit(self):

        # Test the static method behavior via a mock-like approach
        import re

        response = "Here's my answer...\nACTION: SUBMIT"
        match = re.search(r"ACTION:\s*(SUBMIT|CONTINUE|QUIT)", response, re.IGNORECASE)
        assert match
        assert match.group(1).lower() == "submit"

    def test_parse_cycle_action_continue(self):
        import re

        response = "I need more time.\n\nACTION: CONTINUE"
        match = re.search(r"ACTION:\s*(SUBMIT|CONTINUE|QUIT)", response, re.IGNORECASE)
        assert match
        assert match.group(1).lower() == "continue"

    def test_parse_cycle_action_quit(self):
        import re

        response = "This is too hard.\nACTION: QUIT"
        match = re.search(r"ACTION:\s*(SUBMIT|CONTINUE|QUIT)", response, re.IGNORECASE)
        assert match
        assert match.group(1).lower() == "quit"

    def test_parse_cycle_action_default(self):
        import re

        response = "Here's my answer without an explicit action."
        match = re.search(r"ACTION:\s*(SUBMIT|CONTINUE|QUIT)", response, re.IGNORECASE)
        assert match is None  # No match = default to submit


# ==================== Reading Comprehension Tests ====================


class TestExtractReadingAnswer:
    def test_answer_format(self):
        assert extract_reading_answer("ANSWER: yes") == "yes"

    def test_answer_with_text(self):
        result = extract_reading_answer("After analysis, ANSWER: neural networks")
        assert result == "neural networks"

    def test_the_answer_is_format(self):
        result = extract_reading_answer("The answer is B.")
        assert result == "B"

    def test_no_answer(self):
        assert extract_reading_answer("I have no idea what to say.") is None


class TestComputeF1:
    def test_exact_match(self):
        assert compute_f1("the cat sat", "the cat sat") == pytest.approx(1.0)

    def test_partial_overlap(self):
        f1 = compute_f1("the cat", "the cat sat on the mat")
        assert 0.0 < f1 < 1.0

    def test_no_overlap(self):
        assert compute_f1("apple banana", "cherry grape") == 0.0

    def test_empty_strings(self):
        assert compute_f1("", "hello") == 0.0
        assert compute_f1("hello", "") == 0.0

    def test_case_insensitive(self):
        assert compute_f1("The Cat", "the cat") == pytest.approx(1.0)

    def test_punctuation_ignored(self):
        assert compute_f1("hello, world!", "hello world") == pytest.approx(1.0)

    def test_single_token_match(self):
        f1 = compute_f1("yes", "yes")
        assert f1 == pytest.approx(1.0)


class TestVerifyReadingTask:
    async def test_multiple_choice_correct(self):
        result = await verify_reading_task(
            response="ANSWER: B",
            ground_truth="B",
            metadata={"answer_type": "multiple_choice"},
        )
        assert result.passed
        assert result.score == 1.0

    async def test_multiple_choice_incorrect(self):
        result = await verify_reading_task(
            response="ANSWER: A",
            ground_truth="C",
            metadata={"answer_type": "multiple_choice"},
        )
        assert not result.passed
        assert result.score == 0.0

    async def test_multiple_choice_with_extra_text(self):
        result = await verify_reading_task(
            response="ANSWER: B) photosynthesis",
            ground_truth="B",
            metadata={"answer_type": "multiple_choice"},
        )
        assert result.passed

    async def test_boolean_correct(self):
        result = await verify_reading_task(
            response="ANSWER: yes",
            ground_truth="yes",
            metadata={"answer_type": "boolean"},
        )
        assert result.passed
        assert result.score == 1.0

    async def test_boolean_incorrect(self):
        result = await verify_reading_task(
            response="ANSWER: yes",
            ground_truth="no",
            metadata={"answer_type": "boolean"},
        )
        assert not result.passed

    async def test_unanswerable_correct(self):
        result = await verify_reading_task(
            response="ANSWER: unanswerable",
            ground_truth="unanswerable",
            metadata={"answer_type": "unanswerable"},
        )
        assert result.passed
        assert result.score == 1.0

    async def test_unanswerable_with_phrase(self):
        result = await verify_reading_task(
            response="ANSWER: cannot be answered from the text",
            ground_truth="unanswerable",
            metadata={"answer_type": "unanswerable"},
        )
        assert result.passed

    async def test_unanswerable_wrong(self):
        result = await verify_reading_task(
            response="ANSWER: 42",
            ground_truth="unanswerable",
            metadata={"answer_type": "unanswerable"},
        )
        assert not result.passed

    async def test_extractive_high_f1(self):
        result = await verify_reading_task(
            response="ANSWER: neural network architectures for text",
            ground_truth="neural network architectures for text classification",
            metadata={"answer_type": "extractive"},
        )
        assert result.passed
        assert result.score > 0.4

    async def test_extractive_low_f1(self):
        result = await verify_reading_task(
            response="ANSWER: something completely different",
            ground_truth="neural network architectures for text classification",
            metadata={"answer_type": "extractive"},
        )
        assert not result.passed

    async def test_abstractive_scoring(self):
        result = await verify_reading_task(
            response="ANSWER: The method uses attention mechanisms to improve accuracy",
            ground_truth="attention mechanisms improve model accuracy",
            metadata={"answer_type": "abstractive"},
        )
        assert result.score > 0.0

    async def test_no_answer_extracted(self):
        result = await verify_reading_task(
            response="I'm not sure about this question.",
            ground_truth="yes",
            metadata={"answer_type": "boolean"},
        )
        assert not result.passed
        assert "extract" in result.feedback.lower()


class TestVerifySubmissionReading:
    async def test_reading_submission_multiple_choice(self):
        result = await verify_submission(
            category="reading",
            response="ANSWER: C",
            test_code=None,
            ground_truth="C",
            metadata={"answer_type": "multiple_choice"},
        )
        assert result.passed
        assert result.score == 1.0

    async def test_reading_submission_boolean(self):
        result = await verify_submission(
            category="reading",
            response="ANSWER: no",
            test_code=None,
            ground_truth="no",
            metadata={"answer_type": "boolean"},
        )
        assert result.passed

    async def test_reading_submission_no_ground_truth(self):
        result = await verify_submission(
            category="reading",
            response="ANSWER: yes",
            test_code=None,
            ground_truth=None,
            metadata={"answer_type": "boolean"},
        )
        assert not result.passed
        assert "ground truth" in result.feedback.lower()


class TestReadingPayout:
    def test_qasper_payout(self):
        payout = calculate_payout("qasper", 0.5, 1.0, 1)
        assert payout == pytest.approx(0.015 * 1.5, abs=1e-6)

    def test_sciq_payout(self):
        payout = calculate_payout("sciq", 0.1, 1.0, 1)
        assert payout == pytest.approx(0.010 * 0.6, abs=1e-6)


class TestReadingDatabaseIntegration:
    @pytest.fixture
    async def test_db(self, tmp_path):
        """Create a temporary database for testing."""
        db = TaskShopDatabase(tmp_path / "test_taskshop.db")
        await db.connect()
        yield db
        await db.close()

    async def test_reading_task_verification(self, test_db):
        await test_db.insert_task({
            "benchmark": "sciq",
            "benchmark_id": "sciq/0",
            "category": "reading",
            "difficulty": 0.3,
            "title": "SciQ: What is photosynthesis?",
            "prompt": "PASSAGE: Plants convert sunlight...\n\n"
            "A) Respiration\nB) Photosynthesis\n...",
            "ground_truth": "B",
            "metadata": {"answer_type": "multiple_choice", "correct_letter": "B"},
        })

        assignment = await test_db.claim_task("bot-1")
        assert assignment is not None

        result = await test_db.submit_cycle(
            assignment_id=assignment["assignment_id"],
            bot_name="bot-1",
            action="submit",
            response_content="The answer is ANSWER: B",
        )

        assert result["status"] == "completed"
        assert result["score"] == 1.0
        assert result["payout"] > 0
