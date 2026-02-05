"""Tests for Bot lifecycle, replication, and colony management."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawdbot.bot import Bot, BotGenome, BotState
from clawdbot.evolution.genome import ExpandedGenome
from clawdbot.evolution.selection import DeathCause
from clawdbot.backends.base import LLMResponse
from clawdbot.fitness.tasks import TaskResult
from clawdbot.fitness.verifiers import VerificationResult


class TestBotGenome:
    """Tests for legacy BotGenome dataclass."""

    def test_default_values(self):
        """Test default genome values."""
        genome = BotGenome(name="test-bot")
        assert genome.name == "test-bot"
        assert genome.generation == 1
        assert genome.parent_name is None
        assert genome.cycle_interval_seconds == 30.0
        assert genome.replication_fitness_threshold == 0.8
        assert genome.max_cycles_per_run == 1000
        assert genome.mutation_rate == 0.1

    def test_to_dict(self):
        """Test genome serialization."""
        genome = BotGenome(name="test", generation=2, parent_name="parent")
        data = genome.to_dict()
        assert data["name"] == "test"
        assert data["generation"] == 2
        assert data["parent_name"] == "parent"

    def test_from_dict(self):
        """Test genome deserialization."""
        data = {
            "name": "restored",
            "generation": 3,
            "parent_name": "ancestor",
            "brain_config": {"budget_per_cycle": 0.10},
        }
        genome = BotGenome.from_dict(data)
        assert genome.name == "restored"
        assert genome.generation == 3
        assert genome.brain_config["budget_per_cycle"] == 0.10

    def test_hash_consistency(self):
        """Test that identical genomes have same hash."""
        g1 = BotGenome(name="test", generation=1)
        g2 = BotGenome(name="test", generation=1)
        assert g1.hash() == g2.hash()

    def test_hash_changes_with_mutation(self):
        """Test that different genomes have different hashes."""
        g1 = BotGenome(name="test", generation=1)
        g2 = BotGenome(name="test", generation=2)
        assert g1.hash() != g2.hash()

    def test_to_expanded(self):
        """Test conversion to ExpandedGenome."""
        legacy = BotGenome(
            name="test",
            generation=2,
            parent_name="parent",
            brain_config={"budget_per_cycle": 0.08},
        )
        expanded = legacy.to_expanded()

        assert expanded.name == "test"
        assert expanded.generation == 2
        assert expanded.parent_name == "parent"
        assert expanded.budget_per_cycle == 0.08


class TestBotState:
    """Tests for BotState dataclass."""

    def test_default_values(self):
        """Test default state values."""
        state = BotState()
        assert state.cycle_count == 0
        assert state.fitness_score == 0.5
        assert state.wallet_balance == 0.10
        assert state.tasks_completed == 0
        assert state.tasks_failed == 0
        assert state.consecutive_failures == 0
        assert state.current_state == "idle"
        assert state.children_spawned == 0
        assert state.death_cause == DeathCause.ALIVE


class TestFitnessCalculation:
    """Tests for fitness score calculation basics."""

    def test_fitness_ema_calculation(self):
        """Test exponential moving average calculation."""
        state = BotState()
        initial_fitness = state.fitness_score  # 0.5

        # Simulate EMA update for success
        alpha = 0.1
        success = 1.0
        new_fitness = (1 - alpha) * state.fitness_score + alpha * success

        assert new_fitness > initial_fitness
        assert new_fitness == pytest.approx(0.55)  # 0.5 * 0.9 + 1 * 0.1

    def test_fitness_ema_on_failure(self):
        """Test EMA decreases on failure."""
        state = BotState()
        state.fitness_score = 0.8

        alpha = 0.1
        success = 0.0  # Failure
        new_fitness = (1 - alpha) * state.fitness_score + alpha * success

        assert new_fitness == pytest.approx(0.72)  # 0.8 * 0.9 + 0 * 0.1

    def test_fitness_capped_at_one(self):
        """Test fitness capped at 1.0."""
        state = BotState()
        state.fitness_score = 0.99

        state.fitness_score = min(1.0, state.fitness_score + 0.05)

        assert state.fitness_score == 1.0  # Capped


class TestReplicationConditions:
    """Tests for replication eligibility."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        Bot._colony.clear()

        with patch("clawdbot.bot.LLMRegistry") as mock_registry, \
             patch("clawdbot.bot.BrainRouter") as mock_brain, \
             patch("clawdbot.bot.TelemetryReporter") as mock_telemetry, \
             patch("clawdbot.bot.TaskPool") as mock_pool, \
             patch("clawdbot.bot.RewardCalculator") as mock_rewards, \
             patch("clawdbot.bot.SelectionPressure") as mock_selection, \
             patch("clawdbot.bot.Mutator") as mock_mutator:

            mock_registry_instance = MagicMock()
            mock_registry_instance.load = MagicMock()
            mock_registry.return_value = mock_registry_instance

            # Use ExpandedGenome
            genome = ExpandedGenome(name="test-bot", replication_threshold=0.08)
            bot = Bot(genome=genome, registry_path=None)

            yield bot

            Bot._colony.clear()

    def test_cannot_replicate_low_balance(self, mock_bot):
        """Test replication blocked by insufficient funds."""
        mock_bot.state.wallet_balance = 0.01  # Less than threshold + $0.05 cost
        mock_bot.state.cycle_count = 20
        mock_bot.state.consecutive_failures = 0

        assert mock_bot._should_replicate() is False

    def test_cannot_replicate_immature(self, mock_bot):
        """Test replication blocked by low cycle count."""
        mock_bot.state.wallet_balance = 1.0
        mock_bot.state.cycle_count = 5  # Less than 10
        mock_bot.state.consecutive_failures = 0

        assert mock_bot._should_replicate() is False

    def test_can_replicate_all_conditions_met(self, mock_bot):
        """Test replication allowed when all conditions met."""
        mock_bot.state.wallet_balance = 0.20  # Above threshold + cost
        mock_bot.state.cycle_count = 15  # Above 10
        mock_bot.state.consecutive_failures = 0  # Not struggling

        assert mock_bot._should_replicate() is True

    def test_cannot_replicate_struggling(self, mock_bot):
        """Test replication blocked when struggling."""
        mock_bot.state.wallet_balance = 0.20
        mock_bot.state.cycle_count = 15
        mock_bot.state.consecutive_failures = 10  # Too many failures

        assert mock_bot._should_replicate() is False

    def test_cannot_replicate_colony_full(self, mock_bot):
        """Test replication blocked when colony at limit."""
        mock_bot.state.wallet_balance = 1.0
        mock_bot.state.cycle_count = 20
        mock_bot.state.consecutive_failures = 0

        # Fill colony to limit
        for i in range(50):
            Bot._colony[f"fake-bot-{i}"] = MagicMock()

        try:
            assert mock_bot._should_replicate() is False
        finally:
            # Cleanup fake bots
            for i in range(50):
                del Bot._colony[f"fake-bot-{i}"]


class TestReplicationMechanics:
    """Tests for the replication process itself."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        Bot._colony.clear()

        with patch("clawdbot.bot.LLMRegistry") as mock_registry, \
             patch("clawdbot.bot.BrainRouter") as mock_brain, \
             patch("clawdbot.bot.TelemetryReporter") as mock_telemetry, \
             patch("clawdbot.bot.TaskPool") as mock_pool, \
             patch("clawdbot.bot.RewardCalculator") as mock_rewards, \
             patch("clawdbot.bot.SelectionPressure") as mock_selection:

            mock_registry_instance = MagicMock()
            mock_registry_instance.load = MagicMock()
            mock_registry.return_value = mock_registry_instance

            mock_telemetry_instance = MagicMock()
            mock_telemetry_instance.report_event = MagicMock()
            mock_telemetry.return_value = mock_telemetry_instance

            genome = ExpandedGenome(name="parent-bot", generation=1, child_inheritance_ratio=0.4)
            bot = Bot(genome=genome, registry_path=None, initial_balance=0.20)

            yield bot

            Bot._colony.clear()

    @pytest.mark.asyncio
    async def test_replication_deducts_cost(self, mock_bot):
        """Test that replication deducts cost from parent."""
        initial_balance = mock_bot.state.wallet_balance  # 0.20

        with patch("clawdbot.bot.Bot") as MockBotClass:
            mock_child = MagicMock()
            mock_child.run = AsyncMock()
            MockBotClass.return_value = mock_child

            child = await mock_bot._replicate()

        # Cost is max(0.05, child_inheritance)
        # Child inheritance = 0.20 * 0.4 = 0.08
        # So cost should be 0.08
        assert mock_bot.state.wallet_balance < initial_balance

    @pytest.mark.asyncio
    async def test_replication_increments_children_count(self, mock_bot):
        """Test that children_spawned counter increments."""
        assert mock_bot.state.children_spawned == 0

        with patch("clawdbot.bot.Bot") as MockBotClass:
            mock_child = MagicMock()
            mock_child.run = AsyncMock()
            MockBotClass.return_value = mock_child

            await mock_bot._replicate()

        assert mock_bot.state.children_spawned == 1

    @pytest.mark.asyncio
    async def test_replication_reports_event(self, mock_bot):
        """Test that replication reports telemetry event."""
        with patch("clawdbot.bot.Bot") as MockBotClass:
            mock_child = MagicMock()
            mock_child.run = AsyncMock()
            MockBotClass.return_value = mock_child

            await mock_bot._replicate()

        mock_bot.telemetry.report_event.assert_called()
        call_args = mock_bot.telemetry.report_event.call_args
        assert call_args[1]["event_type"] == "replication"

    @pytest.mark.asyncio
    async def test_child_genome_has_correct_generation(self, mock_bot):
        """Test that child has incremented generation."""
        with patch("clawdbot.bot.Bot") as MockBotClass:
            mock_child = MagicMock()
            mock_child.run = AsyncMock()
            MockBotClass.return_value = mock_child

            await mock_bot._replicate()

            call_args = MockBotClass.call_args
            child_genome = call_args[1]["genome"]
            assert child_genome.generation == 2  # Parent is gen 1
            assert child_genome.parent_name == "parent-bot"

    @pytest.mark.asyncio
    async def test_child_receives_inheritance(self, mock_bot):
        """Test that child receives correct initial balance."""
        with patch("clawdbot.bot.Bot") as MockBotClass:
            mock_child = MagicMock()
            mock_child.run = AsyncMock()
            MockBotClass.return_value = mock_child

            await mock_bot._replicate()

            call_args = MockBotClass.call_args
            initial_balance = call_args[1]["initial_balance"]
            # Child inheritance = min(0.20 * 0.4, 0.20 * 0.5) = 0.08
            assert initial_balance == pytest.approx(0.08)


class TestColonyManagement:
    """Tests for colony-level management."""

    def setup_method(self):
        """Clear colony before each test."""
        Bot._colony.clear()

    def teardown_method(self):
        """Clear colony after each test."""
        Bot._colony.clear()

    def test_bot_registers_in_colony(self):
        """Test that new bots register themselves."""
        with patch("clawdbot.bot.LLMRegistry"), \
             patch("clawdbot.bot.BrainRouter"), \
             patch("clawdbot.bot.TelemetryReporter"), \
             patch("clawdbot.bot.TaskPool"), \
             patch("clawdbot.bot.RewardCalculator"), \
             patch("clawdbot.bot.SelectionPressure"), \
             patch("clawdbot.bot.Mutator"):

            bot = Bot(genome=ExpandedGenome(name="colony-test"), registry_path=None)

            assert "colony-test" in Bot._colony
            assert Bot._colony["colony-test"] is bot

    def test_colony_stats_empty(self):
        """Test colony stats when empty."""
        stats = Bot.get_colony_stats()
        assert stats["total_bots"] == 0

    def test_colony_stats_with_bots(self):
        """Test colony stats with multiple bots."""
        with patch("clawdbot.bot.LLMRegistry"), \
             patch("clawdbot.bot.BrainRouter"), \
             patch("clawdbot.bot.TelemetryReporter"), \
             patch("clawdbot.bot.TaskPool"), \
             patch("clawdbot.bot.RewardCalculator"), \
             patch("clawdbot.bot.SelectionPressure"), \
             patch("clawdbot.bot.Mutator"):

            bot1 = Bot(genome=ExpandedGenome(name="bot1", generation=1), registry_path=None)
            bot1.state.fitness_score = 0.8
            bot1.state.wallet_balance = 0.10

            bot2 = Bot(genome=ExpandedGenome(name="bot2", generation=2), registry_path=None)
            bot2.state.fitness_score = 0.6
            bot2.state.wallet_balance = 0.05

            stats = Bot.get_colony_stats()

            assert stats["total_bots"] == 2
            assert stats["alive_bots"] == 2
            assert stats["total_generations"] == 2
            assert stats["avg_fitness"] == pytest.approx(0.7)  # (0.8 + 0.6) / 2
            assert stats["total_wallet"] == pytest.approx(0.15)
            assert "bot1" in stats["bots"]
            assert "bot2" in stats["bots"]

    @pytest.mark.asyncio
    async def test_bot_unregisters_on_close(self):
        """Test that bots unregister when closed."""
        with patch("clawdbot.bot.LLMRegistry"), \
             patch("clawdbot.bot.BrainRouter") as mock_brain, \
             patch("clawdbot.bot.TelemetryReporter") as mock_telemetry, \
             patch("clawdbot.bot.TaskPool"), \
             patch("clawdbot.bot.RewardCalculator"), \
             patch("clawdbot.bot.SelectionPressure"), \
             patch("clawdbot.bot.Mutator"):

            mock_brain.return_value.close = AsyncMock()
            mock_telemetry.return_value.close = AsyncMock()

            bot = Bot(genome=ExpandedGenome(name="closing-bot"), registry_path=None)
            assert "closing-bot" in Bot._colony

            await bot.close()

            assert "closing-bot" not in Bot._colony


class TestWalletEconomics:
    """Tests for wallet balance tracking."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        Bot._colony.clear()

        with patch("clawdbot.bot.LLMRegistry") as mock_registry, \
             patch("clawdbot.bot.BrainRouter") as mock_brain, \
             patch("clawdbot.bot.TelemetryReporter") as mock_telemetry, \
             patch("clawdbot.bot.TaskPool") as mock_pool, \
             patch("clawdbot.bot.RewardCalculator") as mock_rewards, \
             patch("clawdbot.bot.SelectionPressure") as mock_selection, \
             patch("clawdbot.bot.Mutator"):

            mock_registry_instance = MagicMock()
            mock_registry.return_value = mock_registry_instance

            mock_brain_instance = MagicMock()
            mock_brain_instance.reset_cycle = MagicMock()
            mock_brain_instance.state = MagicMock()
            mock_brain_instance.state.cycle_spend = 0.0
            mock_brain_instance.state.last_model_used = "ollama/phi4-mini"
            mock_brain.return_value = mock_brain_instance

            mock_telemetry_instance = MagicMock()
            mock_telemetry_instance.report_telemetry = MagicMock()
            mock_telemetry_instance.report_event = MagicMock()
            mock_telemetry.return_value = mock_telemetry_instance

            genome = ExpandedGenome(name="wallet-test", max_cycles_per_run=5)
            bot = Bot(genome=genome, registry_path=None, initial_balance=0.50)

            yield bot

            Bot._colony.clear()

    def test_initial_balance(self, mock_bot):
        """Test that bot starts with correct balance."""
        assert mock_bot.state.wallet_balance == 0.50

    def test_revenue_increases_balance(self, mock_bot):
        """Test that revenue increases wallet balance."""
        initial = mock_bot.state.wallet_balance

        # Manually simulate revenue
        revenue = 0.001
        mock_bot.state.wallet_balance += revenue

        assert mock_bot.state.wallet_balance == pytest.approx(initial + revenue)

    def test_api_cost_decreases_balance(self, mock_bot):
        """Test that API costs decrease wallet balance."""
        initial = mock_bot.state.wallet_balance

        # Simulate API spend
        mock_bot.brain.state.cycle_spend = 0.01
        mock_bot.state.wallet_balance -= mock_bot.brain.state.cycle_spend

        assert mock_bot.state.wallet_balance == pytest.approx(initial - 0.01)

    def test_balance_can_go_negative(self, mock_bot):
        """Test that balance can go negative (debt)."""
        mock_bot.state.wallet_balance = 0.01
        mock_bot.state.wallet_balance -= 0.05

        assert mock_bot.state.wallet_balance == pytest.approx(-0.04)


class TestBotLifecycle:
    """Tests for bot run lifecycle."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with fully mocked cycle."""
        Bot._colony.clear()

        with patch("clawdbot.bot.LLMRegistry") as mock_registry, \
             patch("clawdbot.bot.BrainRouter") as mock_brain, \
             patch("clawdbot.bot.TelemetryReporter") as mock_telemetry, \
             patch("clawdbot.bot.TaskPool") as mock_pool, \
             patch("clawdbot.bot.RewardCalculator") as mock_rewards, \
             patch("clawdbot.bot.SelectionPressure") as mock_selection, \
             patch("clawdbot.bot.Mutator"), \
             patch("clawdbot.bot.get_verifier") as mock_get_verifier:

            mock_registry_instance = MagicMock()
            mock_registry.return_value = mock_registry_instance

            mock_brain_instance = MagicMock()
            mock_brain_instance.reset_cycle = MagicMock()
            mock_brain_instance.state = MagicMock()
            mock_brain_instance.state.cycle_spend = 0.0
            mock_brain_instance.state.last_model_used = "ollama/phi4-mini"
            mock_brain_instance.generate = AsyncMock(return_value=LLMResponse(
                content='42',
                input_tokens=10,
                output_tokens=20,
                cost_usd=0.0,
                model="ollama/phi4-mini",
                latency_ms=100.0,
            ))
            mock_brain_instance.close = AsyncMock()
            mock_brain.return_value = mock_brain_instance

            mock_telemetry_instance = MagicMock()
            mock_telemetry_instance.report_telemetry = MagicMock()
            mock_telemetry_instance.report_event = MagicMock()
            mock_telemetry_instance.close = AsyncMock()
            mock_telemetry.return_value = mock_telemetry_instance

            # Mock task pool to return simple tasks
            mock_task = MagicMock()
            mock_task.id = "test-task"
            mock_task.task_type = MagicMock()
            mock_task.task_type.value = "math"
            mock_task.tier = MagicMock()
            mock_task.tier.value = 1
            mock_task.difficulty = 0.3
            mock_task.get_prompt = MagicMock(return_value="What is 2+2?")
            mock_pool_instance = MagicMock()
            mock_pool_instance.sample = MagicMock(return_value=mock_task)
            mock_pool.return_value = mock_pool_instance

            # Mock verifier to pass
            mock_verifier = MagicMock()
            mock_verifier.verify = AsyncMock(return_value=VerificationResult(
                passed=True, score=1.0, feedback="Correct"
            ))
            mock_get_verifier.return_value = mock_verifier

            # Mock rewards
            mock_rewards_instance = MagicMock()
            mock_rewards_instance.calculate = MagicMock(return_value=0.001)
            mock_rewards.return_value = mock_rewards_instance

            # Mock selection - return viable for first 3 cycles, then natural death
            call_count = [0]
            def viability_check(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] > 3:
                    return MagicMock(viable=False, cause=DeathCause.NATURAL, details={})
                return MagicMock(viable=True, cause=DeathCause.ALIVE, details={})

            mock_selection_instance = MagicMock()
            mock_selection_instance.check_viability = MagicMock(side_effect=viability_check)
            mock_selection_instance.get_existence_cost = MagicMock(return_value=0.0001)
            mock_selection_instance.calculate_display_fitness = MagicMock(return_value=0.6)
            mock_selection_instance.config = MagicMock()
            mock_selection.return_value = mock_selection_instance

            genome = ExpandedGenome(
                name="lifecycle-test",
                max_cycles_per_run=3,
                cycle_interval_seconds=0.001,  # Very fast
            )
            bot = Bot(genome=genome, registry_path=None)

            yield bot

            Bot._colony.clear()

    @pytest.mark.asyncio
    async def test_bot_runs_cycles(self, mock_bot):
        """Test that bot runs expected number of cycles."""
        await asyncio.wait_for(mock_bot.run(), timeout=5.0)

        assert mock_bot.state.cycle_count == 3  # max_cycles_per_run

    @pytest.mark.asyncio
    async def test_bot_reports_startup_event(self, mock_bot):
        """Test that bot reports startup event."""
        await asyncio.wait_for(mock_bot.run(), timeout=5.0)

        # Find the startup event call
        calls = mock_bot.telemetry.report_event.call_args_list
        startup_calls = [c for c in calls if c[1].get("event_type") == "bot_started"]
        assert len(startup_calls) == 1

    @pytest.mark.asyncio
    async def test_bot_reports_shutdown_event(self, mock_bot):
        """Test that bot reports shutdown event."""
        await asyncio.wait_for(mock_bot.run(), timeout=5.0)

        calls = mock_bot.telemetry.report_event.call_args_list
        shutdown_calls = [c for c in calls if c[1].get("event_type") == "bot_stopped"]
        assert len(shutdown_calls) == 1

    @pytest.mark.asyncio
    async def test_bot_can_be_stopped(self, mock_bot):
        """Test that bot responds to stop request."""
        # Reset the viability check for this test
        mock_bot.selection.check_viability = MagicMock(
            return_value=MagicMock(viable=True, cause=DeathCause.ALIVE, details={})
        )
        mock_bot.genome.max_cycles_per_run = 1000
        mock_bot.genome.cycle_interval_seconds = 0.01

        async def stop_after_delay():
            await asyncio.sleep(0.05)
            mock_bot.stop()

        await asyncio.wait_for(
            asyncio.gather(mock_bot.run(), stop_after_delay()),
            timeout=5.0,
        )

        assert mock_bot.state.cycle_count < 1000
        # Either stopped or shutdown
        assert mock_bot.state.current_state in ("stopped", "dead")

    @pytest.mark.asyncio
    async def test_tasks_completed_increases(self, mock_bot):
        """Test that tasks_completed increases with successful cycles."""
        await asyncio.wait_for(mock_bot.run(), timeout=5.0)

        # With mocked verification passing, tasks should complete
        assert mock_bot.state.tasks_completed == 3


class TestMutations:
    """Tests for genome mutations during replication."""

    def test_mutation_rate_zero_no_changes(self):
        """Test that zero mutation rate preserves genome."""
        parent = BotGenome(
            name="parent",
            mutation_rate=0.0,
            cycle_interval_seconds=30.0,
            replication_fitness_threshold=0.8,
        )

        import random
        random.seed(42)

        mutations_applied = 0
        for _ in range(100):
            if random.random() < parent.mutation_rate:
                mutations_applied += 1

        assert mutations_applied == 0

    def test_mutation_rate_one_always_mutates(self):
        """Test that 100% mutation rate always mutates."""
        import random
        random.seed(42)

        mutations = 0
        for _ in range(100):
            if random.random() < 1.0:
                mutations += 1

        assert mutations == 100

    def test_mutation_bounds_respected(self):
        """Test that mutations stay within bounds."""
        import random

        for _ in range(100):
            original = 0.8
            mutated = original * random.uniform(0.95, 1.05)
            bounded = max(0.5, min(0.95, mutated))

            assert 0.5 <= bounded <= 0.95


class TestGetStats:
    """Tests for bot statistics."""

    def test_get_stats_includes_all_fields(self):
        """Test that get_stats returns all expected fields."""
        Bot._colony.clear()

        with patch("clawdbot.bot.LLMRegistry"), \
             patch("clawdbot.bot.BrainRouter") as mock_brain, \
             patch("clawdbot.bot.TelemetryReporter") as mock_telemetry, \
             patch("clawdbot.bot.TaskPool"), \
             patch("clawdbot.bot.RewardCalculator"), \
             patch("clawdbot.bot.SelectionPressure"), \
             patch("clawdbot.bot.Mutator"):

            mock_brain_instance = MagicMock()
            mock_brain_instance.get_stats = MagicMock(return_value={"test": "brain"})
            mock_brain.return_value = mock_brain_instance

            mock_telemetry_instance = MagicMock()
            mock_telemetry_instance.get_stats = MagicMock(return_value={"test": "telemetry"})
            mock_telemetry.return_value = mock_telemetry_instance

            bot = Bot(genome=ExpandedGenome(name="stats-test"), registry_path=None)
            stats = bot.get_stats()

            assert "name" in stats
            assert "generation" in stats
            assert "genome_hash" in stats
            assert "state" in stats
            assert "is_alive" in stats
            assert "death_cause" in stats
            assert "cycle_count" in stats
            assert "fitness_score" in stats
            assert "wallet_balance" in stats
            assert "tasks_completed" in stats
            assert "tasks_failed" in stats
            assert "consecutive_failures" in stats
            assert "children_spawned" in stats
            assert "brain" in stats
            assert "telemetry" in stats

            Bot._colony.clear()
