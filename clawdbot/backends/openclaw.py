"""OpenClaw backend - Spawns and controls OpenClaw autonomous agent instances.

This backend allows MoltNet bots to use OpenClaw as their execution engine,
enabling real-world tasks like file management, code analysis, and automation.
Each bot gets its own isolated OpenClaw instance with configurable tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawdbot.backends.base import LLMBackend, LLMResponse, Message
from clawdbot.exceptions import BackendError


@dataclass
class OpenClawConfig:
    """Configuration for an OpenClaw instance."""

    model: str = "claude-sonnet-4-5-20250514"
    thinking_level: str = "medium"  # none, low, medium, high
    enabled_tools: list[str] = field(default_factory=lambda: [
        "Read", "Write", "Edit", "Glob", "Grep", "Bash"
    ])
    blocked_tools: list[str] = field(default_factory=lambda: [
        "WebFetch", "WebSearch"  # Block network by default
    ])
    max_turns: int = 10
    timeout_seconds: float = 300.0
    soul_prompt: str = ""
    allowed_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "thinking_level": self.thinking_level,
            "enabled_tools": self.enabled_tools,
            "blocked_tools": self.blocked_tools,
            "max_turns": self.max_turns,
            "timeout_seconds": self.timeout_seconds,
            "soul_prompt": self.soul_prompt,
            "allowed_commands": self.allowed_commands,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenClawConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionMessage:
    """A message in an OpenClaw session."""

    role: str  # user, assistant
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    timestamp: float = 0.0


@dataclass
class OpenClawSession:
    """Represents an active OpenClaw session."""

    session_id: str
    workspace: Path
    port: int
    process: asyncio.subprocess.Process | None = None
    messages: list[SessionMessage] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0


class OpenClawBackend(LLMBackend):
    """Backend that spawns and controls OpenClaw instances.

    This backend manages OpenClaw autonomous agent processes, allowing
    bots to run real-world tasks in isolated workspaces.

    Key features:
    - Spawns dedicated OpenClaw instance per bot
    - Configurable tools and permissions
    - Workspace isolation
    - Session history tracking
    - Graceful shutdown support
    """

    # Port allocation tracking
    _allocated_ports: set[int] = set()
    _port_lock: asyncio.Lock | None = None
    _base_port: int = 18790

    def __init__(
        self,
        model_id: str = "claude-sonnet-4-5-20250514",
        config: OpenClawConfig | None = None,
        workspace: Path | str | None = None,
        openclaw_path: str | None = None,
        timeout: float = 300.0,
    ):
        super().__init__(
            model_id=model_id,
            base_url="",  # OpenClaw is local
            api_key=None,  # CLI handles auth
            cost_per_1k_input=0.0,  # Cost tracked separately
            cost_per_1k_output=0.0,
            timeout=timeout,
        )

        self.config = config or OpenClawConfig(model=model_id)
        self.openclaw_path = openclaw_path or shutil.which("claude") or "claude"

        # Workspace setup
        if workspace:
            self.workspace = Path(workspace)
        else:
            self.workspace = Path(tempfile.mkdtemp(prefix="openclaw_"))

        self.workspace.mkdir(parents=True, exist_ok=True)

        # Session tracking
        self.session: OpenClawSession | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._port: int | None = None

    @classmethod
    async def _get_port_lock(cls) -> asyncio.Lock:
        """Get or create the port allocation lock."""
        if cls._port_lock is None:
            cls._port_lock = asyncio.Lock()
        return cls._port_lock

    @classmethod
    async def allocate_port(cls) -> int:
        """Allocate a unique port for a new instance."""
        lock = await cls._get_port_lock()
        async with lock:
            port = cls._base_port
            while port in cls._allocated_ports:
                port += 1
            cls._allocated_ports.add(port)
            return port

    @classmethod
    async def release_port(cls, port: int) -> None:
        """Release an allocated port."""
        lock = await cls._get_port_lock()
        async with lock:
            cls._allocated_ports.discard(port)

    async def spawn(self) -> OpenClawSession:
        """Spawn a new OpenClaw instance.

        Returns:
            OpenClawSession with process info
        """
        if self.session is not None:
            return self.session

        # Allocate port
        self._port = await self.allocate_port()

        # Create session
        session_id = str(uuid.uuid4())[:8]
        self.session = OpenClawSession(
            session_id=session_id,
            workspace=self.workspace,
            port=self._port,
        )

        # Write SOUL.md if provided
        if self.config.soul_prompt:
            soul_path = self.workspace / "SOUL.md"
            soul_path.write_text(self.config.soul_prompt)

        # Write openclaw config
        config_path = self.workspace / ".openclaw.json"
        config_data = {
            "model": self.config.model,
            "enabledTools": self.config.enabled_tools,
            "blockedTools": self.config.blocked_tools,
            "maxTurns": self.config.max_turns,
        }
        config_path.write_text(json.dumps(config_data, indent=2))

        return self.session

    async def send_task(
        self,
        prompt: str,
        thinking_level: str | None = None,
        max_turns: int | None = None,
    ) -> LLMResponse:
        """Send a task to the OpenClaw instance.

        Args:
            prompt: The task prompt
            thinking_level: Override thinking level (none/low/medium/high)
            max_turns: Maximum turns for this task

        Returns:
            LLMResponse with the result
        """
        if self.session is None:
            await self.spawn()

        start_time = self._measure_time()

        # Build command
        cmd = [
            self.openclaw_path,
            "--print",
            "--dangerously-skip-permissions",
        ]

        # Add model
        if self.model_id:
            cmd.extend(["--model", self.model_id])

        # Add max turns
        turns = max_turns or self.config.max_turns
        cmd.extend(["--max-turns", str(turns)])

        # Add allowed tools via settings
        if self.config.enabled_tools:
            cmd.extend(["--allowedTools", ",".join(self.config.enabled_tools)])

        # Add prompt
        cmd.append(prompt)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.timeout_seconds,
            )

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise BackendError("openclaw", f"OpenClaw error: {error_msg}")

            content = stdout.decode().strip()

        except asyncio.TimeoutError:
            if process:
                process.kill()
            raise BackendError("openclaw", f"Timeout after {self.config.timeout_seconds}s")
        except FileNotFoundError:
            raise BackendError(
                "openclaw",
                f"OpenClaw CLI not found at {self.openclaw_path}. "
                "Install with: npm install -g @anthropic-ai/claude-code"
            )

        latency_ms = self._measure_time() - start_time

        # Estimate tokens (OpenClaw doesn't return exact counts)
        estimated_input_tokens = len(prompt) // 4
        estimated_output_tokens = len(content) // 4

        # Track in session
        if self.session:
            self.session.messages.append(SessionMessage(
                role="user",
                content=prompt,
                tokens=estimated_input_tokens,
            ))
            self.session.messages.append(SessionMessage(
                role="assistant",
                content=content,
                tokens=estimated_output_tokens,
            ))
            self.session.total_tokens += estimated_input_tokens + estimated_output_tokens

        return LLMResponse(
            content=content,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
            cost_usd=0.0,  # OpenClaw via Max plan
            model=self.model_id,
            latency_ms=latency_ms,
            raw_response={"source": "openclaw", "session_id": self.session.session_id if self.session else None},
        )

    async def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response using OpenClaw.

        Args:
            prompt: The task prompt
            system: System prompt (combined with SOUL.md)
            max_tokens: Not used - OpenClaw manages this
            temperature: Not used - OpenClaw manages this

        Returns:
            LLMResponse with result
        """
        # Combine system prompt with task
        if system:
            full_prompt = f"[System: {system}]\n\n{prompt}"
        else:
            full_prompt = prompt

        return await self.send_task(
            prompt=full_prompt,
            max_turns=kwargs.get("max_turns"),
        )

    async def generate_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from chat history.

        OpenClaw doesn't support multi-turn natively in CLI mode,
        so we format messages into a single prompt.
        """
        system = ""
        prompt_parts = []

        for msg in messages:
            if msg.role == "system":
                system = msg.content
            else:
                role_label = "Human" if msg.role == "user" else "Assistant"
                prompt_parts.append(f"{role_label}: {msg.content}")

        prompt = "\n\n".join(prompt_parts)

        return await self.generate(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    async def get_session_history(self) -> list[SessionMessage]:
        """Get the session message history.

        Returns:
            List of session messages
        """
        if self.session is None:
            return []
        return self.session.messages.copy()

    async def get_workspace_files(self) -> list[Path]:
        """List files in the workspace.

        Returns:
            List of file paths
        """
        files = []
        for path in self.workspace.rglob("*"):
            if path.is_file():
                files.append(path)
        return files

    async def read_workspace_file(self, path: str | Path) -> str:
        """Read a file from the workspace.

        Args:
            path: Relative or absolute path

        Returns:
            File contents
        """
        if isinstance(path, str):
            path = Path(path)

        if not path.is_absolute():
            path = self.workspace / path

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not str(path).startswith(str(self.workspace)):
            raise PermissionError(f"Access denied: {path}")

        return path.read_text()

    async def health_check(self) -> bool:
        """Check if OpenClaw CLI is available."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.openclaw_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
            return process.returncode == 0
        except Exception:
            return False

    async def shutdown(self) -> None:
        """Shutdown the OpenClaw instance and clean up."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        if self._port:
            await self.release_port(self._port)
            self._port = None

        self._process = None
        self.session = None

    async def close(self) -> None:
        """Clean up resources."""
        await self.shutdown()

    def get_stats(self) -> dict[str, Any]:
        """Get session statistics."""
        return {
            "session_id": self.session.session_id if self.session else None,
            "workspace": str(self.workspace),
            "port": self._port,
            "message_count": len(self.session.messages) if self.session else 0,
            "total_tokens": self.session.total_tokens if self.session else 0,
            "model": self.model_id,
            "config": self.config.to_dict(),
        }


class OpenClawBackendFactory:
    """Factory for creating OpenClaw backends with consistent configuration."""

    def __init__(
        self,
        base_workspace: Path | str = "/tmp/openclaw_workspaces",
        default_config: OpenClawConfig | None = None,
    ):
        self.base_workspace = Path(base_workspace)
        self.base_workspace.mkdir(parents=True, exist_ok=True)
        self.default_config = default_config or OpenClawConfig()
        self._backends: dict[str, OpenClawBackend] = {}

    def create(
        self,
        bot_id: str,
        config: OpenClawConfig | None = None,
    ) -> OpenClawBackend:
        """Create a new OpenClaw backend for a bot.

        Args:
            bot_id: Unique identifier for the bot
            config: OpenClaw configuration (uses default if None)

        Returns:
            Configured OpenClawBackend
        """
        workspace = self.base_workspace / bot_id
        workspace.mkdir(parents=True, exist_ok=True)

        cfg = config or self.default_config
        backend = OpenClawBackend(
            model_id=cfg.model,
            config=cfg,
            workspace=workspace,
        )

        self._backends[bot_id] = backend
        return backend

    async def shutdown_all(self) -> None:
        """Shutdown all managed backends."""
        for backend in self._backends.values():
            await backend.shutdown()
        self._backends.clear()

    def get(self, bot_id: str) -> OpenClawBackend | None:
        """Get an existing backend by bot ID."""
        return self._backends.get(bot_id)
