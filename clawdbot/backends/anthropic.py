"""Anthropic Claude backend."""

from __future__ import annotations

import httpx

from clawdbot.backends.base import LLMBackend, LLMResponse, Message
from clawdbot.exceptions import BackendError


class AnthropicBackend(LLMBackend):
    """Backend for Anthropic's Claude API."""

    API_VERSION = "2023-06-01"

    def __init__(
        self,
        model_id: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        cost_per_1k_input: float = 0.003,
        cost_per_1k_output: float = 0.015,
        timeout: float = 60.0,
    ):
        super().__init__(
            model_id=model_id,
            base_url=base_url,
            api_key=api_key,
            cost_per_1k_input=cost_per_1k_input,
            cost_per_1k_output=cost_per_1k_output,
            timeout=timeout,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.API_VERSION,
                    "content-type": "application/json",
                },
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response using the Anthropic Messages API."""
        messages = [Message(role="user", content=prompt)]
        return await self.generate_chat(
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    async def generate_chat(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from a chat history."""
        client = await self._get_client()
        start_time = self._measure_time()

        # Convert messages to Anthropic format
        anthropic_messages = []
        for m in messages:
            if m.role == "system":
                # System messages are handled separately
                if not system:
                    system = m.content
            else:
                anthropic_messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": self.model_id,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }

        if system:
            payload["system"] = system

        try:
            response = await client.post(
                f"{self.base_url}/v1/messages",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise BackendError(
                "anthropic", f"HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise BackendError("anthropic", f"Request failed: {e}") from e

        latency_ms = self._measure_time() - start_time

        # Extract response
        content_blocks = data.get("content", [])
        content = ""
        for block in content_blocks:
            if block.get("type") == "text":
                content += block.get("text", "")

        # Token usage
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # Calculate cost
        cost = self.calculate_cost(input_tokens, output_tokens)

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=self.model_id,
            latency_ms=latency_ms,
            raw_response=data,
        )

    async def health_check(self) -> bool:
        """Check if the Anthropic API is reachable."""
        try:
            client = await self._get_client()
            # Send a minimal request to check connectivity
            # We use a very short max_tokens to minimize cost
            response = await client.post(
                f"{self.base_url}/v1/messages",
                json={
                    "model": self.model_id,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                },
            )
            # 200 = success, 401 = bad key but API reachable
            return response.status_code in (200, 401)
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
