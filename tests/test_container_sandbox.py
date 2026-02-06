"""Tests for Docker container sandbox."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from clawdbot.sandbox.container import (
    ContainerConfig,
    ContainerSandbox,
    ContainerManager,
    SafetyMonitor,
    SafetyViolation,
    SafetyViolationType,
)


class TestContainerConfig:
    """Tests for ContainerConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = ContainerConfig()

        assert config.memory_limit == "512m"
        assert config.cpu_limit == 1.0
        assert not config.network_enabled
        assert config.timeout_seconds == 300.0

    def test_strict_config(self):
        """Test strict configuration preset."""
        config = ContainerConfig.strict()

        assert config.memory_limit == "256m"
        assert config.cpu_limit == 0.5
        assert config.timeout_seconds == 120.0

    def test_relaxed_config(self):
        """Test relaxed configuration preset."""
        config = ContainerConfig.relaxed()

        assert config.memory_limit == "1g"
        assert config.cpu_limit == 2.0
        assert config.network_enabled

    def test_config_to_dict(self):
        """Test configuration serialization."""
        config = ContainerConfig(memory_limit="1g", cpu_limit=2.0)
        data = config.to_dict()

        assert data["memory_limit"] == "1g"
        assert data["cpu_limit"] == 2.0


class TestContainerSandbox:
    """Tests for ContainerSandbox."""

    def test_initialization(self):
        """Test sandbox initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = ContainerSandbox(
                bot_name="test-bot",
                workspace=tmpdir,
            )

            assert sandbox.bot_name == "test-bot"
            assert sandbox.workspace == Path(tmpdir)
            assert not sandbox.is_running

    @pytest.mark.asyncio
    async def test_start_local_fallback(self):
        """Test starting with local fallback (no Docker)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = ContainerSandbox(
                bot_name="local-bot",
                workspace=tmpdir,
            )

            # Mock Docker as unavailable
            with patch.object(ContainerSandbox, "_docker_available", return_value=False):
                container_id = await sandbox.start()

            assert container_id.startswith("local-")
            assert sandbox.is_running

            await sandbox.cleanup()

    @pytest.mark.asyncio
    async def test_exec_local(self):
        """Test executing commands in local mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = ContainerSandbox(
                bot_name="exec-bot",
                workspace=tmpdir,
            )

            with patch.object(ContainerSandbox, "_docker_available", return_value=False):
                await sandbox.start()

            # Execute a simple command
            returncode, stdout, stderr = await sandbox.exec(["echo", "hello"])

            assert returncode == 0
            assert "hello" in stdout

            await sandbox.cleanup()

    @pytest.mark.asyncio
    async def test_copy_to_local(self):
        """Test copying files to workspace in local mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = ContainerSandbox(
                bot_name="copy-bot",
                workspace=tmpdir,
            )

            sandbox.container_id = "local-test"
            sandbox._running = True

            # Create source file
            source = Path(tmpdir) / "source.txt"
            source.write_text("test content")

            success = await sandbox.copy_to(source, "/dest.txt")

            assert success
            assert (sandbox.workspace / "dest.txt").exists()

            await sandbox.cleanup()

    @pytest.mark.asyncio
    async def test_copy_from_local(self):
        """Test copying files from workspace in local mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = ContainerSandbox(
                bot_name="copy-bot",
                workspace=tmpdir,
            )

            sandbox.container_id = "local-test"
            sandbox._running = True

            # Create file in workspace
            (sandbox.workspace / "source.txt").write_text("workspace content")

            # Copy to external location
            dest = Path(tmpdir) / "external" / "dest.txt"
            success = await sandbox.copy_from("/source.txt", dest)

            assert success
            assert dest.exists()
            assert dest.read_text() == "workspace content"

            await sandbox.cleanup()

    @pytest.mark.asyncio
    async def test_get_stats_local(self):
        """Test getting stats in local mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = ContainerSandbox(
                bot_name="stats-bot",
                workspace=tmpdir,
            )

            sandbox.container_id = "local-test"
            sandbox._running = True
            sandbox._start_time = 100.0

            with patch("time.time", return_value=110.0):
                stats = await sandbox.get_stats()

            assert stats.container_id == "local-test"
            assert stats.uptime_seconds == 10.0

            await sandbox.cleanup()

    @pytest.mark.asyncio
    async def test_stop(self):
        """Test stopping sandbox."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = ContainerSandbox(
                bot_name="stop-bot",
                workspace=tmpdir,
            )

            sandbox.container_id = "local-test"
            sandbox._running = True

            await sandbox.stop()

            assert not sandbox.is_running


class TestSafetyMonitor:
    """Tests for SafetyMonitor."""

    def test_record_violation(self):
        """Test recording safety violations."""
        monitor = SafetyMonitor(max_violations=3)

        violation = SafetyViolation(
            violation_type=SafetyViolationType.RESOURCE_EXCEEDED,
            description="Memory limit exceeded",
            container_id="container-1",
            bot_name="bad-bot",
        )

        should_kill = monitor.record_violation(violation)

        assert not should_kill  # First violation
        assert monitor.get_violation_count("bad-bot") == 1

    def test_kill_after_max_violations(self):
        """Test that bot is killed after max violations."""
        monitor = SafetyMonitor(max_violations=2)

        for i in range(3):
            violation = SafetyViolation(
                violation_type=SafetyViolationType.NETWORK_VIOLATION,
                description=f"Violation {i}",
                container_id="container-1",
                bot_name="repeat-offender",
            )
            should_kill = monitor.record_violation(violation)

        assert should_kill
        assert monitor.is_killed("repeat-offender")

    def test_get_violations_filtered(self):
        """Test getting violations filtered by bot."""
        monitor = SafetyMonitor()

        monitor.record_violation(SafetyViolation(
            violation_type=SafetyViolationType.TIMEOUT,
            description="Timeout",
            container_id="c1",
            bot_name="bot-1",
        ))
        monitor.record_violation(SafetyViolation(
            violation_type=SafetyViolationType.TIMEOUT,
            description="Timeout",
            container_id="c2",
            bot_name="bot-2",
        ))

        bot1_violations = monitor.get_violations("bot-1")

        assert len(bot1_violations) == 1
        assert bot1_violations[0].bot_name == "bot-1"

    def test_reset_bot(self):
        """Test resetting violations for a bot."""
        monitor = SafetyMonitor()

        monitor.record_violation(SafetyViolation(
            violation_type=SafetyViolationType.UNKNOWN,
            description="Test",
            container_id="c1",
            bot_name="reset-bot",
        ))

        monitor.reset("reset-bot")

        assert monitor.get_violation_count("reset-bot") == 0

    def test_reset_all(self):
        """Test resetting all violations."""
        monitor = SafetyMonitor()

        for i in range(3):
            monitor.record_violation(SafetyViolation(
                violation_type=SafetyViolationType.UNKNOWN,
                description="Test",
                container_id=f"c{i}",
                bot_name=f"bot-{i}",
            ))

        monitor.reset()

        assert len(monitor.get_violations()) == 0


class TestContainerManager:
    """Tests for ContainerManager."""

    @pytest.mark.asyncio
    async def test_create_sandbox(self):
        """Test creating sandboxes through manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ContainerManager(base_workspace=tmpdir)

            sandbox = await manager.create("bot-1")

            assert sandbox is not None
            assert "bot-1" in str(sandbox.workspace)

            await manager.shutdown_all()

    @pytest.mark.asyncio
    async def test_get_sandbox(self):
        """Test retrieving created sandboxes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ContainerManager(base_workspace=tmpdir)

            sandbox = await manager.create("bot-1")
            retrieved = manager.get("bot-1")

            assert retrieved is sandbox

            await manager.shutdown_all()

    @pytest.mark.asyncio
    async def test_kill_switch(self):
        """Test kill switch functionality."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ContainerManager(base_workspace=tmpdir)

            await manager.create("bot-1")
            await manager.create("bot-2")

            count = await manager.activate_kill_switch()

            assert count == 2
            assert manager.is_kill_switch_active

            # Should not allow new containers
            with pytest.raises(RuntimeError):
                await manager.create("bot-3")

            manager.deactivate_kill_switch()
            assert not manager.is_kill_switch_active

            await manager.shutdown_all()

    @pytest.mark.asyncio
    async def test_reject_killed_bots(self):
        """Test that killed bots cannot create new containers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SafetyMonitor(max_violations=1)
            manager = ContainerManager(
                base_workspace=tmpdir,
                safety_monitor=monitor,
            )

            # Kill a bot
            monitor.record_violation(SafetyViolation(
                violation_type=SafetyViolationType.UNKNOWN,
                description="Test",
                container_id="c1",
                bot_name="banned-bot",
            ))
            monitor.record_violation(SafetyViolation(
                violation_type=SafetyViolationType.UNKNOWN,
                description="Test",
                container_id="c1",
                bot_name="banned-bot",
            ))

            with pytest.raises(RuntimeError):
                await manager.create("banned-bot")

            await manager.shutdown_all()

    @pytest.mark.asyncio
    async def test_list_containers(self):
        """Test listing managed containers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ContainerManager(base_workspace=tmpdir)

            await manager.create("bot-1")
            await manager.create("bot-2")

            containers = manager.list_containers()

            assert "bot-1" in containers
            assert "bot-2" in containers
            assert manager.container_count == 2

            await manager.shutdown_all()
