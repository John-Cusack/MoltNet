"""Telemetry Reporter - Fire-and-forget telemetry with circuit breaker.

Supports both HTTP telemetry to Observatory and file-based fallback logging.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from clawdbot.logging import BotFileLogger


@dataclass
class CircuitBreakerState:
    """State for the circuit breaker."""

    failures: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False


@dataclass
class TelemetryConfig:
    """Configuration for telemetry reporter."""

    timeout_seconds: float = 2.0
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 60.0
    max_queue_size: int = 100


class TelemetryReporter:
    """Fire-and-forget telemetry reporter with circuit breaker.

    This reporter is designed to never block or raise exceptions to the caller.
    All telemetry is sent asynchronously with graceful degradation on failure.

    Supports file-based fallback logging when HTTP telemetry fails or when
    a file logger is explicitly attached.
    """

    def __init__(
        self,
        observatory_url: str | None = None,
        config: TelemetryConfig | None = None,
        file_logger: "BotFileLogger | None" = None,
    ):
        self.observatory_url = observatory_url.rstrip("/") if observatory_url else None
        self.config = config or TelemetryConfig()
        self._circuit = CircuitBreakerState()
        self._client: httpx.AsyncClient | None = None
        self._pending_tasks: set[asyncio.Task] = set()
        self._queue: list[dict[str, Any]] = []
        self._enabled = bool(self.observatory_url)
        self._file_logger = file_logger

    def set_file_logger(self, file_logger: "BotFileLogger") -> None:
        """Attach a file logger for fallback/persistent logging."""
        self._file_logger = file_logger

    @property
    def is_enabled(self) -> bool:
        """Check if telemetry is enabled."""
        return self._enabled

    @property
    def is_circuit_open(self) -> bool:
        """Check if circuit breaker is open (blocking requests)."""
        if not self._circuit.is_open:
            return False

        # Check if recovery timeout has passed
        elapsed = time.time() - self._circuit.last_failure_time
        if elapsed >= self.config.recovery_timeout_seconds:
            # Reset circuit breaker
            self._circuit = CircuitBreakerState()
            return False

        return True

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
        return self._client

    def _record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self._circuit.failures += 1
        self._circuit.last_failure_time = time.time()

        if self._circuit.failures >= self.config.failure_threshold:
            self._circuit.is_open = True

    def _record_success(self) -> None:
        """Record a success and reset failure count."""
        self._circuit.failures = 0
        self._circuit.is_open = False

    async def _send_payload(self, endpoint: str, payload: dict[str, Any]) -> bool:
        """Send a payload to the observatory.

        Returns True on success, False on failure.
        On failure, falls back to file logging if available.
        """
        if not self._enabled or self.is_circuit_open:
            # Fall back to file logging
            self._log_to_file(endpoint, payload)
            return False

        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.observatory_url}/{endpoint}",
                json=payload,
            )
            if response.status_code in (200, 201):
                self._record_success()
                return True
            else:
                self._record_failure()
                # Fall back to file logging on HTTP error
                self._log_to_file(endpoint, payload)
                return False
        except Exception:
            self._record_failure()
            # Fall back to file logging on exception
            self._log_to_file(endpoint, payload)
            return False

    def _log_to_file(self, endpoint: str, payload: dict[str, Any]) -> None:
        """Log payload to file as fallback."""
        if self._file_logger is None:
            return

        try:
            if endpoint == "telemetry":
                self._file_logger.log_telemetry(
                    generation=payload.get("generation"),
                    fitness_score=payload.get("fitness_score"),
                    wallet_balance=payload.get("wallet_balance"),
                    cycle_count=payload.get("cycle_count"),
                    state=payload.get("state"),
                    brain_primary=payload.get("brain_primary"),
                    cycle_revenue=payload.get("cycle_revenue"),
                    cycle_api_spend=payload.get("cycle_api_spend"),
                    tasks_completed=payload.get("tasks_completed"),
                    tasks_failed=payload.get("tasks_failed"),
                    genome_hash=payload.get("genome_hash"),
                    parent_name=payload.get("parent_name"),
                    extra=payload.get("extra"),
                )
            elif endpoint == "events":
                self._file_logger.log_event(
                    event_type=payload.get("event_type", "unknown"),
                    data=payload.get("data"),
                )
        except Exception:
            pass  # File logging is best-effort

    def _fire_and_forget(self, endpoint: str, payload: dict[str, Any]) -> None:
        """Send a request without waiting for response.

        This creates a background task and tracks it for cleanup.
        Also logs to file for persistence (if file logger attached).
        """
        # Always log to file for persistence (independent of HTTP)
        self._log_to_file(endpoint, payload)

        if not self._enabled:
            return

        async def send_task():
            await self._send_payload(endpoint, payload)

        try:
            # Try to get the running loop
            loop = asyncio.get_running_loop()
            task = loop.create_task(send_task())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            # No running loop - queue for later
            if len(self._queue) < self.config.max_queue_size:
                self._queue.append({"endpoint": endpoint, "payload": payload})

    def report_telemetry(
        self,
        bot_name: str,
        generation: int | None = None,
        fitness_score: float | None = None,
        wallet_balance: float | None = None,
        cycle_count: int | None = None,
        state: str | None = None,
        brain_primary: str | None = None,
        cycle_revenue: float | None = None,
        cycle_api_spend: float | None = None,
        tasks_completed: int | None = None,
        tasks_failed: int | None = None,
        genome_hash: str | None = None,
        parent_name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Report bot telemetry to the observatory.

        This is a fire-and-forget operation that never blocks or raises.
        """
        payload = {
            "bot_name": bot_name,
            "timestamp": datetime.now().isoformat(),
            "generation": generation,
            "fitness_score": fitness_score,
            "wallet_balance": wallet_balance,
            "cycle_count": cycle_count,
            "state": state,
            "brain_primary": brain_primary,
            "cycle_revenue": cycle_revenue,
            "cycle_api_spend": cycle_api_spend,
            "tasks_completed": tasks_completed,
            "tasks_failed": tasks_failed,
            "genome_hash": genome_hash,
            "parent_name": parent_name,
            "extra": extra,
        }

        # Remove None values to reduce payload size
        payload = {k: v for k, v in payload.items() if v is not None}

        self._fire_and_forget("telemetry", payload)

    def report_event(
        self,
        event_type: str,
        bot_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Report an event to the observatory.

        This is a fire-and-forget operation that never blocks or raises.
        """
        payload = {
            "event_type": event_type,
            "bot_name": bot_name,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }

        payload = {k: v for k, v in payload.items() if v is not None}

        self._fire_and_forget("events", payload)

    async def flush_queue(self) -> int:
        """Flush any queued telemetry.

        Returns the number of items flushed.
        """
        if not self._queue:
            return 0

        count = 0
        while self._queue:
            item = self._queue.pop(0)
            success = await self._send_payload(item["endpoint"], item["payload"])
            if success:
                count += 1
            else:
                # Put it back if circuit opened
                if self.is_circuit_open:
                    self._queue.insert(0, item)
                    break

        return count

    async def wait_pending(self) -> None:
        """Wait for all pending telemetry tasks to complete."""
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)

    async def close(self) -> None:
        """Close the telemetry reporter."""
        # Wait for pending tasks
        await self.wait_pending()

        # Close client
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get_stats(self) -> dict[str, Any]:
        """Get telemetry reporter statistics."""
        stats = {
            "enabled": self._enabled,
            "circuit_open": self.is_circuit_open,
            "failure_count": self._circuit.failures,
            "pending_tasks": len(self._pending_tasks),
            "queue_size": len(self._queue),
            "file_logger_attached": self._file_logger is not None,
        }
        if self._file_logger:
            stats["file_logger"] = self._file_logger.get_stats()
        return stats
