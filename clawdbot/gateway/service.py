"""LLM Gateway Service - Routes requests to Claude CLI or Cerebras.

This service runs on the host and provides an HTTP API for containerized bots
to access LLM backends. It manages Claude CLI sessions (limited by Max plan
concurrency) and overflows to Cerebras for additional capacity.

Usage:
    uv run python -m clawdbot.gateway.service --port 8080 --claude-slots 2
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx


class ModelType(str, Enum):
    CLAUDE = "claude"
    CEREBRAS = "cerebras"


class CompletionRequest(BaseModel):
    """Request for LLM completion."""
    prompt: str
    model: str = "claude_code/opus-4-5"  # or cerebras/zai-glm-4.7
    max_turns: int = 10
    timeout_seconds: float = 300.0
    workspace: str | None = None  # Working directory for Claude
    bot_name: str | None = None  # For logging/tracking
    prefer_claude: bool = True  # Try Claude first if slots available


class CompletionResponse(BaseModel):
    """Response from LLM completion."""
    content: str
    model_used: str
    backend: str  # "claude_cli" or "cerebras_api"
    input_tokens: int
    output_tokens: int
    latency_ms: float
    queued: bool = False  # Was request queued?
    request_id: str


class GatewayStats(BaseModel):
    """Gateway statistics."""
    total_requests: int
    claude_requests: int
    cerebras_requests: int
    claude_slots_used: int
    claude_slots_max: int
    queue_depth: int
    uptime_seconds: float


@dataclass
class GatewayConfig:
    """Configuration for the gateway service."""
    port: int = 8080
    host: str = "0.0.0.0"

    # Claude CLI settings
    claude_max_slots: int = 5  # Max concurrent Claude sessions
    claude_path: str | None = None  # Path to claude binary
    claude_timeout: float = 300.0

    # Cerebras settings
    cerebras_api_key: str | None = None
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_timeout: float = 60.0

    # Routing
    overflow_to_cerebras: bool = True  # If Claude full, use Cerebras
    default_cerebras_model: str = "zai-glm-4.7"


@dataclass
class ClaudeSlot:
    """Tracks a Claude CLI slot."""
    slot_id: int
    in_use: bool = False
    current_request_id: str | None = None
    last_used: float = 0.0


class GatewayService:
    """LLM Gateway that routes to Claude CLI or Cerebras."""

    def __init__(self, config: GatewayConfig | None = None):
        self.config = config or GatewayConfig()
        self.config.claude_path = self.config.claude_path or shutil.which("claude") or "claude"
        self.config.cerebras_api_key = self.config.cerebras_api_key or os.environ.get("CEREBRAS_API_KEY")

        # Claude slot management
        self._claude_slots: list[ClaudeSlot] = [
            ClaudeSlot(slot_id=i) for i in range(self.config.claude_max_slots)
        ]
        self._slot_lock = asyncio.Lock()

        # Request queue for overflow
        self._queue: asyncio.Queue[tuple[str, CompletionRequest, asyncio.Future]] = asyncio.Queue()

        # Stats
        self._start_time = time.time()
        self._total_requests = 0
        self._claude_requests = 0
        self._cerebras_requests = 0

        # HTTP client for Cerebras
        self._http_client: httpx.AsyncClient | None = None

        # FastAPI app
        self.app = self._create_app()

    def _create_app(self) -> FastAPI:
        """Create the FastAPI application."""
        app = FastAPI(
            title="MoltNet LLM Gateway",
            description="Routes LLM requests to Claude CLI or Cerebras API",
            version="1.0.0",
        )

        @app.post("/complete", response_model=CompletionResponse)
        async def complete(request: CompletionRequest):
            return await self.complete(request)

        @app.get("/stats", response_model=GatewayStats)
        async def stats():
            return self.get_stats()

        @app.get("/health")
        async def health():
            return {
                "status": "ok",
                "claude_available": self._claude_available(),
                "cerebras_available": bool(self.config.cerebras_api_key),
            }

        return app

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.config.cerebras_timeout)
        return self._http_client

    def _claude_available(self) -> bool:
        """Check if Claude CLI is available."""
        return shutil.which(self.config.claude_path) is not None

    async def _acquire_claude_slot(self) -> ClaudeSlot | None:
        """Try to acquire a Claude slot. Returns None if all busy."""
        async with self._slot_lock:
            for slot in self._claude_slots:
                if not slot.in_use:
                    slot.in_use = True
                    slot.last_used = time.time()
                    return slot
            return None

    async def _release_claude_slot(self, slot: ClaudeSlot):
        """Release a Claude slot."""
        async with self._slot_lock:
            slot.in_use = False
            slot.current_request_id = None

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Handle a completion request."""
        request_id = str(uuid.uuid4())[:8]
        self._total_requests += 1
        start_time = time.time()

        # Determine backend based on model and availability
        model_lower = request.model.lower()
        wants_claude = "claude" in model_lower or "opus" in model_lower
        wants_cerebras = "cerebras" in model_lower or "llama" in model_lower

        # Try Claude first if requested and available
        if (wants_claude or request.prefer_claude) and not wants_cerebras:
            slot = await self._acquire_claude_slot()
            if slot:
                try:
                    slot.current_request_id = request_id
                    result = await self._call_claude(request, request_id)
                    self._claude_requests += 1
                    result.latency_ms = (time.time() - start_time) * 1000
                    return result
                finally:
                    await self._release_claude_slot(slot)
            elif self.config.overflow_to_cerebras and self.config.cerebras_api_key:
                # Overflow to Cerebras
                result = await self._call_cerebras(request, request_id)
                result.queued = True  # Indicate it was overflow
                self._cerebras_requests += 1
                result.latency_ms = (time.time() - start_time) * 1000
                return result
            else:
                raise HTTPException(
                    status_code=503,
                    detail="All Claude slots busy and no Cerebras fallback configured"
                )

        # Use Cerebras
        if self.config.cerebras_api_key:
            result = await self._call_cerebras(request, request_id)
            self._cerebras_requests += 1
            result.latency_ms = (time.time() - start_time) * 1000
            return result
        else:
            raise HTTPException(
                status_code=503,
                detail="Cerebras API key not configured"
            )

    async def _call_claude(self, request: CompletionRequest, request_id: str) -> CompletionResponse:
        """Call Claude CLI."""
        cmd = [
            self.config.claude_path,
            "--print",
            "--dangerously-skip-permissions",
            "--max-turns", str(request.max_turns),
            request.prompt,
        ]

        # Use workspace if it exists on host, otherwise use current directory
        # (Container paths like /workspace won't exist on host)
        cwd = os.getcwd()
        if request.workspace and os.path.isdir(request.workspace):
            cwd = request.workspace

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout_seconds,
            )

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise HTTPException(status_code=500, detail=f"Claude error: {error_msg}")

            content = stdout.decode().strip()

            # Estimate tokens
            input_tokens = len(request.prompt) // 4
            output_tokens = len(content) // 4

            return CompletionResponse(
                content=content,
                model_used="claude-opus-4-5",
                backend="claude_cli",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=0,  # Will be set by caller
                request_id=request_id,
            )

        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail=f"Claude timeout after {request.timeout_seconds}s")

    async def _call_cerebras(self, request: CompletionRequest, request_id: str) -> CompletionResponse:
        """Call Cerebras API."""
        client = await self._get_http_client()

        # Map model names
        model = self.config.default_cerebras_model
        if "glm" in request.model.lower() or "zai" in request.model.lower():
            model = "zai-glm-4.7"
        elif "8b" in request.model.lower():
            model = "llama3.1-8b"

        try:
            response = await client.post(
                f"{self.config.cerebras_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.cerebras_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": request.prompt}],
                    "max_tokens": 4096,
                },
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Cerebras error: {response.text}"
                )

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            return CompletionResponse(
                content=content,
                model_used=model,
                backend="cerebras_api",
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=0,
                request_id=request_id,
            )

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Cerebras timeout")

    def get_stats(self) -> GatewayStats:
        """Get gateway statistics."""
        slots_used = sum(1 for s in self._claude_slots if s.in_use)
        return GatewayStats(
            total_requests=self._total_requests,
            claude_requests=self._claude_requests,
            cerebras_requests=self._cerebras_requests,
            claude_slots_used=slots_used,
            claude_slots_max=self.config.claude_max_slots,
            queue_depth=self._queue.qsize(),
            uptime_seconds=time.time() - self._start_time,
        )

    async def close(self):
        """Clean up resources."""
        if self._http_client:
            await self._http_client.aclose()


# CLI entry point
async def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="MoltNet LLM Gateway")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--claude-slots", type=int, default=2, help="Max concurrent Claude sessions")
    args = parser.parse_args()

    config = GatewayConfig(
        port=args.port,
        host=args.host,
        claude_max_slots=args.claude_slots,
    )

    service = GatewayService(config)

    print("=" * 60)
    print("MOLTNET LLM GATEWAY")
    print("=" * 60)
    print(f"Host: {config.host}:{config.port}")
    print(f"Claude slots: {config.claude_max_slots}")
    print(f"Claude CLI: {config.claude_path}")
    print(f"Cerebras: {'configured' if config.cerebras_api_key else 'not configured'}")
    print("=" * 60)

    uvicorn_config = uvicorn.Config(
        service.app,
        host=config.host,
        port=config.port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
