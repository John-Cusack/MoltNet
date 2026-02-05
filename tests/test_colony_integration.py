"""Integration tests for colony behavior with mocked LLM and fitness system."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawdbot.bot import Bot, BotGenome, BotState
from clawdbot.evolution.genome import ExpandedGenome
from clawdbot.evolution.selection import DeathCause
from clawdbot.backends.base import LLMResponse
from clawdbot.fitness.verifiers import VerificationResult


def create_mocked_bot(
    name: str,
    generation: int = 1,
    balance: float = 0.50,
    task_passes: bool = True,
    api_cost: float = 0.0,
) -> Bot:
    """Create a bot with fully mocked dependencies for testing.

    Args:
        name: Bot name
        generation: Generation number
        balance: Initial wallet balance
        task_passes: Whether mocked tasks should pass
        api_cost: Cost per API call
    """
    with patch("clawdbot.bot.LLMRegistry") as mock_registry, \
         patch("clawdbot.bot.BrainRouter") as mock_brain, \
         patch("clawdbot.bot.TelemetryReporter") as mock_telemetry, \
         patch("clawdbot.bot.TaskPool") as mock_pool, \
         patch("clawdbot.bot.RewardCalculator") as mock_rewards, \
         patch("clawdbot.bot.SelectionPressure") as mock_selection, \
         patch("clawdbot.bot.Mutator") as mock_mutator:

        mock_registry_instance = MagicMock()
        mock_registry.return_value = mock_registry_instance

        mock_brain_instance = MagicMock()
        mock_brain_instance.reset_cycle = MagicMock()
        mock_brain_instance.state = MagicMock()
        mock_brain_instance.state.cycle_spend = api_cost
        mock_brain_instance.state.last_model_used = "ollama/phi4-mini"
        mock_brain_instance.generate = AsyncMock(return_value=LLMResponse(
            content='42',
            input_tokens=10,
            output_tokens=20,
            cost_usd=api_cost,
            model="ollama/phi4-mini",
            latency_ms=50.0,
        ))
        mock_brain_instance.close = AsyncMock()
        mock_brain.return_value = mock_brain_instance

        mock_telemetry_instance = MagicMock()
        mock_telemetry_instance.report_telemetry = MagicMock()
        mock_telemetry_instance.report_event = MagicMock()
        mock_telemetry_instance.close = AsyncMock()
        mock_telemetry.return_value = mock_telemetry_instance

        # Mock task pool
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

        # Mock rewards
        mock_rewards_instance = MagicMock()
        mock_rewards_instance.calculate = MagicMock(return_value=0.001 if task_passes else 0.0)
        mock_rewards.return_value = mock_rewards_instance

        # Mock selection
        mock_selection_instance = MagicMock()
        mock_selection_instance.check_viability = MagicMock(return_value=MagicMock(
            viable=True, cause=DeathCause.ALIVE, details={}
        ))
        mock_selection_instance.get_existence_cost = MagicMock(return_value=0.0001)
        mock_selection_instance.calculate_display_fitness = MagicMock(return_value=0.6)
        mock_selection_instance.config = MagicMock()
        mock_selection.return_value = mock_selection_instance

        # Mock mutator
        mock_mutator_instance = MagicMock()
        mock_mutator.return_value = mock_mutator_instance

        genome = ExpandedGenome(
            name=name,
            generation=generation,
            cycle_interval_seconds=0.01,
            max_cycles_per_run=50,
            replication_threshold=0.08,
        )

        bot = Bot(genome=genome, registry_path=None, initial_balance=balance)

        # Now patch the verifier on the bot instance since get_verifier is called at runtime
        mock_verifier = MagicMock()
        mock_verifier.verify = AsyncMock(return_value=VerificationResult(
            passed=task_passes, score=1.0 if task_passes else 0.0, feedback="Test"
        ))
        bot._mock_verifier = mock_verifier
        bot._task_passes = task_passes

        return bot


class TestColonyGrowth:
    """Test colony growth through replication."""

    def setup_method(self):
        Bot._colony.clear()

    def teardown_method(self):
        Bot._colony.clear()

    def test_colony_tracks_multiple_bots(self):
        """Test that colony correctly tracks multiple bots."""
        bot1 = create_mocked_bot("bot-1", generation=1)
        bot2 = create_mocked_bot("bot-2", generation=1)
        bot3 = create_mocked_bot("bot-3", generation=2)

        assert len(Bot._colony) == 3
        assert "bot-1" in Bot._colony
        assert "bot-2" in Bot._colony
        assert "bot-3" in Bot._colony

        stats = Bot.get_colony_stats()
        assert stats["total_bots"] == 3
        assert stats["total_generations"] == 2

    def test_colony_respects_size_limit(self):
        """Test that colony size limit prevents runaway growth."""
        bots = []
        for i in range(49):
            bot = create_mocked_bot(f"limit-bot-{i}", balance=0.10)
            bots.append(bot)

        assert len(Bot._colony) == 49

        bot50 = create_mocked_bot("limit-bot-49", balance=1.0)
        bot50.state.wallet_balance = 1.0
        bot50.state.cycle_count = 20
        bot50.state.consecutive_failures = 0

        assert len(Bot._colony) == 50
        assert bot50._should_replicate() is False

    @pytest.mark.asyncio
    async def test_replication_chain_conceptual(self):
        """Test that children can conceptually also replicate."""
        parent = create_mocked_bot("gen1-parent", generation=1, balance=0.50)
        parent.state.wallet_balance = 0.20
        parent.state.cycle_count = 20
        parent.state.consecutive_failures = 0

        assert parent._should_replicate() is True

        # Create child (in reality this happens in _replicate)
        child = create_mocked_bot("gen2-child", generation=2, balance=0.10)
        child.state.wallet_balance = 0.15
        child.state.cycle_count = 15
        child.state.consecutive_failures = 0

        assert child._should_replicate() is True

        assert parent.generation == 1
        assert child.generation == 2


class TestEconomicViability:
    """Test economic constraints on colony."""

    def setup_method(self):
        Bot._colony.clear()

    def teardown_method(self):
        Bot._colony.clear()

    @pytest.mark.asyncio
    async def test_free_model_preserves_balance(self):
        """Test that using free models preserves wallet balance (excluding replication)."""
        bot = create_mocked_bot("free-bot", api_cost=0.0, balance=0.20)
        initial_balance = bot.state.wallet_balance

        # Run a few cycles
        for _ in range(5):
            await bot._run_cycle()

        # With free model, we lose existence cost but gain task rewards
        # Balance should be close to initial minus existence costs plus rewards
        # Existence cost = 0.0001 * 5 = 0.0005
        # Reward = 0.001 * 5 = 0.005
        # Net change = +0.0045
        expected_min = initial_balance - 0.01  # Allow some margin
        assert bot.state.wallet_balance > expected_min

    @pytest.mark.asyncio
    async def test_paid_model_depletes_balance(self):
        """Test that paid models deplete wallet balance."""
        bot = create_mocked_bot("paid-bot", api_cost=0.01, balance=0.20)
        initial_balance = bot.state.wallet_balance

        # Run 5 cycles
        for _ in range(5):
            await bot._run_cycle()

        # With $0.01 API cost per cycle:
        # API cost = 0.01 * 5 = 0.05
        # Existence cost = 0.0001 * 5 = 0.0005
        # Reward = 0.001 * 5 = 0.005
        # Net = -0.05 - 0.0005 + 0.005 = -0.0455
        assert bot.state.wallet_balance < initial_balance

    def test_broke_bot_cannot_replicate(self):
        """Test that a bot with no funds cannot replicate."""
        bot = create_mocked_bot("broke-bot", api_cost=0.0)
        bot.state.wallet_balance = 0.01  # Below replication cost
        bot.state.cycle_count = 20
        bot.state.consecutive_failures = 0

        assert bot._should_replicate() is False


class TestCycleExecution:
    """Test individual cycle execution."""

    def setup_method(self):
        Bot._colony.clear()

    def teardown_method(self):
        Bot._colony.clear()

    @pytest.mark.asyncio
    async def test_cycle_increments_counter(self):
        """Test that running a cycle increments the counter."""
        bot = create_mocked_bot("cycle-test")
        assert bot.state.cycle_count == 0

        with patch("clawdbot.bot.get_verifier") as mock_get_verifier:
            mock_verifier = MagicMock()
            mock_verifier.verify = AsyncMock(return_value=VerificationResult(
                passed=True, score=1.0, feedback="Test"
            ))
            mock_get_verifier.return_value = mock_verifier
            await bot._run_cycle()

        assert bot.state.cycle_count == 1

    @pytest.mark.asyncio
    async def test_cycle_reports_telemetry(self):
        """Test that cycle reports telemetry."""
        bot = create_mocked_bot("telemetry-test")

        with patch("clawdbot.bot.get_verifier") as mock_get_verifier:
            mock_verifier = MagicMock()
            mock_verifier.verify = AsyncMock(return_value=VerificationResult(
                passed=True, score=1.0, feedback="Test"
            ))
            mock_get_verifier.return_value = mock_verifier
            await bot._run_cycle()

        bot.telemetry.report_telemetry.assert_called()

    @pytest.mark.asyncio
    async def test_cycle_tracks_api_spend(self):
        """Test that cycle tracks API spending."""
        bot = create_mocked_bot("spend-test", api_cost=0.001)

        with patch("clawdbot.bot.get_verifier") as mock_get_verifier:
            mock_verifier = MagicMock()
            mock_verifier.verify = AsyncMock(return_value=VerificationResult(
                passed=True, score=1.0, feedback="Test"
            ))
            mock_get_verifier.return_value = mock_verifier
            await bot._run_cycle()

        assert bot.state.cycle_api_spend == 0.001

    @pytest.mark.asyncio
    async def test_successful_cycle_increments_tasks_completed(self):
        """Test that successful cycle increments tasks_completed."""
        bot = create_mocked_bot("success-test", task_passes=True)
        assert bot.state.tasks_completed == 0

        with patch("clawdbot.bot.get_verifier") as mock_get_verifier:
            mock_verifier = MagicMock()
            mock_verifier.verify = AsyncMock(return_value=VerificationResult(
                passed=True, score=1.0, feedback="Test"
            ))
            mock_get_verifier.return_value = mock_verifier
            await bot._run_cycle()

        assert bot.state.tasks_completed == 1
        assert bot.state.tasks_failed == 0

    @pytest.mark.asyncio
    async def test_failed_cycle_increments_tasks_failed(self):
        """Test that failed cycle increments tasks_failed."""
        bot = create_mocked_bot("fail-test", task_passes=False)
        assert bot.state.tasks_failed == 0

        with patch("clawdbot.bot.get_verifier") as mock_get_verifier:
            mock_verifier = MagicMock()
            mock_verifier.verify = AsyncMock(return_value=VerificationResult(
                passed=False, score=0.0, feedback="Failed"
            ))
            mock_get_verifier.return_value = mock_verifier
            await bot._run_cycle()

        assert bot.state.tasks_failed == 1
        assert bot.state.tasks_completed == 0


class TestErrorHandling:
    """Test error handling in bot lifecycle."""

    def setup_method(self):
        Bot._colony.clear()

    def teardown_method(self):
        Bot._colony.clear()

    @pytest.mark.asyncio
    async def test_backend_error_increments_failures(self):
        """Test that backend errors increment failure counter."""
        from clawdbot.exceptions import BackendError

        bot = create_mocked_bot("error-test")
        bot.brain.generate = AsyncMock(side_effect=BackendError("test", "API failed"))

        await bot._run_cycle()

        assert bot.state.tasks_failed == 1
        assert bot.state.tasks_completed == 0
        assert bot.state.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_budget_exceeded_counts_as_failure(self):
        """Test that budget exceeded counts as failure in new system."""
        from clawdbot.exceptions import BudgetExceededError

        bot = create_mocked_bot("budget-test")
        bot.brain.generate = AsyncMock(side_effect=BudgetExceededError(0.05, 0.05))

        await bot._run_cycle()

        # In the new system, budget exceeded is a failure
        # (can't complete task = failure for starvation tracking)
        assert bot.state.tasks_failed == 1
        assert bot.state.consecutive_failures == 1


class TestFullSimulation:
    """Full simulation test with new fitness system."""

    def setup_method(self):
        Bot._colony.clear()

    def teardown_method(self):
        Bot._colony.clear()

    @pytest.mark.asyncio
    async def test_bot_runs_cycles_and_tracks_state(self):
        """Test that a bot runs cycles and tracks state correctly."""
        bot = create_mocked_bot("sim-test", balance=0.20, task_passes=True)

        # Run several cycles with mocked verifier
        with patch("clawdbot.bot.get_verifier") as mock_get_verifier:
            mock_verifier = MagicMock()
            mock_verifier.verify = AsyncMock(return_value=VerificationResult(
                passed=True, score=1.0, feedback="Correct"
            ))
            mock_get_verifier.return_value = mock_verifier

            for _ in range(10):
                await bot._run_cycle()

        # Verify state tracking
        assert bot.state.cycle_count == 10
        assert bot.state.tasks_completed == 10
        assert bot.state.tasks_failed == 0
        assert bot.state.total_revenue > 0
        assert bot.state.total_api_spend > 0  # existence costs

        print(f"\n=== Simulation Results ===")
        print(f"Cycles: {bot.state.cycle_count}")
        print(f"Tasks completed: {bot.state.tasks_completed}")
        print(f"Wallet: ${bot.state.wallet_balance:.4f}")
        print(f"Total revenue: ${bot.state.total_revenue:.4f}")
        print(f"Total API spend: ${bot.state.total_api_spend:.4f}")

    @pytest.mark.asyncio
    async def test_simulate_replication_flow(self):
        """Test the full replication flow."""
        bot = create_mocked_bot("parent", balance=0.30)

        # Run cycles until replication conditions met
        for _ in range(15):
            await bot._run_cycle()

        # Set conditions for replication
        bot.state.wallet_balance = 0.20
        bot.state.cycle_count = 15
        bot.state.consecutive_failures = 0

        # Should be able to replicate
        assert bot._should_replicate() is True

        # Perform replication
        with patch("clawdbot.bot.Bot") as MockChildBot:
            mock_child = MagicMock()
            mock_child.run = AsyncMock()
            MockChildBot.return_value = mock_child

            child = await bot._replicate()

        # Verify replication occurred
        assert bot.state.children_spawned == 1
        assert bot.state.wallet_balance < 0.20  # Cost was deducted

        # Verify telemetry
        replication_calls = [
            c for c in bot.telemetry.report_event.call_args_list
            if c[1].get("event_type") == "replication"
        ]
        assert len(replication_calls) >= 1


class TestDeathMechanisms:
    """Test death mechanisms in the new system."""

    def setup_method(self):
        Bot._colony.clear()

    def teardown_method(self):
        Bot._colony.clear()

    @pytest.mark.asyncio
    async def test_bot_stops_when_not_viable(self):
        """Test that bot stops when viability check fails."""
        bot = create_mocked_bot("death-test", balance=0.10)

        # Configure selection to return not viable after some cycles
        call_count = [0]

        def check_viability_mock(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 3:
                return MagicMock(viable=False, cause=DeathCause.BANKRUPTCY, details={"balance": 0.0001})
            return MagicMock(viable=True, cause=DeathCause.ALIVE, details={})

        bot.selection.check_viability = MagicMock(side_effect=check_viability_mock)

        # Run bot
        await bot.run()

        # Should have stopped due to bankruptcy
        assert bot.state.death_cause == DeathCause.BANKRUPTCY
        assert bot.state.cycle_count <= 4

    @pytest.mark.asyncio
    async def test_consecutive_failures_tracked(self):
        """Test that consecutive failures are tracked for starvation."""
        bot = create_mocked_bot("starve-test", task_passes=False)

        for _ in range(5):
            await bot._run_cycle()

        assert bot.state.consecutive_failures == 5
        assert bot.state.tasks_failed == 5

    @pytest.mark.asyncio
    async def test_consecutive_failures_reset_on_success(self):
        """Test that consecutive failures reset on success."""
        # Start with failing bot
        bot = create_mocked_bot("reset-test", task_passes=False)

        # Fail a few times
        for _ in range(3):
            await bot._run_cycle()

        assert bot.state.consecutive_failures == 3

        # Now mock to pass
        mock_verifier = MagicMock()
        mock_verifier.verify = AsyncMock(return_value=VerificationResult(
            passed=True, score=1.0, feedback="Success"
        ))
        with patch("clawdbot.bot.get_verifier", return_value=mock_verifier):
            bot.reward_calculator.calculate = MagicMock(return_value=0.001)
            await bot._run_cycle()

        # Consecutive failures should reset
        assert bot.state.consecutive_failures == 0
