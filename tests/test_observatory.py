"""Tests for Observatory API and database."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from observatory.database import Database
from observatory.models import EventPayload, TelemetryPayload


class TestDatabase:
    """Tests for Observatory database."""

    @pytest.fixture
    async def db(self, tmp_path):
        """Create a test database."""
        db_path = tmp_path / "test.db"
        database = Database(db_path)
        await database.connect()
        yield database
        await database.close()

    @pytest.mark.asyncio
    async def test_insert_telemetry(self, db):
        """Test inserting telemetry data."""
        payload = {
            "bot_name": "test-bot",
            "timestamp": datetime.now(),
            "generation": 1,
            "fitness_score": 0.75,
            "wallet_balance": 1.50,
            "cycle_count": 10,
            "state": "active",
            "brain_primary": "ollama/phi4-mini",
        }

        row_id = await db.insert_telemetry(payload)
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_insert_event(self, db):
        """Test inserting event data."""
        payload = {
            "event_type": "bot_started",
            "bot_name": "test-bot",
            "timestamp": datetime.now(),
            "data": {"generation": 1},
        }

        row_id = await db.insert_event(payload)
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_get_current_bots(self, db):
        """Test getting current bot statuses."""
        # Insert some telemetry
        for i in range(3):
            await db.insert_telemetry({
                "bot_name": f"bot-{i}",
                "timestamp": datetime.now(),
                "fitness_score": 0.5 + i * 0.1,
            })

        bots = await db.get_current_bots(since_seconds=60)
        assert len(bots) == 3

    @pytest.mark.asyncio
    async def test_get_colony_stats(self, db):
        """Test getting colony statistics."""
        # Insert telemetry for multiple bots
        for i in range(5):
            await db.insert_telemetry({
                "bot_name": f"bot-{i}",
                "timestamp": datetime.now(),
                "fitness_score": 0.5,
                "cycle_revenue": 0.001,
                "cycle_api_spend": 0.0005,
                "generation": i + 1,
            })

        stats = await db.get_colony_stats(since_seconds=3600)

        assert stats["total_bots"] == 5
        assert stats["avg_fitness"] == pytest.approx(0.5)
        assert stats["total_revenue"] == pytest.approx(0.005)
        assert stats["generation_range"] == (1, 5)

    @pytest.mark.asyncio
    async def test_get_brain_leaderboard(self, db):
        """Test getting brain leaderboard."""
        # Insert telemetry with different brains
        brains = ["ollama/phi4-mini", "anthropic/claude-haiku", "ollama/phi4-mini"]
        for i, brain in enumerate(brains):
            await db.insert_telemetry({
                "bot_name": f"bot-{i}",
                "timestamp": datetime.now(),
                "brain_primary": brain,
                "fitness_score": 0.5 + i * 0.1,
                "cycle_revenue": 0.001,
            })

        leaderboard = await db.get_brain_leaderboard(limit=10)

        assert len(leaderboard) == 2  # Two unique brains
        # phi4-mini should have higher count
        phi_entry = next(e for e in leaderboard if "phi4" in e["brain_model"])
        assert phi_entry["usage_count"] == 2

    @pytest.mark.asyncio
    async def test_get_time_series(self, db):
        """Test getting time series data."""
        # Insert telemetry over time (simulated)
        import time

        base_time = int(time.time())
        for i in range(10):
            await db.insert_telemetry({
                "bot_name": "test-bot",
                "timestamp": datetime.fromtimestamp(base_time - (9 - i) * 60),
                "fitness_score": 0.5 + i * 0.05,
            })

        points = await db.get_time_series(
            metric="fitness_score",
            since_seconds=3600,
            bucket_seconds=60,
        )

        assert len(points) > 0
        # Values should be increasing
        values = [p["value"] for p in points]
        assert values == sorted(values)

    @pytest.mark.asyncio
    async def test_get_recent_events(self, db):
        """Test getting recent events."""
        # Insert some events
        events = [
            {"event_type": "bot_started", "bot_name": "bot-1"},
            {"event_type": "replication", "bot_name": "bot-1"},
            {"event_type": "error", "bot_name": "bot-2"},
        ]
        for event in events:
            await db.insert_event({**event, "timestamp": datetime.now()})

        all_events = await db.get_recent_events(limit=10)
        assert len(all_events) == 3

        # Filter by type
        errors = await db.get_recent_events(limit=10, event_type="error")
        assert len(errors) == 1
        assert errors[0]["event_type"] == "error"

    @pytest.mark.asyncio
    async def test_get_bot_history(self, db):
        """Test getting bot history."""
        # Insert multiple telemetry records for one bot
        for i in range(5):
            await db.insert_telemetry({
                "bot_name": "test-bot",
                "timestamp": datetime.now(),
                "cycle_count": i + 1,
                "fitness_score": 0.5 + i * 0.1,
            })

        history = await db.get_bot_history("test-bot", since_seconds=3600)
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_invalid_metric(self, db):
        """Test that invalid metrics return empty results."""
        points = await db.get_time_series(
            metric="invalid_metric",
            since_seconds=3600,
        )
        assert points == []


class TestPydanticModels:
    """Tests for Pydantic models."""

    def test_telemetry_payload_minimal(self):
        """Test minimal telemetry payload."""
        payload = TelemetryPayload(bot_name="test-bot")
        assert payload.bot_name == "test-bot"
        assert payload.fitness_score is None

    def test_telemetry_payload_full(self):
        """Test full telemetry payload."""
        payload = TelemetryPayload(
            bot_name="test-bot",
            generation=1,
            fitness_score=0.85,
            wallet_balance=1.50,
            cycle_count=100,
            state="active",
            brain_primary="ollama/phi4-mini",
            cycle_revenue=0.001,
            cycle_api_spend=0.0005,
        )
        assert payload.fitness_score == 0.85
        assert payload.brain_primary == "ollama/phi4-mini"

    def test_telemetry_payload_validation(self):
        """Test telemetry payload validation."""
        # Fitness score must be 0-1
        with pytest.raises(ValueError):
            TelemetryPayload(bot_name="test", fitness_score=1.5)

        with pytest.raises(ValueError):
            TelemetryPayload(bot_name="test", fitness_score=-0.1)

    def test_event_payload(self):
        """Test event payload."""
        payload = EventPayload(
            event_type="replication",
            bot_name="test-bot",
            data={"child_name": "test-bot-child"},
        )
        assert payload.event_type == "replication"
        assert payload.data["child_name"] == "test-bot-child"


class TestTelemetryReporter:
    """Tests for TelemetryReporter."""

    def test_disabled_when_no_url(self):
        """Test reporter is disabled without URL."""
        from clawdbot.telemetry import TelemetryReporter

        reporter = TelemetryReporter(observatory_url=None)
        assert reporter.is_enabled is False

    def test_enabled_with_url(self):
        """Test reporter is enabled with URL."""
        from clawdbot.telemetry import TelemetryReporter

        reporter = TelemetryReporter(observatory_url="http://localhost:9100")
        assert reporter.is_enabled is True

    def test_circuit_breaker_opens(self):
        """Test circuit breaker opens after failures."""
        from clawdbot.telemetry import TelemetryConfig, TelemetryReporter

        config = TelemetryConfig(failure_threshold=3)
        reporter = TelemetryReporter(
            observatory_url="http://localhost:9100",
            config=config,
        )

        # Simulate failures
        for _ in range(3):
            reporter._record_failure()

        assert reporter.is_circuit_open is True

    def test_report_telemetry_fire_and_forget(self):
        """Test that report_telemetry doesn't block."""
        from clawdbot.telemetry import TelemetryReporter

        reporter = TelemetryReporter(observatory_url="http://invalid:9999")

        # This should not raise or block
        reporter.report_telemetry(
            bot_name="test-bot",
            fitness_score=0.5,
        )

    def test_report_event_fire_and_forget(self):
        """Test that report_event doesn't block."""
        from clawdbot.telemetry import TelemetryReporter

        reporter = TelemetryReporter(observatory_url="http://invalid:9999")

        # This should not raise or block
        reporter.report_event(
            event_type="test_event",
            bot_name="test-bot",
        )

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing the reporter."""
        from clawdbot.telemetry import TelemetryReporter

        reporter = TelemetryReporter(observatory_url="http://localhost:9100")
        await reporter.close()


# Integration test - requires running observatory
@pytest.mark.asyncio
async def test_observatory_integration():
    """Integration test for observatory API.

    Only runs if observatory is available.
    """
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:9100/health", timeout=2.0)
            if response.status_code != 200:
                pytest.skip("Observatory not available")
    except Exception:
        pytest.skip("Observatory not available")

    # Test telemetry ingestion
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:9100/telemetry",
            json={
                "bot_name": "pytest-bot",
                "fitness_score": 0.5,
                "generation": 1,
            },
        )
        assert response.status_code == 201

        # Test colony endpoint
        response = await client.get("http://localhost:9100/api/colony/current")
        assert response.status_code == 200
        data = response.json()
        assert "bots" in data

        # Test stats endpoint
        response = await client.get("http://localhost:9100/api/colony/stats")
        assert response.status_code == 200
