"""Gateway Client - HTTP client for containerized bots to access LLM Gateway.

This client provides a simple interface for bots running in Docker containers
to make LLM requests through the gateway service.

Usage:
    client = GatewayClient("http://host.docker.internal:8080")
    response = await client.complete("What is 2+2?")
    print(response.content)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from clawdbot.backends.base import LLMBackend, LLMResponse, Message
from clawdbot.exceptions import BackendError


@dataclass
class GatewayResponse:
    """Response from the gateway."""
    content: str
    model_used: str
    backend: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    queued: bool
    request_id: str


class GatewayClient:
    """HTTP client for the LLM Gateway service."""

    def __init__(
        self,
        gateway_url: str | None = None,
        timeout: float = 600.0,
        bot_name: str | None = None,
    ):
        """Initialize gateway client.

        Args:
            gateway_url: URL of the gateway service. Defaults to GATEWAY_URL env var
                        or http://host.docker.internal:8080 for Docker containers.
            timeout: Request timeout in seconds.
            bot_name: Bot name for request tracking.
        """
        self.gateway_url = gateway_url or os.environ.get(
            "GATEWAY_URL",
            "http://host.docker.internal:8080"
        )
        self.gateway_url = self.gateway_url.rstrip("/")
        self.timeout = timeout
        self.bot_name = bot_name
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def complete(
        self,
        prompt: str,
        model: str = "claude_code/opus-4-5",
        max_turns: int = 10,
        timeout_seconds: float = 300.0,
        workspace: str | None = None,
        prefer_claude: bool = True,
    ) -> GatewayResponse:
        """Send a completion request to the gateway.

        Args:
            prompt: The prompt to complete.
            model: Model preference (claude_code/* or cerebras/*).
            max_turns: Maximum turns for Claude.
            timeout_seconds: Timeout for the request.
            workspace: Working directory (for file operations).
            prefer_claude: If True, prefer Claude when available.

        Returns:
            GatewayResponse with the completion.

        Raises:
            BackendError: If the request fails.
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self.gateway_url}/complete",
                json={
                    "prompt": prompt,
                    "model": model,
                    "max_turns": max_turns,
                    "timeout_seconds": timeout_seconds,
                    "workspace": workspace,
                    "bot_name": self.bot_name,
                    "prefer_claude": prefer_claude,
                },
            )

            if response.status_code != 200:
                error_detail = response.json().get("detail", response.text)
                raise BackendError("gateway", f"Gateway error: {error_detail}")

            data = response.json()
            return GatewayResponse(
                content=data["content"],
                model_used=data["model_used"],
                backend=data["backend"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                latency_ms=data["latency_ms"],
                queued=data.get("queued", False),
                request_id=data["request_id"],
            )

        except httpx.TimeoutException:
            raise BackendError("gateway", f"Gateway timeout after {self.timeout}s")
        except httpx.ConnectError:
            raise BackendError("gateway", f"Cannot connect to gateway at {self.gateway_url}")

    async def health_check(self) -> dict[str, Any]:
        """Check gateway health."""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.gateway_url}/health")
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def get_stats(self) -> dict[str, Any]:
        """Get gateway statistics."""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.gateway_url}/stats")
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class GatewayBackend(LLMBackend):
    """LLM Backend that uses the Gateway service.

    Drop-in replacement for OpenClawBackend that routes through the gateway.
    """

    def __init__(
        self,
        model_id: str = "claude_code/opus-4-5",
        gateway_url: str | None = None,
        workspace: str | None = None,
        bot_name: str | None = None,
        timeout: float = 600.0,
        prefer_claude: bool = True,
    ):
        super().__init__(
            model_id=model_id,
            base_url=gateway_url or "",
            api_key=None,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            timeout=timeout,
        )

        self.client = GatewayClient(
            gateway_url=gateway_url,
            timeout=timeout,
            bot_name=bot_name,
        )
        self.workspace = workspace
        self.prefer_claude = prefer_claude
        self._session_tokens = 0

    async def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a completion through the gateway."""
        if system:
            full_prompt = f"[System: {system}]\n\n{prompt}"
        else:
            full_prompt = prompt

        response = await self.client.complete(
            prompt=full_prompt,
            model=self.model_id,
            max_turns=kwargs.get("max_turns", 10),
            timeout_seconds=self.timeout,
            workspace=self.workspace,
            prefer_claude=self.prefer_claude,
        )

        self._session_tokens += response.input_tokens + response.output_tokens

        return LLMResponse(
            content=response.content,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=0.0,  # Max plan / free tier
            model=response.model_used,
            latency_ms=response.latency_ms,
            raw_response={
                "backend": response.backend,
                "request_id": response.request_id,
                "queued": response.queued,
            },
        )

    async def generate_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate from chat history."""
        system = ""
        prompt_parts = []

        for msg in messages:
            if msg.role == "system":
                system = msg.content
            else:
                role_label = "Human" if msg.role == "user" else "Assistant"
                prompt_parts.append(f"{role_label}: {msg.content}")

        prompt = "\n\n".join(prompt_parts)
        return await self.generate(prompt=prompt, system=system, **kwargs)

    async def health_check(self) -> bool:
        """Check if gateway is healthy."""
        result = await self.client.health_check()
        return result.get("status") == "ok"

    async def close(self):
        """Clean up resources."""
        await self.client.close()

    def get_stats(self) -> dict[str, Any]:
        """Get backend statistics."""
        return {
            "model_id": self.model_id,
            "gateway_url": self.client.gateway_url,
            "session_tokens": self._session_tokens,
            "prefer_claude": self.prefer_claude,
        }
