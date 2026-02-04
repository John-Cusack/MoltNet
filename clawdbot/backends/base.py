"""Abstract base class for LLM backends."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Message:
    """A chat message."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM backend."""

    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    latency_ms: float
    raw_response: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    def __init__(
        self,
        model_id: str,
        base_url: str,
        api_key: str | None = None,
        cost_per_1k_input: float = 0.0,
        cost_per_1k_output: float = 0.0,
        timeout: float = 60.0,
    ):
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output
        self.timeout = timeout

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for given token counts."""
        input_cost = (input_tokens / 1000) * self.cost_per_1k_input
        output_cost = (output_tokens / 1000) * self.cost_per_1k_output
        return input_cost + output_cost

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional backend-specific parameters

        Returns:
            LLMResponse with generated content and metadata
        """
        ...

    @abstractmethod
    async def generate_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from a chat history.

        Args:
            messages: List of chat messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional backend-specific parameters

        Returns:
            LLMResponse with generated content and metadata
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the backend is healthy and responsive.

        Returns:
            True if healthy, False otherwise
        """
        ...

    async def close(self) -> None:
        """Clean up any resources. Override if needed."""
        pass

    def _measure_time(self) -> float:
        """Get current time in milliseconds for latency measurement."""
        return time.perf_counter() * 1000

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model_id}, url={self.base_url})"
