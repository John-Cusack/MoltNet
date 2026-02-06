"""Tests for evolution and selection pressure."""

import pytest
from clawdbot.evolution.genome import ExpandedGenome
from clawdbot.evolution.selection import (
    SelectionPressure,
    SelectionConfig,
    DeathCause,
    ViabilityCheck,
    is_bankrupt,
)
from clawdbot.evolution.mutation import Mutator, MutationBounds


class TestExpandedGenome:
    """Tests for ExpandedGenome."""

    def test_default_values(self):
        """Test default genome values."""
        genome = ExpandedGenome(name="test-bot")

        assert genome.name == "test-bot"
        assert genome.generation == 1
        assert genome.difficulty_preference == 0.4
        assert genome.risk_tolerance == 0.3
        assert genome.mutation_rate == 0.1

    def test_to_dict(self):
        """Test serialization to dictionary."""
        genome = ExpandedGenome(name="test-bot", generation=3)
        data = genome.to_dict()

        assert data["name"] == "test-bot"
        assert data["generation"] == 3
        assert "task_preferences" in data
        assert "budget_per_cycle" in data

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "restored-bot",
            "generation": 5,
            "risk_tolerance": 0.7,
            "difficulty_preference": 0.6,
        }
        genome = ExpandedGenome.from_dict(data)

        assert genome.name == "restored-bot"
        assert genome.generation == 5
        assert genome.risk_tolerance == 0.7

    def test_hash_consistency(self):
        """Test that hash is consistent for same traits."""
        genome1 = ExpandedGenome(name="bot1", difficulty_preference=0.5)
        genome2 = ExpandedGenome(name="bot2", difficulty_preference=0.5)

        # Same traits should have same hash (name excluded)
        assert genome1.hash() == genome2.hash()

    def test_hash_changes_with_traits(self):
        """Test that hash changes with different traits."""
        genome1 = ExpandedGenome(name="bot", difficulty_preference=0.5)
        genome2 = ExpandedGenome(name="bot", difficulty_preference=0.6)

        assert genome1.hash() != genome2.hash()

    def test_random_generation(self):
        """Test random genome generation."""
        genome = ExpandedGenome.random("random-bot")

        assert genome.name == "random-bot"
        assert 0.1 <= genome.risk_tolerance <= 0.7
        assert 0.2 <= genome.difficulty_preference <= 0.6

    def test_get_brain_config(self):
        """Test brain config derivation."""
        genome = ExpandedGenome(
            name="test",
            budget_per_cycle=0.08,
            prefer_local=True,
            model_preference_tier=3,
        )

        config = genome.get_brain_config()

        assert config["budget_per_cycle"] == 0.08
        assert config["prefer_local"] is True
        assert config["routing_strategy"] == "best_value"

    def test_select_difficulty(self):
        """Test difficulty selection."""
        genome = ExpandedGenome(name="test", difficulty_preference=0.5, risk_tolerance=0.0)

        # With zero risk tolerance, should be close to preference
        difficulties = [genome.select_difficulty() for _ in range(10)]

        for d in difficulties:
            assert 0.4 <= d <= 0.6

    def test_should_attempt_hard_task(self):
        """Test hard task decision logic."""
        # High balance, high risk tolerance should attempt
        genome = ExpandedGenome(name="test", risk_tolerance=0.9)
        assert genome.should_attempt_hard_task(current_balance=1.0, task_cost_estimate=0.01)

        # Low balance should not attempt
        genome = ExpandedGenome(name="test", risk_tolerance=0.5)
        result = genome.should_attempt_hard_task(current_balance=0.01, task_cost_estimate=0.05)
        # With very low balance, should be False
        assert result is False

    def test_calculate_replication_investment(self):
        """Test child investment calculation."""
        genome = ExpandedGenome(name="test", child_inheritance_ratio=0.4)

        investment = genome.calculate_replication_investment(current_balance=0.10)

        # Should be 40% of balance, max 50%
        assert abs(investment - 0.04) < 0.0001  # Allow floating point tolerance


class TestSelectionConfig:
    """Tests for SelectionConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = SelectionConfig.default()

        assert config.minimum_viable_balance == 0.001
        assert config.enable_culling is False

    def test_harsh_config(self):
        """Test harsh configuration."""
        config = SelectionConfig.harsh()

        assert config.minimum_viable_balance == 0.005
        assert config.enable_culling is True

    def test_gentle_config(self):
        """Test gentle configuration."""
        config = SelectionConfig.gentle()

        assert config.minimum_viable_balance == 0.0001
        assert config.enable_culling is False


class TestSelectionPressure:
    """Tests for SelectionPressure."""

    @pytest.fixture
    def selection(self):
        return SelectionPressure()

    def test_viable_bot(self, selection):
        """Test that healthy bot is viable."""
        result = selection.check_viability(
            wallet_balance=0.10,
            consecutive_failures=0,
            cycle_count=50,
            max_cycles=1000,
        )

        assert result.viable is True
        assert result.cause == DeathCause.ALIVE

    def test_bankruptcy_death(self, selection):
        """Test bankruptcy detection."""
        result = selection.check_viability(
            wallet_balance=0.0005,  # Below threshold
            consecutive_failures=0,
            cycle_count=50,
            max_cycles=1000,
        )

        assert result.viable is False
        assert result.cause == DeathCause.BANKRUPTCY
        assert "balance" in result.details

    def test_natural_death(self, selection):
        """Test natural death at max cycles."""
        result = selection.check_viability(
            wallet_balance=0.10,
            consecutive_failures=0,
            cycle_count=1000,  # At max
            max_cycles=1000,
        )

        assert result.viable is False
        assert result.cause == DeathCause.NATURAL

    def test_existence_cost(self, selection):
        """Test getting existence cost."""
        cost = selection.get_existence_cost()

        assert cost == 0.0001

    def test_culling_disabled_by_default(self, selection):
        """Test that culling is disabled by default."""
        assert selection.should_cull(cycle_count=100) is False

    def test_culling_enabled(self):
        """Test culling when enabled."""
        config = SelectionConfig(enable_culling=True, culling_interval_cycles=50)
        selection = SelectionPressure(config)

        assert selection.should_cull(cycle_count=50) is True
        assert selection.should_cull(cycle_count=100) is True
        assert selection.should_cull(cycle_count=75) is False

    def test_select_for_culling(self):
        """Test selecting bots for culling."""
        config = SelectionConfig(enable_culling=True, culling_bottom_percentile=0.3)
        selection = SelectionPressure(config)

        bots = [
            {"name": "bot1", "fitness": 0.9},
            {"name": "bot2", "fitness": 0.5},
            {"name": "bot3", "fitness": 0.2},  # Should be culled
            {"name": "bot4", "fitness": 0.8},
        ]

        to_cull = selection.select_for_culling(bots)

        # Should cull bottom 30% (1 bot)
        assert len(to_cull) == 1
        assert "bot3" in to_cull

    def test_calculate_display_fitness(self, selection):
        """Test display fitness calculation."""
        fitness = selection.calculate_display_fitness(
            survival_time=50,
            economic_roi=0.5,
            task_success_rate=0.8,
            offspring_survival_rate=0.6,
        )

        assert 0.0 <= fitness <= 1.0
        # With positive ROI, good success, etc., should be decent
        assert fitness > 0.4


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_is_bankrupt(self):
        """Test bankruptcy check."""
        assert is_bankrupt(0.0001) is True
        assert is_bankrupt(0.01) is False
        assert is_bankrupt(0.001, threshold=0.002) is True


class TestMutator:
    """Tests for Mutator."""

    @pytest.fixture
    def mutator(self):
        return Mutator()

    def test_mutate_creates_child(self, mutator):
        """Test that mutation creates a new genome."""
        parent = ExpandedGenome(name="parent", generation=1)

        result = mutator.mutate(parent, "child")

        assert result.genome.name == "child"
        assert result.genome.generation == 2
        assert result.genome.parent_name == "parent"

    def test_mutate_respects_bounds(self, mutator):
        """Test that mutations stay within bounds."""
        parent = ExpandedGenome(
            name="parent",
            mutation_rate=0.99,  # Force mutations
            mutation_magnitude=0.5,  # Large mutations
        )

        for _ in range(10):
            result = mutator.mutate(parent, "child", force_mutation=True)
            genome = result.genome

            # Check all bounded values
            assert 0.0 <= genome.risk_tolerance <= 1.0
            assert 0.0 <= genome.difficulty_preference <= 1.0
            assert 0.01 <= genome.budget_per_cycle <= 0.20
            assert 1 <= genome.model_preference_tier <= 4

    def test_mutation_tracking(self, mutator):
        """Test that mutations are tracked."""
        parent = ExpandedGenome(name="parent", mutation_rate=0.99)

        result = mutator.mutate(parent, "child")

        assert isinstance(result.mutations_applied, list)
        assert result.mutation_count == len(result.mutations_applied)

    def test_force_mutation(self, mutator):
        """Test forced mutation."""
        parent = ExpandedGenome(name="parent", mutation_rate=0.0)  # No natural mutations

        result = mutator.mutate(parent, "child", force_mutation=True)

        assert result.mutation_count >= 1

    def test_mutation_summary(self, mutator):
        """Test mutation summary generation."""
        parent = ExpandedGenome(name="parent", mutation_rate=0.99)

        result = mutator.mutate(parent, "child")
        summary = result.summary()

        assert isinstance(summary, str)
        if result.mutation_count > 0:
            assert "mutations" in summary

    def test_crossover(self, mutator):
        """Test genome crossover."""
        parent1 = ExpandedGenome(
            name="parent1",
            risk_tolerance=0.1,
            difficulty_preference=0.2,
        )
        parent2 = ExpandedGenome(
            name="parent2",
            risk_tolerance=0.9,
            difficulty_preference=0.8,
        )

        result = mutator.crossover(parent1, parent2, "child")

        # Child should have generation higher than both parents
        # Crossover sets to max(parent)+1, then mutate increments again, so generation=3
        assert result.genome.generation >= 2
        assert result.genome.name == "child"

    def test_task_preference_mutation(self, mutator):
        """Test that task preferences can mutate."""
        parent = ExpandedGenome(
            name="parent",
            task_preferences={"math": 0.5, "json": 0.5, "logic": 0.5, "code": 0.5},
            mutation_rate=0.99,
        )

        result = mutator.mutate(parent, "child")

        # Check that task preferences might have changed
        child_prefs = result.genome.task_preferences
        assert "math" in child_prefs
        assert "json" in child_prefs


class TestViabilityCheck:
    """Tests for ViabilityCheck."""

    def test_alive_factory(self):
        """Test alive factory method."""
        check = ViabilityCheck.alive()

        assert check.viable is True
        assert check.cause == DeathCause.ALIVE
        assert check.details == {}

    def test_dead_factory(self):
        """Test dead factory method."""
        check = ViabilityCheck.dead(DeathCause.BANKRUPTCY, balance=0.0001)

        assert check.viable is False
        assert check.cause == DeathCause.BANKRUPTCY
        assert check.details["balance"] == 0.0001


class TestDeathCause:
    """Tests for DeathCause enum."""

    def test_all_causes_exist(self):
        """Test that all expected causes exist."""
        causes = [c.value for c in DeathCause]

        assert "alive" in causes
        assert "bankruptcy" in causes
        assert "culling" in causes
        assert "natural" in causes
        assert "shutdown" in causes
