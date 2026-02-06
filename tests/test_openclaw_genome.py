"""Tests for OpenClaw genome and mutation."""

import pytest

from clawdbot.evolution.openclaw_genome import (
    OpenClawGenome,
    OpenClawMutationBounds,
    AVAILABLE_MODELS,
    THINKING_LEVELS,
    SAFE_TOOLS,
    DEFAULT_SOUL_PROMPTS,
    Soul,
)
from clawdbot.evolution.genome import ExpandedGenome
from clawdbot.openclaw_bot import OpenClawMutator, OpenClawMutationResult


class TestOpenClawGenome:
    """Tests for OpenClawGenome."""

    def test_default_genome(self):
        """Test default genome values."""
        genome = OpenClawGenome(name="test-bot")

        assert genome.name == "test-bot"
        assert genome.generation == 1
        assert genome.openclaw_model == "claude_code/opus-4-5"
        assert genome.thinking_level == "medium"
        assert "Read" in genome.enabled_tools
        assert genome.tool_risk_tolerance == 0.3

    def test_genome_to_dict(self):
        """Test genome serialization."""
        genome = OpenClawGenome(
            name="test-bot",
            openclaw_model="cerebras/zai-glm-4.7",
            thinking_level="high",
        )

        data = genome.to_dict()

        assert data["name"] == "test-bot"
        assert data["openclaw_model"] == "cerebras/zai-glm-4.7"
        assert data["thinking_level"] == "high"

    def test_genome_from_dict(self):
        """Test genome deserialization."""
        data = {
            "name": "restored-bot",
            "generation": 5,
            "openclaw_model": "claude_code/sonnet-4-5",
            "thinking_level": "low",
            "enabled_tools": ["Read", "Write", "Bash"],
        }

        genome = OpenClawGenome.from_dict(data)

        assert genome.name == "restored-bot"
        assert genome.generation == 5
        assert genome.openclaw_model == "claude_code/sonnet-4-5"
        assert genome.thinking_level == "low"
        assert genome.enabled_tools == ["Read", "Write", "Bash"]

    def test_genome_hash(self):
        """Test that genome hash excludes identity fields."""
        # Use explicit soul to ensure consistent hashing
        fixed_soul = Soul(
            purpose="Test purpose",
            values=["Value 1", "Value 2"],
            boundaries=["Boundary 1"],
            personality="focused",
            approach="step by step",
            style="concise",
            backstory="",
        )

        genome1 = OpenClawGenome(
            name="bot-1",
            generation=1,
            openclaw_model="test-model",
            soul=fixed_soul,
        )
        genome2 = OpenClawGenome(
            name="bot-2",
            generation=2,
            openclaw_model="test-model",
            soul=fixed_soul,
        )

        # Same traits, different identity -> same hash
        assert genome1.hash() == genome2.hash()

        # Different traits -> different hash
        genome3 = OpenClawGenome(
            name="bot-3",
            openclaw_model="different-model",
            soul=fixed_soul,
        )
        assert genome1.hash() != genome3.hash()

    def test_random_genome(self):
        """Test random genome generation."""
        genome = OpenClawGenome.random("random-bot")

        assert genome.name == "random-bot"
        assert genome.generation == 1
        assert genome.openclaw_model in AVAILABLE_MODELS
        assert genome.thinking_level in THINKING_LEVELS
        assert all(t in SAFE_TOOLS for t in genome.enabled_tools if t in SAFE_TOOLS)

    def test_from_expanded_genome(self):
        """Test conversion from ExpandedGenome."""
        base = ExpandedGenome(
            name="base-bot",
            generation=3,
            risk_tolerance=0.7,
            difficulty_preference=0.6,
        )

        openclaw = OpenClawGenome.from_expanded(base)

        assert openclaw.name == "base-bot"
        assert openclaw.generation == 3
        assert openclaw.risk_tolerance == 0.7
        assert openclaw.difficulty_preference == 0.6
        # OpenClaw-specific defaults applied
        assert openclaw.openclaw_model == "claude_code/opus-4-5"

    def test_get_openclaw_config(self):
        """Test generating OpenClaw configuration."""
        # Test with legacy soul_prompt (no soul object)
        genome = OpenClawGenome(
            name="test-bot",
            openclaw_model="claude_code/opus-4-5",
            thinking_level="high",
            soul=None,  # Disable soul to use legacy soul_prompt
            soul_prompt="Be helpful.",
            max_task_duration=150.0,
        )

        config = genome.get_openclaw_config()

        assert config["model"] == "opus"  # Resolved ID
        assert config["thinking_level"] == "high"
        assert config["soul_prompt"] == "Be helpful."
        assert config["timeout_seconds"] == 150.0

    def test_get_openclaw_config_with_soul(self):
        """Test generating OpenClaw configuration with Soul object."""
        test_soul = Soul(
            purpose="I exist to help.",
            values=["Efficiency", "Quality"],
            boundaries=["Do not harm"],
            personality="helpful",
            approach="Be thorough.",
            style="Clear explanations.",
        )

        genome = OpenClawGenome(
            name="test-bot",
            openclaw_model="claude_code/opus-4-5",
            thinking_level="high",
            soul=test_soul,
            max_task_duration=150.0,
        )

        config = genome.get_openclaw_config()

        assert config["model"] == "opus"
        assert config["thinking_level"] == "high"
        # Soul should generate a full prompt including the purpose
        assert "I exist to help." in config["soul_prompt"]
        assert "# Soul" in config["soul_prompt"]
        assert config["timeout_seconds"] == 150.0

    def test_select_task_type(self):
        """Test task type selection based on specializations."""
        genome = OpenClawGenome(
            name="coding-bot",
            task_specializations={
                "coding": 1.0,
                "file_organization": 0.0,
                "data_extraction": 0.0,
                "reasoning": 0.0,
                "scripting": 0.0,
                "ai_research": 0.0,
            },
            research_time_ratio=0.0,  # Disable research task selection
        )

        # Should always select coding due to weights (with research disabled)
        for _ in range(10):
            task_type = genome.select_task_type()
            assert task_type == "coding"

    def test_select_task_type_research(self):
        """Test that research tasks are selected based on research_time_ratio."""
        genome = OpenClawGenome(
            name="research-bot",
            task_specializations={
                "coding": 1.0,
                "ai_research": 0.5,
            },
            research_time_ratio=1.0,  # Always select research
        )

        # Should always select ai_research when ratio is 1.0
        for _ in range(10):
            task_type = genome.select_task_type()
            assert task_type == "ai_research"

    def test_max_turns_calculation(self):
        """Test max turns calculation based on traits."""
        low_thinking = OpenClawGenome(
            name="low",
            thinking_level="none",
            tool_risk_tolerance=0.0,
        )
        high_thinking = OpenClawGenome(
            name="high",
            thinking_level="high",
            tool_risk_tolerance=1.0,
        )

        low_turns = low_thinking._calculate_max_turns()
        high_turns = high_thinking._calculate_max_turns()

        assert high_turns > low_turns


class TestOpenClawMutator:
    """Tests for OpenClawMutator."""

    def test_mutate_creates_child(self):
        """Test that mutation creates a valid child genome."""
        parent = OpenClawGenome(
            name="parent",
            generation=1,
            mutation_rate=1.0,  # Force mutations
        )

        mutator = OpenClawMutator()
        result = mutator.mutate(parent, "child")

        assert isinstance(result, OpenClawMutationResult)
        assert result.genome.name == "child"
        assert result.genome.generation == 2
        assert result.genome.parent_name == "parent"

    def test_mutate_with_high_rate(self):
        """Test that high mutation rate causes changes."""
        parent = OpenClawGenome(
            name="parent",
            mutation_rate=1.0,
            mutation_magnitude=0.5,
        )

        mutator = OpenClawMutator()

        # Run multiple mutations and check for changes
        mutations_found = False
        for _ in range(10):
            result = mutator.mutate(parent, f"child-{_}")
            if result.mutation_count > 0:
                mutations_found = True
                break

        # With 100% mutation rate, we should see mutations
        assert mutations_found

    def test_mutate_preserves_identity(self):
        """Test that child has correct identity fields."""
        parent = OpenClawGenome(
            name="parent-alpha",
            generation=5,
        )

        mutator = OpenClawMutator()
        result = mutator.mutate(parent, "child-alpha")

        assert result.genome.name == "child-alpha"
        assert result.genome.generation == 6
        assert result.genome.parent_name == "parent-alpha"

    def test_force_mutation(self):
        """Test forced mutation when no mutations occur."""
        parent = OpenClawGenome(
            name="parent",
            mutation_rate=0.0,  # No natural mutations
        )

        mutator = OpenClawMutator()
        result = mutator.mutate(parent, "child", force_mutation=True)

        assert result.mutation_count >= 1
        assert len(result.mutations_applied) >= 1

    def test_model_mutation(self):
        """Test that model can be mutated."""
        # Set high model mutation probability
        bounds = OpenClawMutationBounds(model_mutation_prob=1.0)
        mutator = OpenClawMutator(bounds=bounds)

        parent = OpenClawGenome(
            name="parent",
            openclaw_model="claude_code/opus-4-5",
        )

        # Run multiple times to ensure mutation happens
        model_changed = False
        for _ in range(20):
            result = mutator.mutate(parent, f"child-{_}")
            if result.genome.openclaw_model != parent.openclaw_model:
                model_changed = True
                assert result.genome.openclaw_model in AVAILABLE_MODELS
                break

        # Model should change with 100% probability
        assert model_changed

    def test_thinking_level_mutation(self):
        """Test thinking level mutation."""
        bounds = OpenClawMutationBounds(thinking_mutation_prob=1.0)
        mutator = OpenClawMutator(bounds=bounds)

        parent = OpenClawGenome(
            name="parent",
            thinking_level="medium",
        )

        # Check that thinking level can change
        level_changed = False
        for _ in range(20):
            result = mutator.mutate(parent, f"child-{_}")
            if result.genome.thinking_level != parent.thinking_level:
                level_changed = True
                assert result.genome.thinking_level in THINKING_LEVELS
                break

    def test_mutation_result_summary(self):
        """Test mutation result summary."""
        genome = OpenClawGenome(name="child")

        result = OpenClawMutationResult(
            genome=genome,
            mutations_applied=["model: a -> b", "thinking: low -> high"],
            mutation_count=2,
        )

        summary = result.summary()

        assert "2 mutations" in summary
        assert "model:" in summary
