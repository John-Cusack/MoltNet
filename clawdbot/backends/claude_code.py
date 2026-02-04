"""Claude Code CLI backend - Uses the Claude Code CLI for inference.

This backend allows bots to use Claude Code (the CLI tool) as an LLM backend,
which can be useful when you have a Max plan subscription and want to use
it for token-based billing.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil

from clawdbot.backends.base import LLMBackend, LLMResponse, Message
from clawdbot.exceptions import BackendError


class ClaudeCodeBackend(LLMBackend):
    """Backend that uses Claude Code CLI for inference.

    This backend invokes the `claude` CLI tool to generate responses.
    Useful for Max plan users who want to use their subscription.

    Note: This is a subprocess-based backend, so it may have higher
    latency than direct API calls.
    """

    def __init__(
        self,
        model_id: str = "claude-sonnet-4-5-20250514",
        timeout: float = 120.0,
        claude_path: str | None = None,
    ):
        super().__init__(
            model_id=model_id,
            base_url="",  # Not used - we call CLI directly
            api_key=None,  # Not used - CLI handles auth
            cost_per_1k_input=0.0,  # Covered by Max plan
            cost_per_1k_output=0.0,  # Covered by Max plan
            timeout=timeout,
        )
        # Find claude CLI path
        self.claude_path = claude_path or shutil.which("claude") or "claude"

    async def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response using Claude Code CLI."""
        start_time = self._measure_time()

        # Build the command
        cmd = [self.claude_path, "--print"]

        if system:
            cmd.extend(["--system", system])

        if max_tokens:
            cmd.extend(["--max-tokens", str(max_tokens)])

        # Add the prompt
        cmd.extend(["--prompt", prompt])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout,
            )

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise BackendError("claude_code", f"CLI error: {error_msg}")

            content = stdout.decode().strip()

        except asyncio.TimeoutError:
            raise BackendError("claude_code", f"Timeout after {self.timeout}s")
        except FileNotFoundError:
            raise BackendError(
                "claude_code",
                f"Claude CLI not found at {self.claude_path}. Install with: npm install -g @anthropic-ai/claude-code",
            )

        latency_ms = self._measure_time() - start_time

        # Claude Code doesn't return token counts directly
        # Estimate based on character count (rough approximation)
        estimated_input_tokens = len(prompt) // 4
        estimated_output_tokens = len(content) // 4

        return LLMResponse(
            content=content,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
            cost_usd=0.0,  # Covered by Max plan
            model=self.model_id,
            latency_ms=latency_ms,
            raw_response={"source": "claude_code_cli"},
        )

    async def generate_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from chat history.

        Claude Code CLI doesn't support multi-turn natively in --print mode,
        so we format the messages into a single prompt.
        """
        # Extract system message if present
        system = ""
        chat_messages = []
        for msg in messages:
            if msg.role == "system":
                system = msg.content
            else:
                chat_messages.append(msg)

        # Format chat history into prompt
        prompt_parts = []
        for msg in chat_messages:
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

    async def health_check(self) -> bool:
        """Check if Claude Code CLI is available."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.claude_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
            return process.returncode == 0
        except Exception:
            return False

    async def close(self) -> None:
        """No cleanup needed for CLI backend."""
        pass
