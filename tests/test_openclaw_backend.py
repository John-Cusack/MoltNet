"""Tests for OpenClaw backend."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawdbot.backends.openclaw import (
    OpenClawBackend,
    OpenClawConfig,
    OpenClawSession,
    OpenClawBackendFactory,
)


class TestOpenClawConfig:
    """Tests for OpenClawConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OpenClawConfig()

        assert config.model == "claude-sonnet-4-5-20250514"
        assert config.thinking_level == "medium"
        assert "Read" in config.enabled_tools
        assert "Write" in config.enabled_tools
        assert config.max_turns == 10
        assert config.timeout_seconds == 300.0

    def test_config_to_dict(self):
        """Test configuration serialization."""
        config = OpenClawConfig(
            model="test-model",
            thinking_level="high",
            max_turns=15,
        )

        data = config.to_dict()

        assert data["model"] == "test-model"
        assert data["thinking_level"] == "high"
        assert data["max_turns"] == 15

    def test_config_from_dict(self):
        """Test configuration deserialization."""
        data = {
            "model": "custom-model",
            "thinking_level": "low",
            "enabled_tools": ["Read", "Write"],
            "max_turns": 5,
        }

        config = OpenClawConfig.from_dict(data)

        assert config.model == "custom-model"
        assert config.thinking_level == "low"
        assert config.enabled_tools == ["Read", "Write"]
        assert config.max_turns == 5


class TestOpenClawBackend:
    """Tests for OpenClawBackend."""

    def test_initialization(self):
        """Test backend initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = OpenClawBackend(
                model_id="test-model",
                workspace=tmpdir,
            )

            assert backend.model_id == "test-model"
            assert backend.workspace == Path(tmpdir)
            assert backend.session is None

    @pytest.mark.asyncio
    async def test_spawn_creates_session(self):
        """Test that spawn creates a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = OpenClawBackend(workspace=tmpdir)

            session = await backend.spawn()

            assert session is not None
            assert isinstance(session, OpenClawSession)
            assert session.workspace == Path(tmpdir)

    @pytest.mark.asyncio
    async def test_port_allocation(self):
        """Test that ports are allocated uniquely."""
        # Reset port tracking
        OpenClawBackend._allocated_ports.clear()

        port1 = await OpenClawBackend.allocate_port()
        port2 = await OpenClawBackend.allocate_port()

        assert port1 != port2
        assert port1 in OpenClawBackend._allocated_ports
        assert port2 in OpenClawBackend._allocated_ports

        await OpenClawBackend.release_port(port1)
        assert port1 not in OpenClawBackend._allocated_ports

    @pytest.mark.asyncio
    async def test_send_task_with_mock(self):
        """Test send_task with mocked subprocess."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = OpenClawBackend(workspace=tmpdir)

            # Mock subprocess execution
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"test response", b""))

            with patch("asyncio.create_subprocess_exec", return_value=mock_process):
                response = await backend.send_task("Test prompt")

            assert response.content == "test response"
            assert response.model == backend.model_id

    @pytest.mark.asyncio
    async def test_health_check_with_mock(self):
        """Test health check with mocked subprocess."""
        backend = OpenClawBackend()

        # Mock subprocess for health check
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            healthy = await backend.health_check()

        assert healthy is True

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Test backend shutdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = OpenClawBackend(workspace=tmpdir)
            await backend.spawn()

            await backend.shutdown()

            assert backend.session is None
            assert backend._port is None

    def test_soul_prompt_written_to_workspace(self):
        """Test that SOUL.md is written on spawn."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = OpenClawConfig(soul_prompt="You are a helpful assistant.")
            backend = OpenClawBackend(
                workspace=tmpdir,
                config=config,
            )

            # Manually call spawn logic
            asyncio.run(backend.spawn())

            soul_path = Path(tmpdir) / "SOUL.md"
            assert soul_path.exists()
            assert soul_path.read_text() == "You are a helpful assistant."


class TestOpenClawBackendFactory:
    """Tests for OpenClawBackendFactory."""

    def test_create_backend(self):
        """Test creating backends through factory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = OpenClawBackendFactory(base_workspace=tmpdir)

            backend = factory.create("bot-1")

            assert backend is not None
            assert "bot-1" in str(backend.workspace)

    def test_get_backend(self):
        """Test retrieving created backends."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = OpenClawBackendFactory(base_workspace=tmpdir)

            backend = factory.create("bot-1")
            retrieved = factory.get("bot-1")

            assert retrieved is backend

    @pytest.mark.asyncio
    async def test_shutdown_all(self):
        """Test shutting down all backends."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = OpenClawBackendFactory(base_workspace=tmpdir)

            factory.create("bot-1")
            factory.create("bot-2")

            await factory.shutdown_all()

            assert factory.get("bot-1") is None
            assert factory.get("bot-2") is None
