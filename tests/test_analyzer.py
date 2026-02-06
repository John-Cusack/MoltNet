"""Tests for the analyzer module."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from analyzer.database import AnalyzerDatabase
from analyzer.run_manager import RunManager
from clawdbot.conversation_logger import ConversationLogger
from clawdbot.reflection import (
    ReflectionContext,
    build_reflection_prompt,
    should_reflect_periodic,
    should_reflect_milestone,
    should_reflect_failure,
)


class TestConversationLogger:
    """Tests for ConversationLogger."""

    def test_logger_disabled(self):
        """Logger should return UUIDs even when disabled."""
        logger = ConversationLogger(enabled=False)
        conv_id = logger.log_conversation(
            bot_name="test-bot",
            bot_generation=0,
            model="test-model",
            interaction_type="test",
            user_prompt="hello",
        )
        assert conv_id is not None
        assert len(conv_id) == 36  # UUID format

    def test_logger_creates_database(self):
        """Logger should create database file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = ConversationLogger(db_path=db_path, run_id="test-run")

            conv_id = logger.log_conversation(
                bot_name="test-bot",
                bot_generation=1,
                model="claude_code/opus-4-5",
                interaction_type="task_execution",
                user_prompt="Solve this task",
                assistant_response="Here is the solution",
                input_tokens=100,
                output_tokens=50,
                latency_ms=1500,
                cost_usd=0.001,
                success=True,
                score=0.95,
            )

            assert conv_id is not None
            assert db_path.exists()

            # Verify data was logged
            convs = logger.get_bot_conversations("test-bot")
            assert len(convs) == 1
            assert convs[0].interaction_type == "task_execution"
            assert convs[0].success is True

            logger.close()

    def test_search_conversations(self):
        """Logger should support full-text search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = ConversationLogger(db_path=db_path, run_id="test-run")

            logger.log_conversation(
                bot_name="bot1",
                bot_generation=1,
                model="claude",
                interaction_type="reflection_periodic",
                user_prompt="Reflect on your existence",
                assistant_response="I think therefore I am",
            )

            logger.log_conversation(
                bot_name="bot2",
                bot_generation=1,
                model="claude",
                interaction_type="task_execution",
                user_prompt="Write a function",
                assistant_response="def foo(): pass",
            )

            # Search should find the reflection
            results = logger.search("existence")
            assert len(results) == 1
            assert results[0].bot_name == "bot1"

            logger.close()

    def test_get_model_conversations(self):
        """Logger should filter by model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = ConversationLogger(db_path=db_path, run_id="test-run")

            logger.log_conversation(
                bot_name="bot1",
                bot_generation=1,
                model="claude_code/opus-4-5",
                interaction_type="reflection_periodic",
                user_prompt="Test",
            )

            logger.log_conversation(
                bot_name="bot2",
                bot_generation=1,
                model="cerebras/glm-4",
                interaction_type="task_execution",
                user_prompt="Test",
            )

            opus_convs = logger.get_model_conversations("opus")
            assert len(opus_convs) == 1
            assert opus_convs[0].bot_name == "bot1"

            logger.close()


class TestReflection:
    """Tests for reflection system."""

    def test_should_reflect_periodic(self):
        """Periodic reflection should trigger every 15 cycles."""
        assert not should_reflect_periodic(0)
        assert not should_reflect_periodic(7)
        assert should_reflect_periodic(15)
        assert should_reflect_periodic(30)
        assert not should_reflect_periodic(31)
        assert should_reflect_periodic(45)

    def test_should_reflect_milestone(self):
        """Milestone reflection should trigger at key cycles."""
        assert not should_reflect_milestone(49)
        assert should_reflect_milestone(50)
        assert should_reflect_milestone(100)
        assert should_reflect_milestone(200)
        assert should_reflect_milestone(500)
        assert not should_reflect_milestone(150)

    def test_should_reflect_failure(self):
        """Failure reflection should trigger after 3 consecutive failures."""
        assert not should_reflect_failure(2, False)
        assert should_reflect_failure(3, False)
        assert should_reflect_failure(5, False)
        assert not should_reflect_failure(3, True)  # Already reflected

    def test_build_reflection_prompt(self):
        """Should build valid reflection prompts."""
        context = ReflectionContext(
            bot_name="test-bot",
            cycle_count=50,
            balance=0.25,
            success_rate=0.8,
            tasks_completed=40,
            tasks_failed=10,
            children_count=2,
            children_alive=1,
        )

        prompt = build_reflection_prompt("milestone", context)

        assert "test-bot" in prompt
        assert "50" in prompt
        assert "survived" in prompt.lower()

    def test_reflection_prompt_types(self):
        """All reflection types should produce valid prompts."""
        context = ReflectionContext(
            bot_name="test",
            cycle_count=100,
            balance=0.5,
            success_rate=0.7,
            tasks_completed=70,
            tasks_failed=30,
            children_count=3,
            children_alive=2,
            consecutive_failures=4,
            death_cause="bankruptcy",
            final_balance=0.001,
            cycles_lived=100,
            children_spawned=3,
            children_survived=2,
            confidence=0.8,
            investment=0.15,
            urgency=0.3,
        )

        for reflection_type in ["periodic", "milestone", "pre_reproduction", "post_failure", "death"]:
            prompt = build_reflection_prompt(reflection_type, context)
            assert len(prompt) > 50
            assert "test" in prompt


class TestAnalyzerDatabase:
    """Tests for analyzer database."""

    @pytest.fixture
    def db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "analyzer.db"
            database = AnalyzerDatabase(db_path)
            yield database

    @pytest.mark.asyncio
    async def test_create_run(self, db):
        """Should create run records."""
        await db.connect()

        run_id = await db.create_run("test-run", config={"max_bots": 10})

        assert run_id == "test-run"

        run = await db.get_run("test-run")
        assert run is not None
        assert run["run_id"] == "test-run"

        await db.close()

    @pytest.mark.asyncio
    async def test_log_conversation(self, db):
        """Should log conversations."""
        await db.connect()
        await db.create_run("test-run")

        conv_id = await db.log_conversation(
            run_id="test-run",
            bot_name="bot1",
            bot_generation=1,
            model="claude",
            interaction_type="task_execution",
            user_prompt="Hello",
            assistant_response="Hi there",
            input_tokens=10,
            output_tokens=5,
        )

        assert conv_id is not None

        conv = await db.get_conversation(conv_id)
        assert conv is not None
        assert conv["bot_name"] == "bot1"

        await db.close()

    @pytest.mark.asyncio
    async def test_search_conversations(self, db):
        """Should support FTS search."""
        await db.connect()
        await db.create_run("test-run")

        await db.log_conversation(
            run_id="test-run",
            bot_name="bot1",
            bot_generation=1,
            model="claude",
            interaction_type="reflection_death",
            user_prompt="What are your final thoughts?",
            assistant_response="I learned that perseverance matters most",
        )

        results = await db.search_conversations("perseverance", run_id="test-run")
        assert len(results) == 1
        assert "perseverance" in results[0]["assistant_response"]

        await db.close()


class TestRunManager:
    """Tests for run manager."""

    def test_start_and_list_runs(self):
        """Should start runs and list them."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = RunManager(data_dir=tmpdir)

            run_id = manager.start_run(config={"test": True})

            assert run_id is not None

            runs = manager.list_runs()
            assert len(runs) == 1
            assert runs[0]["run_id"] == run_id
            assert runs[0]["status"] == "running"

    def test_end_run(self):
        """Should end runs and update metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = RunManager(data_dir=tmpdir)

            run_id = manager.start_run()
            result = manager.end_run(
                run_id,
                stats={"total_bots": 5},
                combine=False,  # Skip combining for test
                archive=False,  # Skip archiving for test
            )

            assert result["run_id"] == run_id

            info = manager.get_run_info(run_id)
            assert info["status"] == "completed"
            assert info["final_stats"]["total_bots"] == 5
