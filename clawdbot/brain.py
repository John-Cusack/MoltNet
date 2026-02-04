"""Brain Router - Intelligent model selection with budget tracking."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from clawdbot.backends.base import LLMBackend, LLMResponse, Message
from clawdbot.backends.anthropic import AnthropicBackend
from clawdbot.backends.cerebras import CerebrasBackend
from clawdbot.backends.claude_code import ClaudeCodeBackend
from clawdbot.backends.ollama import OllamaBackend
from clawdbot.backends.openai_compatible import OpenAICompatibleBackend
from clawdbot.exceptions import BackendError, BudgetExceededError, ModelNotFoundError
from clawdbot.llm_registry import LLMRegistry, ModelSpec


@dataclass
class BrainConfig:
    """Configuration for the brain router."""

    budget_per_cycle: float = 0.05  # USD
    default_task_type: str = "general"
    prefer_local: bool = True  # Prefer local models when possible
    fallback_to_free: bool = True  # Fall back to free models when over budget
    max_retries: int = 2
    routing_strategy: str = "best_value"  # "best", "cheapest", "best_value"


@dataclass
class BrainState:
    """Current state of the brain router."""

    cycle_spend: float = 0.0
    request_count: int = 0
    failed_models: set[str] = field(default_factory=set)
    last_model_used: str | None = None


class BrainRouter:
    """Intelligent router for LLM requests with budget tracking and fallbacks."""

    def __init__(
        self,
        config: dict[str, Any] | BrainConfig | None = None,
        registry: LLMRegistry | None = None,
    ):
        if isinstance(config, BrainConfig):
            self.config = config
        elif isinstance(config, dict):
            self.config = BrainConfig(**config)
        else:
            self.config = BrainConfig()

        self.registry = registry or LLMRegistry()
        self.state = BrainState()
        self._backends: dict[str, LLMBackend] = {}

    @property
    def remaining_budget(self) -> float:
        """Remaining budget for this cycle."""
        return max(0.0, self.config.budget_per_cycle - self.state.cycle_spend)

    def reset_cycle(self) -> None:
        """Reset the cycle state (budget, failures, etc.)."""
        self.state = BrainState()

    def _create_backend(self, spec: ModelSpec) -> LLMBackend:
        """Create a backend instance for a model spec."""
        if spec.api_format == "ollama":
            return OllamaBackend(
                model_id=spec.model_id,
                base_url=spec.base_url,
            )
        elif spec.api_format == "anthropic":
            api_key = os.environ.get(spec.auth_env or "")
            if not api_key:
                raise BackendError(spec.provider, f"Missing API key: {spec.auth_env}")
            return AnthropicBackend(
                model_id=spec.model_id,
                api_key=api_key,
                base_url=spec.base_url,
                cost_per_1k_input=spec.cost_per_1k_input,
                cost_per_1k_output=spec.cost_per_1k_output,
            )
        elif spec.api_format == "openai_compatible":
            api_key = os.environ.get(spec.auth_env or "")
            if not api_key:
                raise BackendError(spec.provider, f"Missing API key: {spec.auth_env}")
            return OpenAICompatibleBackend(
                model_id=spec.model_id,
                api_key=api_key,
                base_url=spec.base_url,
                cost_per_1k_input=spec.cost_per_1k_input,
                cost_per_1k_output=spec.cost_per_1k_output,
            )
        elif spec.api_format == "claude_code":
            # Claude Code CLI - uses Max plan subscription
            return ClaudeCodeBackend(
                model_id=spec.model_id,
            )
        elif spec.api_format == "cerebras":
            api_key = os.environ.get(spec.auth_env or "")
            if not api_key:
                raise BackendError(spec.provider, f"Missing API key: {spec.auth_env}")
            return CerebrasBackend(
                model_id=spec.model_id,
                api_key=api_key,
                base_url=spec.base_url,
                cost_per_1k_input=spec.cost_per_1k_input,
                cost_per_1k_output=spec.cost_per_1k_output,
            )
        else:
            raise BackendError(spec.provider, f"Unknown API format: {spec.api_format}")

    def _get_backend(self, model_key: str) -> LLMBackend:
        """Get or create a backend for a model."""
        if model_key not in self._backends:
            spec = self.registry.get(model_key)
            if spec is None:
                raise ModelNotFoundError(model_key)
            self._backends[model_key] = self._create_backend(spec)
        return self._backends[model_key]

    def select_model(
        self,
        task_type: str | None = None,
        prefer_model: str | None = None,
        max_cost: float | None = None,
    ) -> ModelSpec:
        """Select the best model for a task given constraints.

        Args:
            task_type: Type of task (e.g., "code", "reasoning")
            prefer_model: Preferred model key (used if available and within budget)
            max_cost: Maximum cost per 1k tokens (input + output)

        Returns:
            Selected ModelSpec

        Raises:
            ModelNotFoundError: If no suitable model is found
        """
        task_type = task_type or self.config.default_task_type
        effective_max_cost = max_cost

        # If we're running low on budget, restrict to cheaper models
        if self.remaining_budget < 0.01:
            effective_max_cost = 0.001  # Very cheap models only

        # Try preferred model first
        if prefer_model:
            spec = self.registry.get(prefer_model)
            if spec and spec.available and prefer_model not in self.state.failed_models:
                if effective_max_cost is None or (
                    spec.cost_per_1k_input + spec.cost_per_1k_output <= effective_max_cost
                ):
                    return spec

        # Get candidates based on strategy
        candidates = []
        if self.config.routing_strategy == "best":
            model = self.registry.best_for(task_type)
            if model:
                candidates.append(model)
        elif self.config.routing_strategy == "cheapest":
            model = self.registry.cheapest_for(task_type)
            if model:
                candidates.append(model)
        else:  # best_value
            model = self.registry.best_value_for(task_type)
            if model:
                candidates.append(model)

        # Add fallback candidates
        for model in self.registry.available_models():
            if model not in candidates and model.model_key not in self.state.failed_models:
                candidates.append(model)

        # Filter by cost if specified
        if effective_max_cost is not None:
            candidates = [
                m
                for m in candidates
                if m.cost_per_1k_input + m.cost_per_1k_output <= effective_max_cost
            ]

        # Prefer local models if configured
        if self.config.prefer_local:
            local = [m for m in candidates if m.is_free()]
            if local:
                candidates = local + [m for m in candidates if not m.is_free()]

        # Return first valid candidate
        for candidate in candidates:
            if candidate.model_key not in self.state.failed_models:
                return candidate

        # Last resort: any free model
        if self.config.fallback_to_free:
            free_models = self.registry.free_models()
            for model in free_models:
                if model.available and model.model_key not in self.state.failed_models:
                    return model

        raise ModelNotFoundError("No suitable model available")

    async def generate(
        self,
        prompt: str,
        system: str = "",
        task_type: str | None = None,
        prefer_model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        strict_budget: bool = True,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response using the best available model.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            task_type: Type of task for routing
            prefer_model: Preferred model key
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            strict_budget: Raise BudgetExceededError if over budget
            **kwargs: Additional backend-specific parameters

        Returns:
            LLMResponse from the selected model

        Raises:
            BudgetExceededError: If strict_budget and budget exceeded
            BackendError: If all models fail
        """
        # Check budget before starting
        if strict_budget and self.remaining_budget <= 0 and not self.config.fallback_to_free:
            raise BudgetExceededError(self.state.cycle_spend, self.config.budget_per_cycle)

        # Select model
        try:
            spec = self.select_model(task_type=task_type, prefer_model=prefer_model)
        except ModelNotFoundError:
            if strict_budget:
                raise BudgetExceededError(self.state.cycle_spend, self.config.budget_per_cycle)
            raise

        # Try to generate with retries
        last_error: Exception | None = None
        tried_models: list[str] = []

        for attempt in range(self.config.max_retries + 1):
            model_key = spec.model_key
            tried_models.append(model_key)

            try:
                backend = self._get_backend(model_key)
                response = await backend.generate(
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )

                # Update state
                self.state.cycle_spend += response.cost_usd
                self.state.request_count += 1
                self.state.last_model_used = model_key

                return response

            except BackendError as e:
                last_error = e
                self.state.failed_models.add(model_key)

                # Try to get a different model
                try:
                    spec = self.select_model(task_type=task_type)
                    if spec.model_key in tried_models:
                        break  # No new models to try
                except ModelNotFoundError:
                    break

        raise BackendError(
            "brain", f"All models failed. Tried: {tried_models}. Last error: {last_error}"
        )

    async def generate_chat(
        self,
        messages: list[Message],
        task_type: str | None = None,
        prefer_model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        strict_budget: bool = True,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from chat history.

        Similar to generate() but for multi-turn conversations.
        """
        if strict_budget and self.remaining_budget <= 0 and not self.config.fallback_to_free:
            raise BudgetExceededError(self.state.cycle_spend, self.config.budget_per_cycle)

        try:
            spec = self.select_model(task_type=task_type, prefer_model=prefer_model)
        except ModelNotFoundError:
            if strict_budget:
                raise BudgetExceededError(self.state.cycle_spend, self.config.budget_per_cycle)
            raise

        last_error: Exception | None = None
        tried_models: list[str] = []

        for attempt in range(self.config.max_retries + 1):
            model_key = spec.model_key
            tried_models.append(model_key)

            try:
                backend = self._get_backend(model_key)
                response = await backend.generate_chat(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )

                self.state.cycle_spend += response.cost_usd
                self.state.request_count += 1
                self.state.last_model_used = model_key

                return response

            except BackendError as e:
                last_error = e
                self.state.failed_models.add(model_key)

                try:
                    spec = self.select_model(task_type=task_type)
                    if spec.model_key in tried_models:
                        break
                except ModelNotFoundError:
                    break

        raise BackendError(
            "brain", f"All models failed. Tried: {tried_models}. Last error: {last_error}"
        )

    async def health_check(self, model_key: str | None = None) -> dict[str, bool]:
        """Check health of one or all backends.

        Args:
            model_key: Specific model to check, or None for all available

        Returns:
            Dict mapping model_key to health status
        """
        results = {}

        if model_key:
            try:
                backend = self._get_backend(model_key)
                results[model_key] = await backend.health_check()
            except Exception:
                results[model_key] = False
        else:
            for spec in self.registry.available_models():
                try:
                    backend = self._get_backend(spec.model_key)
                    results[spec.model_key] = await backend.health_check()
                except Exception:
                    results[spec.model_key] = False

        return results

    async def close(self) -> None:
        """Close all backend connections."""
        for backend in self._backends.values():
            await backend.close()
        self._backends.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get current brain statistics."""
        return {
            "cycle_spend": self.state.cycle_spend,
            "remaining_budget": self.remaining_budget,
            "request_count": self.state.request_count,
            "failed_models": list(self.state.failed_models),
            "last_model_used": self.state.last_model_used,
            "active_backends": list(self._backends.keys()),
        }
