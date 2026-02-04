"""Tests for the LLM Registry."""

import os
from pathlib import Path

import pytest

from clawdbot.exceptions import ModelNotFoundError, RegistryError
from clawdbot.llm_registry import LLMRegistry, ModelSpec


class TestModelSpec:
    """Tests for the ModelSpec dataclass."""

    def test_cost_for_tokens(self):
        """Test cost calculation."""
        spec = ModelSpec(
            model_key="test/model",
            display_name="Test",
            provider="test",
            model_id="model",
            base_url="http://localhost",
            auth_env=None,
            api_format="ollama",
            context_window=8192,
            max_output_tokens=2048,
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
            quality_tier=3,
        )
        # 1000 input tokens at $0.001/1k = $0.001
        # 500 output tokens at $0.002/1k = $0.001
        # Total = $0.002
        cost = spec.cost_for_tokens(1000, 500)
        assert cost == pytest.approx(0.002)

    def test_is_free(self):
        """Test free model detection."""
        free_spec = ModelSpec(
            model_key="test/free",
            display_name="Free",
            provider="test",
            model_id="free",
            base_url="http://localhost",
            auth_env=None,
            api_format="ollama",
            context_window=8192,
            max_output_tokens=2048,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            quality_tier=2,
        )
        assert free_spec.is_free() is True

        paid_spec = ModelSpec(
            model_key="test/paid",
            display_name="Paid",
            provider="test",
            model_id="paid",
            base_url="http://localhost",
            auth_env="API_KEY",
            api_format="openai_compatible",
            context_window=8192,
            max_output_tokens=2048,
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
            quality_tier=3,
        )
        assert paid_spec.is_free() is False

    def test_has_strength_weakness(self):
        """Test strength/weakness checking."""
        spec = ModelSpec(
            model_key="test/model",
            display_name="Test",
            provider="test",
            model_id="model",
            base_url="http://localhost",
            auth_env=None,
            api_format="ollama",
            context_window=8192,
            max_output_tokens=2048,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            quality_tier=2,
            strengths=["code", "math"],
            weaknesses=["creative_writing"],
        )
        assert spec.has_strength("code") is True
        assert spec.has_strength("reasoning") is False
        assert spec.has_weakness("creative_writing") is True
        assert spec.has_weakness("math") is False


class TestLLMRegistry:
    """Tests for the LLMRegistry class."""

    def test_load_missing_file(self):
        """Test loading a non-existent file."""
        registry = LLMRegistry()
        with pytest.raises(RegistryError, match="Config file not found"):
            registry.load("/nonexistent/path.yaml")

    def test_load_temp_registry(self, temp_registry):
        """Test loading a valid registry."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        assert len(registry) == 3
        assert "test_local/model-a" in registry
        assert "test_api/model-b" in registry
        assert "test_api/model-c" in registry

    def test_get_model(self, temp_registry):
        """Test getting a model by key."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        model = registry.get("test_local/model-a")
        assert model is not None
        assert model.display_name == "Test Model A"
        assert model.provider == "test_local"
        assert model.is_free() is True

        # Non-existent model
        assert registry.get("nonexistent/model") is None

    def test_get_or_raise(self, temp_registry):
        """Test get_or_raise raises on missing model."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        model = registry.get_or_raise("test_local/model-a")
        assert model.model_key == "test_local/model-a"

        with pytest.raises(ModelNotFoundError) as exc_info:
            registry.get_or_raise("nonexistent/model")
        assert exc_info.value.model_key == "nonexistent/model"

    def test_availability_with_key(self, temp_registry, mock_api_key):
        """Test model availability when API key is set."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        # Local model (no auth_env) should be available
        local_model = registry.get("test_local/model-a")
        assert local_model.available is True

        # API model should be available since we set the key
        api_model = registry.get("test_api/model-b")
        assert api_model.available is True

    def test_availability_without_key(self, temp_registry, clear_api_keys):
        """Test model availability when API key is not set."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        # Local model should still be available
        local_model = registry.get("test_local/model-a")
        assert local_model.available is True

        # API model should not be available
        api_model = registry.get("test_api/model-b")
        assert api_model.available is False

    def test_available_models(self, temp_registry, mock_api_key):
        """Test getting available models."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        available = registry.available_models()
        # With API key set, all 3 models should be available
        assert len(available) == 3

    def test_free_models(self, temp_registry):
        """Test getting free models."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        free = registry.free_models()
        assert len(free) == 1
        assert free[0].model_key == "test_local/model-a"

    def test_models_by_provider(self, temp_registry):
        """Test filtering by provider."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        local_models = registry.models_by_provider("test_local")
        assert len(local_models) == 1
        assert local_models[0].model_key == "test_local/model-a"

        api_models = registry.models_by_provider("test_api")
        assert len(api_models) == 2

    def test_cheapest_for(self, temp_registry, mock_api_key):
        """Test finding cheapest model for a task."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        cheapest = registry.cheapest_for("code")
        # Should be the free local model
        assert cheapest.model_key == "test_local/model-a"

    def test_best_for(self, temp_registry, mock_api_key):
        """Test finding best model for a task."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        best = registry.best_for("code")
        # Should be the premium model (tier 4)
        assert best.model_key == "test_api/model-c"

    def test_best_value_for(self, temp_registry, mock_api_key):
        """Test finding best value model for a task."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        # Free model should have high value score
        best_value = registry.best_value_for("code")
        # With our formula, free model gets quality * 100 = 200
        # model-b gets 3 / 0.003 = 1000
        # model-c gets 4 / 0.04 = 100
        # So model-b should win
        assert best_value.model_key == "test_api/model-b"

    def test_get_routing(self, temp_registry):
        """Test task routing."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        best = registry.get_routing("code", "best")
        assert best == ["test_api/model-c", "test_api/model-b"]

        free = registry.get_routing("code", "free")
        assert free == ["test_local/model-a"]

        # Non-existent task type
        unknown = registry.get_routing("unknown_task", "best")
        assert unknown == []

    def test_update_benchmark(self, temp_registry):
        """Test updating benchmark scores."""
        registry = LLMRegistry()
        registry.load(temp_registry)

        registry.update_benchmark("test_local/model-a", "code_quality", 0.85)
        model = registry.get("test_local/model-a")
        assert model.benchmark_scores["code_quality"] == 0.85

    def test_refresh_availability(self, temp_registry, monkeypatch):
        """Test refreshing availability."""
        registry = LLMRegistry()

        # Load without API key
        monkeypatch.delenv("TEST_API_KEY", raising=False)
        registry.load(temp_registry)

        api_model = registry.get("test_api/model-b")
        assert api_model.available is False

        # Set API key and refresh
        monkeypatch.setenv("TEST_API_KEY", "new-key")
        registry.refresh_availability()

        assert api_model.available is True

    def test_not_loaded_error(self):
        """Test error when registry not loaded."""
        registry = LLMRegistry()

        with pytest.raises(RegistryError, match="not loaded"):
            registry.get("any/model")

        with pytest.raises(RegistryError, match="not loaded"):
            registry.all_models()

    def test_load_real_registry(self, registry_path):
        """Test loading the real registry file."""
        if not registry_path.exists():
            pytest.skip("Real registry file not found")

        registry = LLMRegistry()
        registry.load(registry_path)

        # Should have multiple models
        assert len(registry) > 0

        # Check some expected models exist
        assert "ollama/phi4-mini" in registry
        assert "anthropic/claude-sonnet-4-5" in registry

        # Check free models exist (ollama, claude_code, cerebras are all "free" per-token)
        free = registry.free_models()
        assert len(free) > 0
        free_providers = {"ollama", "claude_code", "cerebras"}
        for model in free:
            assert model.provider in free_providers
