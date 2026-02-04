"""LLM Registry - Centralized model catalog and query interface."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clawdbot.exceptions import ModelNotFoundError, RegistryError


@dataclass
class ModelSpec:
    """Specification for a single LLM model."""

    model_key: str  # e.g., "anthropic/claude-sonnet-4-5"
    display_name: str
    provider: str
    model_id: str  # API model ID
    base_url: str
    auth_env: str | None
    api_format: str  # "ollama", "anthropic", "openai_compatible"
    context_window: int
    max_output_tokens: int
    cost_per_1k_input: float
    cost_per_1k_output: float
    quality_tier: int  # 1-4 (4 = best)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    notes: str = ""
    benchmark_scores: dict[str, float] = field(default_factory=dict)
    available: bool = False  # Set dynamically based on API key presence

    def cost_for_tokens(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for given token counts."""
        input_cost = (input_tokens / 1000) * self.cost_per_1k_input
        output_cost = (output_tokens / 1000) * self.cost_per_1k_output
        return input_cost + output_cost

    def is_free(self) -> bool:
        """Check if this model is free to use."""
        return self.cost_per_1k_input == 0 and self.cost_per_1k_output == 0

    def has_strength(self, task_type: str) -> bool:
        """Check if model has a given strength."""
        return task_type in self.strengths

    def has_weakness(self, task_type: str) -> bool:
        """Check if model has a given weakness."""
        return task_type in self.weaknesses


class LLMRegistry:
    """Registry for all available LLM models."""

    def __init__(self):
        self._models: dict[str, ModelSpec] = {}
        self._providers: dict[str, dict[str, Any]] = {}
        self._task_routing: dict[str, dict[str, list[str]]] = {}
        self._loaded = False

    def load(self, config_path: str | Path) -> None:
        """Load the registry from a YAML config file."""
        config_path = Path(config_path)
        if not config_path.exists():
            raise RegistryError(f"Config file not found: {config_path}")

        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise RegistryError(f"Invalid YAML in config: {e}") from e

        if not data:
            raise RegistryError("Empty config file")

        self._providers = data.get("providers", {})
        self._task_routing = data.get("task_routing", {})

        # Parse models
        for model_key, model_data in data.get("models", {}).items():
            provider_name = model_data.get("provider")
            provider = self._providers.get(provider_name, {})

            # Check availability based on API key
            auth_env = provider.get("auth_env")
            available = auth_env is None or bool(os.environ.get(auth_env))

            spec = ModelSpec(
                model_key=model_key,
                display_name=model_data.get("display_name", model_key),
                provider=provider_name,
                model_id=model_data.get("model_id", ""),
                base_url=provider.get("base_url", ""),
                auth_env=auth_env,
                api_format=provider.get("api_format", ""),
                context_window=model_data.get("context_window", 4096),
                max_output_tokens=model_data.get("max_output_tokens", 1024),
                cost_per_1k_input=model_data.get("cost_per_1k_input", 0.0),
                cost_per_1k_output=model_data.get("cost_per_1k_output", 0.0),
                quality_tier=model_data.get("quality_tier", 1),
                strengths=model_data.get("strengths", []),
                weaknesses=model_data.get("weaknesses", []),
                notes=model_data.get("notes", ""),
                benchmark_scores=model_data.get("benchmark_scores", {}),
                available=available,
            )
            self._models[model_key] = spec

        self._loaded = True

    def _ensure_loaded(self) -> None:
        """Ensure the registry is loaded."""
        if not self._loaded:
            raise RegistryError("Registry not loaded. Call load() first.")

    def get(self, model_key: str) -> ModelSpec | None:
        """Get a model by its key."""
        self._ensure_loaded()
        return self._models.get(model_key)

    def get_or_raise(self, model_key: str) -> ModelSpec:
        """Get a model by its key, raising if not found."""
        model = self.get(model_key)
        if model is None:
            raise ModelNotFoundError(model_key)
        return model

    def all_models(self) -> list[ModelSpec]:
        """Get all registered models."""
        self._ensure_loaded()
        return list(self._models.values())

    def available_models(self) -> list[ModelSpec]:
        """Get all models that are currently available (have API keys)."""
        self._ensure_loaded()
        return [m for m in self._models.values() if m.available]

    def all_model_keys(self) -> list[str]:
        """Get all registered model keys."""
        self._ensure_loaded()
        return list(self._models.keys())

    def free_models(self) -> list[ModelSpec]:
        """Get all free models (cost = 0)."""
        self._ensure_loaded()
        return [m for m in self._models.values() if m.is_free()]

    def models_by_provider(self, provider: str) -> list[ModelSpec]:
        """Get all models from a specific provider."""
        self._ensure_loaded()
        return [m for m in self._models.values() if m.provider == provider]

    def cheapest_for(self, task_type: str) -> ModelSpec | None:
        """Get the cheapest available model suitable for a task type."""
        self._ensure_loaded()
        candidates = [
            m for m in self._models.values() if m.available and m.has_strength(task_type)
        ]
        if not candidates:
            # Fall back to any available model
            candidates = [m for m in self._models.values() if m.available]
        if not candidates:
            return None

        # Sort by total cost (input + output), then by quality tier descending
        return min(
            candidates, key=lambda m: (m.cost_per_1k_input + m.cost_per_1k_output, -m.quality_tier)
        )

    def best_for(self, task_type: str) -> ModelSpec | None:
        """Get the best quality available model for a task type."""
        self._ensure_loaded()
        candidates = [
            m for m in self._models.values() if m.available and m.has_strength(task_type)
        ]
        if not candidates:
            candidates = [m for m in self._models.values() if m.available]
        if not candidates:
            return None

        # Sort by quality tier descending, then by cost ascending
        return max(
            candidates, key=lambda m: (m.quality_tier, -(m.cost_per_1k_input + m.cost_per_1k_output))
        )

    def best_value_for(self, task_type: str) -> ModelSpec | None:
        """Get the best value model (quality/cost ratio) for a task type."""
        self._ensure_loaded()
        candidates = [
            m for m in self._models.values() if m.available and m.has_strength(task_type)
        ]
        if not candidates:
            candidates = [m for m in self._models.values() if m.available]
        if not candidates:
            return None

        def value_score(m: ModelSpec) -> float:
            total_cost = m.cost_per_1k_input + m.cost_per_1k_output
            if total_cost == 0:
                # Free models get high value but capped below paid top-tier
                return m.quality_tier * 100
            # Quality tier per dollar (scaled for readability)
            return m.quality_tier / total_cost

        return max(candidates, key=value_score)

    def get_routing(self, task_type: str, tier: str = "best") -> list[str]:
        """Get recommended model keys for a task type and tier.

        Args:
            task_type: The type of task (e.g., "code", "reasoning")
            tier: One of "best", "budget", or "free"

        Returns:
            List of model keys in priority order
        """
        self._ensure_loaded()
        routing = self._task_routing.get(task_type, {})
        return routing.get(tier, [])

    def update_benchmark(self, model_key: str, task_type: str, score: float) -> None:
        """Update a benchmark score for a model.

        Args:
            model_key: The model to update
            task_type: The benchmark task type
            score: The score (typically 0.0-1.0)
        """
        model = self.get(model_key)
        if model:
            model.benchmark_scores[task_type] = score

    def refresh_availability(self) -> None:
        """Re-check which models are available based on current env vars."""
        for model in self._models.values():
            if model.auth_env is None:
                model.available = True
            else:
                model.available = bool(os.environ.get(model.auth_env))

    def __len__(self) -> int:
        """Return the number of registered models."""
        return len(self._models)

    def __contains__(self, model_key: str) -> bool:
        """Check if a model key is registered."""
        return model_key in self._models
