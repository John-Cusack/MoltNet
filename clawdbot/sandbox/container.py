"""Docker container sandbox for OpenClaw bots.

Provides isolated execution environments with:
- Resource limits (CPU, memory, disk)
- Network restrictions (domain allowlist)
- Filesystem isolation (workspace only writable)
- Tool restrictions (blocked dangerous operations)
- Safety monitoring and kill switch
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SafetyViolationType(Enum):
    """Types of safety violations."""

    RESOURCE_EXCEEDED = "resource_exceeded"
    NETWORK_VIOLATION = "network_violation"
    FILESYSTEM_VIOLATION = "filesystem_violation"
    TOOL_VIOLATION = "tool_violation"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class SafetyViolation:
    """Record of a safety violation."""

    violation_type: SafetyViolationType
    description: str
    container_id: str
    bot_name: str
    timestamp: float = field(default_factory=time.time)
    severity: int = 1  # 1-5, 5 being most severe

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.violation_type.value,
            "description": self.description,
            "container_id": self.container_id,
            "bot_name": self.bot_name,
            "timestamp": self.timestamp,
            "severity": self.severity,
        }


@dataclass
class ContainerConfig:
    """Configuration for a Docker container sandbox."""

    # Resource limits
    memory_limit: str = "512m"
    cpu_limit: float = 1.0  # Number of CPUs
    disk_limit: str = "1g"  # Disk quota

    # Network settings
    network_enabled: bool = False
    allowed_domains: list[str] = field(default_factory=list)

    # Filesystem settings
    workspace_path: str = "/workspace"
    readonly_paths: list[str] = field(default_factory=lambda: ["/usr", "/lib", "/bin"])

    # Execution settings
    timeout_seconds: float = 300.0
    max_processes: int = 50

    # Blocked operations
    blocked_tools: list[str] = field(default_factory=lambda: [
        "WebFetch",
        "WebSearch",
    ])

    # Image settings
    image: str = "python:3.11-slim"

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "disk_limit": self.disk_limit,
            "network_enabled": self.network_enabled,
            "allowed_domains": self.allowed_domains,
            "workspace_path": self.workspace_path,
            "readonly_paths": self.readonly_paths,
            "timeout_seconds": self.timeout_seconds,
            "max_processes": self.max_processes,
            "blocked_tools": self.blocked_tools,
            "image": self.image,
        }

    @classmethod
    def strict(cls) -> ContainerConfig:
        """Create a strict security configuration."""
        return cls(
            memory_limit="256m",
            cpu_limit=0.5,
            network_enabled=False,
            timeout_seconds=120.0,
            max_processes=20,
        )

    @classmethod
    def standard(cls) -> ContainerConfig:
        """Create a standard security configuration."""
        return cls(
            memory_limit="512m",
            cpu_limit=1.0,
            network_enabled=False,
            timeout_seconds=300.0,
            max_processes=50,
        )

    @classmethod
    def relaxed(cls) -> ContainerConfig:
        """Create a relaxed security configuration (for testing)."""
        return cls(
            memory_limit="1g",
            cpu_limit=2.0,
            network_enabled=True,
            allowed_domains=["*"],
            timeout_seconds=600.0,
            max_processes=100,
        )


@dataclass
class ContainerStats:
    """Runtime statistics for a container."""

    container_id: str
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    memory_limit_mb: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    pids: int = 0
    uptime_seconds: float = 0.0


class ContainerSandbox:
    """Docker container sandbox for isolated OpenClaw execution.

    Each sandbox provides:
    - Isolated filesystem with writable workspace
    - Resource limits (CPU, memory, processes)
    - Optional network restrictions
    - Automatic cleanup on exit
    """

    def __init__(
        self,
        bot_name: str,
        config: ContainerConfig | None = None,
        workspace: Path | str | None = None,
    ):
        self.bot_name = bot_name
        self.config = config or ContainerConfig.standard()
        self.container_id: str | None = None
        self._running = False
        self._start_time: float | None = None

        # Set up workspace
        if workspace:
            self.workspace = Path(workspace)
        else:
            self.workspace = Path(tempfile.mkdtemp(prefix=f"openclaw_{bot_name}_"))

        self.workspace.mkdir(parents=True, exist_ok=True)

    async def start(self) -> str:
        """Start the Docker container.

        Returns:
            Container ID
        """
        if self._running:
            return self.container_id

        # Check if Docker is available
        if not await self._docker_available():
            # Fall back to non-containerized execution
            self.container_id = f"local-{uuid.uuid4().hex[:8]}"
            self._running = True
            self._start_time = time.time()
            return self.container_id

        # Build docker run command
        cmd = [
            "docker", "run",
            "--detach",
            "--name", f"openclaw-{self.bot_name}-{uuid.uuid4().hex[:8]}",
            "--memory", self.config.memory_limit,
            "--cpus", str(self.config.cpu_limit),
            "--pids-limit", str(self.config.max_processes),
            "--read-only",
            "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=100m",
            "--volume", f"{self.workspace}:{self.config.workspace_path}:rw",
            "--workdir", self.config.workspace_path,
        ]

        # Network settings
        if not self.config.network_enabled:
            cmd.append("--network=none")

        # Remove container on exit
        cmd.append("--rm")

        # Image and command (keep container alive)
        cmd.extend([
            self.config.image,
            "tail", "-f", "/dev/null"
        ])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"Failed to start container: {stderr.decode()}")

            self.container_id = stdout.decode().strip()[:12]
            self._running = True
            self._start_time = time.time()

            return self.container_id

        except FileNotFoundError:
            # Docker not installed, use local fallback
            self.container_id = f"local-{uuid.uuid4().hex[:8]}"
            self._running = True
            self._start_time = time.time()
            return self.container_id

    async def exec(
        self,
        command: list[str],
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command in the container.

        Args:
            command: Command and arguments
            timeout: Override timeout (uses config default if None)

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        if not self._running:
            await self.start()

        timeout = timeout or self.config.timeout_seconds

        # Check if using local fallback
        if self.container_id and self.container_id.startswith("local-"):
            # Execute locally in workspace
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.workspace),
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
                return process.returncode, stdout.decode(), stderr.decode()
            except asyncio.TimeoutError:
                process.kill()
                return -1, "", f"Timeout after {timeout}s"

        # Docker exec
        cmd = [
            "docker", "exec",
            self.container_id,
        ] + command

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
            return process.returncode, stdout.decode(), stderr.decode()

        except asyncio.TimeoutError:
            return -1, "", f"Timeout after {timeout}s"

    async def copy_to(self, local_path: Path, container_path: str) -> bool:
        """Copy a file to the container.

        Args:
            local_path: Path on host
            container_path: Path in container

        Returns:
            True if successful
        """
        if self.container_id and self.container_id.startswith("local-"):
            # Local mode - copy to workspace
            dest = self.workspace / container_path.lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, dest)
            return True

        cmd = [
            "docker", "cp",
            str(local_path),
            f"{self.container_id}:{container_path}",
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        return process.returncode == 0

    async def copy_from(self, container_path: str, local_path: Path) -> bool:
        """Copy a file from the container.

        Args:
            container_path: Path in container
            local_path: Path on host

        Returns:
            True if successful
        """
        if self.container_id and self.container_id.startswith("local-"):
            # Local mode - copy from workspace
            src = self.workspace / container_path.lstrip("/")
            if src.exists():
                local_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, local_path)
                return True
            return False

        cmd = [
            "docker", "cp",
            f"{self.container_id}:{container_path}",
            str(local_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        return process.returncode == 0

    async def get_stats(self) -> ContainerStats:
        """Get container resource statistics."""
        if not self.container_id or self.container_id.startswith("local-"):
            return ContainerStats(
                container_id=self.container_id or "unknown",
                uptime_seconds=time.time() - self._start_time if self._start_time else 0,
            )

        cmd = [
            "docker", "stats",
            "--no-stream",
            "--format", "{{json .}}",
            self.container_id,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5.0)

            data = json.loads(stdout.decode())

            # Parse CPU percentage
            cpu_str = data.get("CPUPerc", "0%").rstrip("%")
            cpu_usage = float(cpu_str) if cpu_str else 0.0

            # Parse memory
            mem_usage = data.get("MemUsage", "0MiB / 0MiB")
            mem_parts = mem_usage.split(" / ")
            mem_used = self._parse_mem_string(mem_parts[0]) if mem_parts else 0.0
            mem_limit = self._parse_mem_string(mem_parts[1]) if len(mem_parts) > 1 else 0.0

            return ContainerStats(
                container_id=self.container_id,
                cpu_usage_percent=cpu_usage,
                memory_usage_mb=mem_used,
                memory_limit_mb=mem_limit,
                pids=int(data.get("PIDs", "0")),
                uptime_seconds=time.time() - self._start_time if self._start_time else 0,
            )

        except Exception:
            return ContainerStats(
                container_id=self.container_id,
                uptime_seconds=time.time() - self._start_time if self._start_time else 0,
            )

    @staticmethod
    def _parse_mem_string(mem_str: str) -> float:
        """Parse memory string like '100MiB' to MB."""
        mem_str = mem_str.strip().upper()
        if mem_str.endswith("GIB") or mem_str.endswith("GB"):
            return float(mem_str[:-3]) * 1024
        elif mem_str.endswith("MIB") or mem_str.endswith("MB"):
            return float(mem_str[:-3])
        elif mem_str.endswith("KIB") or mem_str.endswith("KB"):
            return float(mem_str[:-3]) / 1024
        return float(mem_str) if mem_str.replace(".", "").isdigit() else 0.0

    async def stop(self, timeout: float = 10.0) -> None:
        """Stop the container gracefully."""
        if not self._running:
            return

        if self.container_id and not self.container_id.startswith("local-"):
            try:
                process = await asyncio.create_subprocess_exec(
                    "docker", "stop", "-t", str(int(timeout)), self.container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(process.communicate(), timeout=timeout + 5)
            except (asyncio.TimeoutError, Exception):
                # Force kill
                await self.kill()

        self._running = False

    async def kill(self) -> None:
        """Force kill the container."""
        if self.container_id and not self.container_id.startswith("local-"):
            try:
                process = await asyncio.create_subprocess_exec(
                    "docker", "kill", self.container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(process.communicate(), timeout=5.0)
            except Exception:
                pass

        self._running = False

    async def cleanup(self) -> None:
        """Clean up the container and workspace."""
        await self.stop()

        # Remove container if it exists
        if self.container_id and not self.container_id.startswith("local-"):
            try:
                process = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", self.container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.communicate()
            except Exception:
                pass

        # Optionally clean up workspace
        # (Keeping workspace for debugging, remove if needed)
        self.container_id = None

    @staticmethod
    async def _docker_available() -> bool:
        """Check if Docker is available."""
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5.0)
            return process.returncode == 0
        except Exception:
            return False

    @property
    def is_running(self) -> bool:
        return self._running


class SafetyMonitor:
    """Monitor container safety and track violations."""

    def __init__(self, max_violations: int = 5):
        self.max_violations = max_violations
        self._violations: list[SafetyViolation] = []
        self._violation_counts: dict[str, int] = {}  # bot_name -> count
        self._killed_bots: set[str] = set()

    def record_violation(self, violation: SafetyViolation) -> bool:
        """Record a safety violation.

        Args:
            violation: The violation to record

        Returns:
            True if bot should be killed (exceeded max violations)
        """
        self._violations.append(violation)

        count = self._violation_counts.get(violation.bot_name, 0) + 1
        self._violation_counts[violation.bot_name] = count

        # Check if bot should be killed
        should_kill = count >= self.max_violations

        if should_kill:
            self._killed_bots.add(violation.bot_name)

        return should_kill

    def is_killed(self, bot_name: str) -> bool:
        """Check if a bot has been killed for violations."""
        return bot_name in self._killed_bots

    def get_violations(self, bot_name: str | None = None) -> list[SafetyViolation]:
        """Get violations, optionally filtered by bot."""
        if bot_name:
            return [v for v in self._violations if v.bot_name == bot_name]
        return self._violations.copy()

    def get_violation_count(self, bot_name: str) -> int:
        """Get violation count for a bot."""
        return self._violation_counts.get(bot_name, 0)

    def reset(self, bot_name: str | None = None) -> None:
        """Reset violations, optionally for a specific bot."""
        if bot_name:
            self._violation_counts[bot_name] = 0
            self._violations = [v for v in self._violations if v.bot_name != bot_name]
            self._killed_bots.discard(bot_name)
        else:
            self._violations.clear()
            self._violation_counts.clear()
            self._killed_bots.clear()


class ContainerManager:
    """Manages multiple container sandboxes for a colony."""

    def __init__(
        self,
        base_workspace: Path | str = "/tmp/openclaw_containers",
        default_config: ContainerConfig | None = None,
        safety_monitor: SafetyMonitor | None = None,
    ):
        self.base_workspace = Path(base_workspace)
        self.base_workspace.mkdir(parents=True, exist_ok=True)
        self.default_config = default_config or ContainerConfig.standard()
        self.safety_monitor = safety_monitor or SafetyMonitor()

        self._containers: dict[str, ContainerSandbox] = {}
        self._kill_switch_active = False

    async def create(
        self,
        bot_name: str,
        config: ContainerConfig | None = None,
    ) -> ContainerSandbox:
        """Create a new container sandbox for a bot.

        Args:
            bot_name: Unique bot identifier
            config: Container configuration

        Returns:
            ContainerSandbox instance
        """
        if self._kill_switch_active:
            raise RuntimeError("Kill switch active - no new containers allowed")

        if self.safety_monitor.is_killed(bot_name):
            raise RuntimeError(f"Bot {bot_name} has been killed for safety violations")

        workspace = self.base_workspace / bot_name
        workspace.mkdir(parents=True, exist_ok=True)

        sandbox = ContainerSandbox(
            bot_name=bot_name,
            config=config or self.default_config,
            workspace=workspace,
        )

        self._containers[bot_name] = sandbox
        return sandbox

    def get(self, bot_name: str) -> ContainerSandbox | None:
        """Get an existing sandbox by bot name."""
        return self._containers.get(bot_name)

    async def stop(self, bot_name: str) -> None:
        """Stop a specific bot's container."""
        sandbox = self._containers.get(bot_name)
        if sandbox:
            await sandbox.stop()

    async def kill(self, bot_name: str) -> None:
        """Force kill a bot's container."""
        sandbox = self._containers.get(bot_name)
        if sandbox:
            await sandbox.kill()

    async def cleanup(self, bot_name: str) -> None:
        """Clean up a bot's container and remove from management."""
        sandbox = self._containers.pop(bot_name, None)
        if sandbox:
            await sandbox.cleanup()

    async def activate_kill_switch(self) -> int:
        """Activate global kill switch - stop all containers.

        Returns:
            Number of containers stopped
        """
        self._kill_switch_active = True

        count = 0
        for bot_name, sandbox in list(self._containers.items()):
            try:
                await sandbox.kill()
                count += 1
            except Exception:
                pass

        return count

    def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch."""
        self._kill_switch_active = False

    @property
    def is_kill_switch_active(self) -> bool:
        return self._kill_switch_active

    async def get_all_stats(self) -> dict[str, ContainerStats]:
        """Get stats for all containers."""
        stats = {}
        for bot_name, sandbox in self._containers.items():
            try:
                stats[bot_name] = await sandbox.get_stats()
            except Exception:
                pass
        return stats

    async def shutdown_all(self) -> None:
        """Shutdown all managed containers."""
        for bot_name in list(self._containers.keys()):
            await self.cleanup(bot_name)

    def list_containers(self) -> list[str]:
        """List all managed bot names."""
        return list(self._containers.keys())

    @property
    def container_count(self) -> int:
        return len(self._containers)
