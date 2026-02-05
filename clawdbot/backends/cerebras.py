"""Cerebras backend via OpenCode - High-speed inference.

This backend uses Cerebras inference through OpenCode or direct API,
offering extremely fast token generation.
"""

from __future__ import annotations

import httpx

from clawdbot.backends.base import LLMBackend, LLMResponse, Message
from clawdbot.exceptions import BackendError


class CerebrasBackend(LLMBackend):
    """Backend for Cerebras inference.

    Cerebras offers extremely fast inference speeds. This backend supports
    both direct API access and OpenCode integration.
    """

    def __init__(
        self,
        model_id: str = "zai-glm-4.7",
        api_key: str | None = None,
        base_url: str = "https://api.cerebras.ai/v1",
        cost_per_1k_input: float = 0.0,  # Varies by plan
        cost_per_1k_output: float = 0.0,  # Varies by plan
        timeout: float = 30.0,  # Cerebras is fast
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
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
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
        """Generate a response using Cerebras API."""
        messages = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        return await self.generate_chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    async def generate_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from chat history."""
        client = await self._get_client()
        start_time = self._measure_time()

        # Convert messages to API format
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        payload = {
            "model": self.model_id,
            "messages": api_messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # Add any extra parameters
        for key, value in kwargs.items():
            if key not in payload:
                payload[key] = value

        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise BackendError(
                "cerebras", f"HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise BackendError("cerebras", f"Request failed: {e}") from e

        latency_ms = self._measure_time() - start_time

        # Extract response
        choices = data.get("choices", [])
        content = ""
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")

        # Token usage
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

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
        """Check if Cerebras API is reachable."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.base_url}/models")
            return response.status_code in (200, 401)
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
