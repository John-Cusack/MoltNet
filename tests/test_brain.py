"""Tests for the Brain Router."""

import pytest

from clawdbot.brain import BrainConfig, BrainRouter, BrainState
from clawdbot.llm_registry import LLMRegistry
from clawdbot.exceptions import BudgetExceededError, ModelNotFoundError


class TestBrainConfig:
    """Tests for BrainConfig."""

    def test_defaults(self):
        """Test default configuration values."""
        config = BrainConfig()
        assert config.budget_per_cycle == 0.05
        assert config.default_task_type == "general"
        assert config.prefer_local is True
        assert config.fallback_to_free is True
        assert config.max_retries == 2
        assert config.routing_strategy == "best_value"

    def test_custom_values(self):
        """Test custom configuration."""
        config = BrainConfig(
            budget_per_cycle=0.10,
            routing_strategy="best",
            prefer_local=False,
        )
        assert config.budget_per_cycle == 0.10
        assert config.routing_strategy == "best"
        assert config.prefer_local is False


class TestBrainState:
    """Tests for BrainState."""

    def test_defaults(self):
        """Test default state values."""
        state = BrainState()
        assert state.cycle_spend == 0.0
        assert state.request_count == 0
        assert state.failed_models == set()
        assert state.last_model_used is None


class TestBrainRouter:
    """Tests for BrainRouter."""

    @pytest.fixture
    def registry(self, temp_registry, mock_api_key):
        """Create a loaded registry."""
        reg = LLMRegistry()
        reg.load(temp_registry)
        return reg

    @pytest.fixture
    def brain(self, registry):
        """Create a brain router with test registry."""
        config = BrainConfig(
            budget_per_cycle=0.05,
            prefer_local=True,
            fallback_to_free=True,
        )
        return BrainRouter(config=config, registry=registry)

    def test_init_with_dict_config(self, registry):
        """Test initialization with dict config."""
        brain = BrainRouter(
            config={"budget_per_cycle": 0.10, "prefer_local": False},
            registry=registry,
        )
        assert brain.config.budget_per_cycle == 0.10
        assert brain.config.prefer_local is False

    def test_init_with_brain_config(self, registry):
        """Test initialization with BrainConfig."""
        config = BrainConfig(budget_per_cycle=0.20)
        brain = BrainRouter(config=config, registry=registry)
        assert brain.config.budget_per_cycle == 0.20

    def test_remaining_budget(self, brain):
        """Test remaining budget calculation."""
        assert brain.remaining_budget == 0.05
        brain.state.cycle_spend = 0.02
        assert brain.remaining_budget == pytest.approx(0.03)

    def test_remaining_budget_clamp(self, brain):
        """Test remaining budget doesn't go negative."""
        brain.state.cycle_spend = 0.10
        assert brain.remaining_budget == 0.0

    def test_reset_cycle(self, brain):
        """Test cycle reset."""
        brain.state.cycle_spend = 0.05
        brain.state.request_count = 10
        brain.state.failed_models.add("test/model")
        brain.state.last_model_used = "test/model"

        brain.reset_cycle()

        assert brain.state.cycle_spend == 0.0
        assert brain.state.request_count == 0
        assert brain.state.failed_models == set()
        assert brain.state.last_model_used is None

    def test_select_model_prefers_local(self, brain):
        """Test that local models are preferred when configured."""
        spec = brain.select_model(task_type="code")
        # Should prefer the free local model
        assert spec.model_key == "test_local/model-a"

    def test_select_model_with_preference(self, brain):
        """Test preferred model selection."""
        spec = brain.select_model(
            task_type="code",
            prefer_model="test_api/model-b",
        )
        assert spec.model_key == "test_api/model-b"

    def test_select_model_excludes_failed(self, brain):
        """Test that failed models are excluded."""
        brain.state.failed_models.add("test_local/model-a")
        spec = brain.select_model(task_type="code")
        # Should pick a non-failed model
        assert spec.model_key != "test_local/model-a"

    def test_select_model_budget_constraint(self, brain):
        """Test model selection with cost constraint."""
        spec = brain.select_model(task_type="code", max_cost=0.001)
        # Should pick a cheap model
        assert (spec.cost_per_1k_input + spec.cost_per_1k_output) <= 0.001

    def test_get_stats(self, brain):
        """Test getting brain statistics."""
        brain.state.cycle_spend = 0.01
        brain.state.request_count = 5
        brain.state.last_model_used = "test/model"

        stats = brain.get_stats()

        assert stats["cycle_spend"] == 0.01
        assert stats["remaining_budget"] == pytest.approx(0.04)
        assert stats["request_count"] == 5
        assert stats["last_model_used"] == "test/model"


class TestBrainRouterRouting:
    """Tests for routing strategies."""

    @pytest.fixture
    def registry(self, temp_registry, mock_api_key):
        """Create a loaded registry."""
        reg = LLMRegistry()
        reg.load(temp_registry)
        return reg

    def test_best_strategy(self, registry):
        """Test 'best' routing strategy."""
        brain = BrainRouter(
            config=BrainConfig(routing_strategy="best", prefer_local=False),
            registry=registry,
        )
        spec = brain.select_model(task_type="code")
        # Should pick highest quality tier
        assert spec.quality_tier >= 3

    def test_cheapest_strategy(self, registry):
        """Test 'cheapest' routing strategy."""
        brain = BrainRouter(
            config=BrainConfig(routing_strategy="cheapest", prefer_local=False),
            registry=registry,
        )
        spec = brain.select_model(task_type="code")
        # Should pick free model
        assert spec.is_free()

    def test_best_value_strategy(self, registry):
        """Test 'best_value' routing strategy."""
        brain = BrainRouter(
            config=BrainConfig(routing_strategy="best_value", prefer_local=False),
            registry=registry,
        )
        spec = brain.select_model(task_type="code")
        # Should pick a model with good value ratio
        assert spec is not None


class TestBrainRouterIntegration:
    """Integration tests for BrainRouter with real backends."""

    @pytest.mark.asyncio
    async def test_generate_with_ollama(self, temp_registry, mock_api_key):
        """Test generation with Ollama backend."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        # Override to use real Ollama endpoint
        for model in registry.all_models():
            if model.provider == "test_local":
                model.model_id = "phi4-mini"
                model.base_url = "http://localhost:11434"

        brain = BrainRouter(
            config=BrainConfig(prefer_local=True),
            registry=registry,
        )

        # Check if Ollama is available
        health = await brain.health_check("test_local/model-a")
        if not health.get("test_local/model-a"):
            await brain.close()
            pytest.skip("Ollama not available")

        try:
            response = await brain.generate(
                prompt="What is 2+2? Reply with just the number.",
                max_tokens=10,
                temperature=0.0,
            )
            assert response.content
            assert "4" in response.content
            assert brain.state.request_count == 1
        finally:
            await brain.close()

    @pytest.mark.asyncio
    async def test_health_check_all(self, temp_registry, mock_api_key):
        """Test health check for all backends."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        brain = BrainRouter(registry=registry)

        try:
            results = await brain.health_check()
            # Results should be a dict with model keys
            assert isinstance(results, dict)
            # All models should have a boolean result
            for key, value in results.items():
                assert isinstance(value, bool)
        finally:
            await brain.close()
