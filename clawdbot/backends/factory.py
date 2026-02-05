"""Backend factory - Routes to appropriate backend based on model type.

This factory creates the right backend based on:
- Model type (Claude vs Cerebras)
- Environment (container vs host)

Routing logic:
- Claude models: GatewayBackend (routes to gateway service on host)
- Cerebras models: CerebrasBackend (direct API calls, self-contained)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from clawdbot.backends.base import LLMBackend
from clawdbot.backends.cerebras import CerebrasBackend


def is_claude_model(model_id: str) -> bool:
    """Check if model is a Claude model."""
    model_lower = model_id.lower()
    return any(x in model_lower for x in ["claude", "opus", "sonnet"])


def is_cerebras_model(model_id: str) -> bool:
    """Check if model is a Cerebras model (including GLM-4.7)."""
    model_lower = model_id.lower()
    return any(x in model_lower for x in ["cerebras", "llama", "glm", "zai"])


def create_backend(
    model_id: str,
    workspace: Path | str | None = None,
    gateway_url: str | None = None,
    bot_name: str | None = None,
    timeout: float = 300.0,
    **kwargs,
) -> LLMBackend:
    """Create appropriate backend based on model type.

    Args:
        model_id: Model identifier (e.g., "claude_code/opus-4-5" or "cerebras/zai-glm-4.7")
        workspace: Working directory for file operations
        gateway_url: URL of gateway service (for Claude models in containers)
        bot_name: Bot name for request tracking
        timeout: Request timeout in seconds
        **kwargs: Additional backend-specific parameters

    Returns:
        Configured LLMBackend instance

    Routing:
        - Claude models → GatewayBackend (routes to host gateway)
        - Cerebras models → CerebrasBackend (direct API calls)
    """
    if is_cerebras_model(model_id):
        # Cerebras: Self-contained with direct API access
        api_key = os.environ.get("CEREBRAS_API_KEY")
        if not api_key:
            raise ValueError("CEREBRAS_API_KEY environment variable required for Cerebras models")

        # Extract actual model name from model_id (e.g., "cerebras/zai-glm-4.7" -> "zai-glm-4.7")
        actual_model = model_id.split("/")[-1] if "/" in model_id else model_id

        return CerebrasBackend(
            model_id=actual_model,
            api_key=api_key,
            timeout=timeout,
        )

    elif is_claude_model(model_id):
        # Claude: Route through gateway service
        # Import here to avoid circular imports
        from clawdbot.gateway.client import GatewayBackend

        gateway_url = gateway_url or os.environ.get(
            "GATEWAY_URL",
            "http://host.docker.internal:8080"  # Default for Docker containers
        )

        return GatewayBackend(
            model_id=model_id,
            gateway_url=gateway_url,
            workspace=str(workspace) if workspace else None,
            bot_name=bot_name,
            timeout=timeout,
            prefer_claude=True,
        )

    else:
        # Default to gateway (will use overflow logic)
        from clawdbot.gateway.client import GatewayBackend

        gateway_url = gateway_url or os.environ.get(
            "GATEWAY_URL",
            "http://host.docker.internal:8080"
        )

        return GatewayBackend(
            model_id=model_id,
            gateway_url=gateway_url,
            workspace=str(workspace) if workspace else None,
            bot_name=bot_name,
            timeout=timeout,
            prefer_claude=False,
        )


class BackendFactory:
    """Factory for creating backends with consistent configuration.

    Supports both self-contained (Cerebras) and gateway-routed (Claude) backends.
    """

    def __init__(
        self,
        gateway_url: str | None = None,
        default_timeout: float = 300.0,
    ):
        """Initialize backend factory.

        Args:
            gateway_url: URL of gateway service for Claude models
            default_timeout: Default request timeout
        """
        self.gateway_url = gateway_url or os.environ.get(
            "GATEWAY_URL",
            "http://host.docker.internal:8080"
        )
        self.default_timeout = default_timeout
        self._backends: dict[str, LLMBackend] = {}

    def create(
        self,
        bot_id: str,
        model_id: str,
        workspace: Path | str | None = None,
        timeout: float | None = None,
        **kwargs,
    ) -> LLMBackend:
        """Create backend for a bot.

        Args:
            bot_id: Unique bot identifier
            model_id: Model to use
            workspace: Working directory
            timeout: Request timeout (uses default if None)
            **kwargs: Additional backend parameters

        Returns:
            Configured backend
        """
        backend = create_backend(
            model_id=model_id,
            workspace=workspace,
            gateway_url=self.gateway_url,
            bot_name=bot_id,
            timeout=timeout or self.default_timeout,
            **kwargs,
        )

        self._backends[bot_id] = backend
        return backend

    def get(self, bot_id: str) -> LLMBackend | None:
        """Get existing backend by bot ID."""
        return self._backends.get(bot_id)

    async def close_all(self) -> None:
        """Close all managed backends."""
        for backend in self._backends.values():
            await backend.close()
        self._backends.clear()

    async def close(self, bot_id: str) -> None:
        """Close a specific backend."""
        if bot_id in self._backends:
            await self._backends[bot_id].close()
            del self._backends[bot_id]
