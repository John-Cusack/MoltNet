"""Ollama backend for local LLM inference."""

from __future__ import annotations

import httpx

from clawdbot.backends.base import LLMBackend, LLMResponse, Message
from clawdbot.exceptions import BackendError


class OllamaBackend(LLMBackend):
    """Backend for Ollama local inference server."""

    def __init__(
        self,
        model_id: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ):
        super().__init__(
            model_id=model_id,
            base_url=base_url,
            api_key=None,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            timeout=timeout,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response using Ollama's generate endpoint."""
        client = await self._get_client()
        start_time = self._measure_time()

        payload = {
            "model": self.model_id,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        if system:
            payload["system"] = system

        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        try:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise BackendError("ollama", f"HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise BackendError("ollama", f"Request failed: {e}") from e

        latency_ms = self._measure_time() - start_time

        # Ollama returns token counts in the response
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=data.get("response", ""),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,  # Ollama is free
            model=self.model_id,
            latency_ms=latency_ms,
            raw_response=data,
        )

    async def generate_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response using Ollama's chat endpoint."""
        client = await self._get_client()
        start_time = self._measure_time()

        # Convert messages to Ollama format
        ollama_messages = [{"role": m.role, "content": m.content} for m in messages]

        payload = {
            "model": self.model_id,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        try:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise BackendError("ollama", f"HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise BackendError("ollama", f"Request failed: {e}") from e

        latency_ms = self._measure_time() - start_time

        # Extract response content
        message = data.get("message", {})
        content = message.get("content", "")

        # Token counts
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,
            model=self.model_id,
            latency_ms=latency_ms,
            raw_response=data,
        )

    async def health_check(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            client = await self._get_client()
            # Check if Ollama is running
            response = await client.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                return False

            # Check if our model is loaded
            data = response.json()
            models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
            return self.model_id in models or f"{self.model_id}:latest" in [
                m.get("name", "") for m in data.get("models", [])
            ]
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List all available models in Ollama."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
