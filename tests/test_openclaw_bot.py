"""Tests for OpenClawBot lifecycle and integration."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawdbot.openclaw_bot import (
    OpenClawBot,
    OpenClawBotState,
    OpenClawMutator,
)
from clawdbot.evolution.openclaw_genome import OpenClawGenome
from clawdbot.evolution.selection import SelectionConfig, DeathCause


class TestOpenClawBotState:
    """Tests for OpenClawBotState."""

    def test_default_state(self):
        """Test default state values."""
        state = OpenClawBotState()

        assert state.cycle_count == 0
        assert state.fitness_score == 0.5
        assert state.wallet_balance == 0.30  # Seed funding for OpenClaw
        assert state.death_cause == DeathCause.ALIVE

    def test_state_tracking(self):
        """Test state modification."""
        state = OpenClawBotState()

        state.cycle_count = 10
        state.tasks_completed = 8
        state.tasks_failed = 2
        state.wallet_balance = 0.75

        assert state.cycle_count == 10
        assert state.tasks_completed == 8
        assert state.tasks_failed == 2
        assert state.wallet_balance == 0.75


class TestOpenClawBotInitialization:
    """Tests for OpenClawBot initialization."""

    def test_init_with_genome(self):
        """Test initialization with OpenClawGenome."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(
                name="test-bot",
                generation=1,
            )

            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
            )

            assert bot.name == "test-bot"
            assert bot.generation == 1
            assert bot.is_alive

            # Cleanup
            asyncio.run(bot.close())

    def test_init_with_dict(self):
        """Test initialization with genome dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome_dict = {
                "name": "dict-bot",
                "generation": 2,
                "openclaw_model": "claude_code/opus-4-5",
            }

            bot = OpenClawBot(
                genome=genome_dict,
                workspace_base=tmpdir,
            )

            assert bot.name == "dict-bot"
            assert bot.generation == 2
            assert bot.genome.openclaw_model == "claude_code/opus-4-5"

            asyncio.run(bot.close())

    def test_init_with_initial_balance(self):
        """Test initialization with custom balance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(name="balance-bot")

            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
                initial_balance=1.50,
            )

            assert bot.state.wallet_balance == 1.50

            asyncio.run(bot.close())

    def test_colony_registration(self):
        """Test that bots register in the colony."""
        OpenClawBot._colony.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(name="colony-bot")

            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
            )

            assert "colony-bot" in OpenClawBot._colony

            asyncio.run(bot.close())

            assert "colony-bot" not in OpenClawBot._colony


class TestOpenClawBotLifecycle:
    """Tests for bot lifecycle methods."""

    @pytest.mark.asyncio
    async def test_viability_check_alive(self):
        """Test viability check for healthy bot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(name="healthy-bot")
            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
                initial_balance=0.50,
            )

            check = bot._check_viability()

            assert check.viable
            assert check.cause == DeathCause.ALIVE

            await bot.close()

    @pytest.mark.asyncio
    async def test_viability_check_bankruptcy(self):
        """Test viability check for bankrupt bot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(name="poor-bot")
            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
                initial_balance=0.001,  # Below threshold
            )

            check = bot._check_viability()

            assert not check.viable
            assert check.cause == DeathCause.BANKRUPTCY

            await bot.close()

    @pytest.mark.asyncio
    async def test_stop_request(self):
        """Test stop request handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(name="stop-bot")
            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
            )

            bot.stop()

            assert bot._stop_requested
            assert bot.state.death_cause == DeathCause.SHUTDOWN

            await bot.close()

    @pytest.mark.asyncio
    async def test_should_replicate_false_initially(self):
        """Test that new bots shouldn't replicate immediately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(
                name="young-bot",
                min_reproduction_age=10,
            )
            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
                initial_balance=0.50,
            )

            # Cycle count is 0, too young
            assessment = bot._assess_reproduction_readiness()
            assert not assessment.should_reproduce

            await bot.close()

    @pytest.mark.asyncio
    async def test_should_replicate_when_wealthy(self):
        """Test that wealthy, mature bots can replicate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(
                name="wealthy-bot",
                min_reproduction_age=10,
                safety_margin_cycles=5,
                reproduction_confidence_threshold=0.3,
                min_success_rate_for_reproduction=0.3,
            )
            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
                initial_balance=1.00,  # Rich
            )

            # Simulate maturity and good performance
            bot.state.cycle_count = 15
            bot.state.consecutive_failures = 0

            # Build up some economic history
            for i in range(20):
                bot.awareness.record_cycle(
                    balance=1.00,
                    income=0.02,
                    cost=0.001,
                    task_type="coding",
                    task_success=True,
                )

            assessment = bot._assess_reproduction_readiness()
            assert assessment.should_reproduce

            await bot.close()


class TestOpenClawBotReplication:
    """Tests for bot replication."""

    @pytest.mark.asyncio
    async def test_replicate_creates_child(self):
        """Test that replication creates a child bot."""
        from clawdbot.evolution.reproduction import ReproductiveAssessment

        OpenClawBot._colony.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            parent = OpenClawGenome(
                name="parent-bot",
                generation=1,
            )
            parent_bot = OpenClawBot(
                genome=parent,
                workspace_base=tmpdir,
                initial_balance=1.00,
            )

            # Create a mock assessment
            assessment = ReproductiveAssessment.yes(
                confidence=0.75,
                investment=0.20,
                urgency=0.3,
                reasons=["Test reproduction"],
            )

            # Mock the child's run to prevent actual execution
            with patch.object(OpenClawBot, "run", new_callable=AsyncMock):
                child_bot = await parent_bot._replicate(assessment)

            assert child_bot is not None
            assert child_bot.generation == 2
            assert child_bot.genome.parent_name == "parent-bot"
            assert parent_bot.state.children_spawned == 1

            # Cleanup
            await parent_bot.close()
            await child_bot.close()

    @pytest.mark.asyncio
    async def test_replicate_deducts_cost(self):
        """Test that replication deducts cost from parent."""
        from clawdbot.evolution.reproduction import ReproductiveAssessment

        OpenClawBot._colony.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            parent = OpenClawGenome(
                name="spending-parent",
                child_inheritance_ratio=0.3,
            )
            parent_bot = OpenClawBot(
                genome=parent,
                workspace_base=tmpdir,
                initial_balance=1.00,
            )

            initial_balance = parent_bot.state.wallet_balance

            # Create assessment with specific investment
            assessment = ReproductiveAssessment.yes(
                confidence=0.75,
                investment=0.25,
                urgency=0.3,
                reasons=["Test reproduction"],
            )

            with patch.object(OpenClawBot, "run", new_callable=AsyncMock):
                await parent_bot._replicate(assessment)

            assert parent_bot.state.wallet_balance < initial_balance
            # Should have deducted the investment amount
            assert parent_bot.state.wallet_balance == pytest.approx(initial_balance - 0.25)

            await parent_bot.close()


class TestOpenClawBotStats:
    """Tests for bot statistics."""

    def test_get_stats(self):
        """Test getting bot statistics."""
        OpenClawBot._colony.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(
                name="stats-bot",
                openclaw_model="claude_code/opus-4-5",
                thinking_level="high",
            )
            bot = OpenClawBot(
                genome=genome,
                workspace_base=tmpdir,
            )

            stats = bot.get_stats()

            assert stats["name"] == "stats-bot"
            assert stats["bot_type"] == "openclaw"
            assert stats["model"] == "claude_code/opus-4-5"
            assert stats["thinking_level"] == "high"
            assert "fitness_score" in stats
            assert "wallet_balance" in stats
            # Check new awareness stats are included
            assert "awareness" in stats
            assert "offspring_history" in stats
            assert "family" in stats

            asyncio.run(bot.close())

    def test_get_colony_stats(self):
        """Test getting colony-wide statistics."""
        OpenClawBot._colony.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple bots (all using claude to avoid API key issues)
            genomes = [
                OpenClawGenome(name="bot-1", openclaw_model="claude_code/opus-4-5"),
                OpenClawGenome(name="bot-2", openclaw_model="claude_code/sonnet-4-5"),
            ]

            bots = []
            for genome in genomes:
                bot = OpenClawBot(
                    genome=genome,
                    workspace_base=tmpdir,
                )
                bots.append(bot)

            stats = OpenClawBot.get_colony_stats()

            assert stats["total_bots"] == 2
            assert stats["alive_bots"] == 2
            assert "model_distribution" in stats
            assert stats["model_distribution"]["claude_code/opus-4-5"] == 1
            assert stats["model_distribution"]["claude_code/sonnet-4-5"] == 1

            # Cleanup
            for bot in bots:
                asyncio.run(bot.close())


class TestOpenClawMutatorIntegration:
    """Integration tests for OpenClawMutator with bots."""

    def test_mutator_in_replication(self):
        """Test that mutator is used correctly in replication."""
        parent = OpenClawGenome(
            name="mutating-parent",
            generation=1,
            mutation_rate=1.0,  # High rate
        )

        mutator = OpenClawMutator()
        result = mutator.mutate(parent, "child")

        assert result.genome.name == "child"
        assert result.genome.generation == 2
        # With high mutation rate, should have some mutations
        # (though it's probabilistic)

    def test_mutator_bounds_respected(self):
        """Test that mutation bounds are respected."""
        parent = OpenClawGenome(
            name="bounded-parent",
            mutation_rate=1.0,
            tool_risk_tolerance=0.5,
        )

        mutator = OpenClawMutator()

        # Run many mutations and check bounds
        for i in range(20):
            result = mutator.mutate(parent, f"child-{i}")
            assert 0.0 <= result.genome.tool_risk_tolerance <= 1.0


class TestOpenClawBotObservability:
    """Tests for bot observability - conversation logging and reflections."""

    def test_conversation_logger_initialized(self):
        """Test that conversation logger is created on bot init."""
        OpenClawBot._colony.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(name="logger-bot")
            bot = OpenClawBot(genome=genome, workspace_base=tmpdir)

            assert bot.conversation_logger is not None
            assert hasattr(bot.conversation_logger, "log_conversation")

            asyncio.run(bot.close())

    def test_conversation_logger_logs_task(self):
        """Test that conversation logger can log task execution."""
        from clawdbot.conversation_logger import ConversationLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = ConversationLogger(db_path=db_path, run_id="test-run")

            # Log a task execution
            conv_id = logger.log_conversation(
                bot_name="test-bot",
                bot_generation=1,
                model="claude_code/opus-4-5",
                interaction_type="task_execution",
                user_prompt="Solve this math problem",
                assistant_response="The answer is 42",
                task_id="task-123",
                task_type="math",
                input_tokens=100,
                output_tokens=50,
                latency_ms=1500,
                cost_usd=0.001,
                success=True,
                score=0.95,
            )

            assert conv_id is not None

            # Verify it was logged
            convs = logger.get_bot_conversations("test-bot")
            assert len(convs) == 1
            assert convs[0].interaction_type == "task_execution"
            assert convs[0].task_id == "task-123"
            assert convs[0].success is True

            logger.close()

    def test_conversation_logger_logs_reflection(self):
        """Test that conversation logger can log reflections."""
        from clawdbot.conversation_logger import ConversationLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = ConversationLogger(db_path=db_path, run_id="test-run")

            # Log a reflection
            conv_id = logger.log_conversation(
                bot_name="reflective-bot",
                bot_generation=2,
                model="cerebras/glm-4",
                interaction_type="reflection_periodic",
                user_prompt="Reflect on your recent performance",
                assistant_response="I've been doing well, completing 8 out of 10 tasks...",
                input_tokens=50,
                output_tokens=100,
                latency_ms=800,
                cost_usd=0.0005,
            )

            assert conv_id is not None

            # Verify it was logged as a reflection
            reflections = logger.get_reflections("reflective-bot")
            assert len(reflections) == 1
            assert "reflection" in reflections[0].interaction_type

            logger.close()

    def test_conversation_logger_searchable(self):
        """Test that logged conversations are searchable."""
        from clawdbot.conversation_logger import ConversationLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = ConversationLogger(db_path=db_path, run_id="test-run")

            # Log multiple conversations
            logger.log_conversation(
                bot_name="bot-1",
                bot_generation=1,
                model="claude",
                interaction_type="task_execution",
                user_prompt="Write a fibonacci function",
                assistant_response="def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)",
            )

            logger.log_conversation(
                bot_name="bot-2",
                bot_generation=1,
                model="opus",
                interaction_type="reflection_death",
                user_prompt="Share your final thoughts",
                assistant_response="I learned that economic survival requires balance",
            )

            # Search for fibonacci
            results = logger.search("fibonacci")
            assert len(results) == 1
            assert results[0].bot_name == "bot-1"

            # Search for survival
            results = logger.search("survival")
            assert len(results) == 1
            assert results[0].bot_name == "bot-2"

            logger.close()

    def test_conversation_logger_closed_on_bot_close(self):
        """Test that conversation logger is closed when bot closes."""
        OpenClawBot._colony.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            genome = OpenClawGenome(name="close-test-bot")
            bot = OpenClawBot(genome=genome, workspace_base=tmpdir)

            # Mock the logger
            mock_logger = MagicMock()
            bot.conversation_logger = mock_logger

            asyncio.run(bot.close())

            mock_logger.close.assert_called_once()
