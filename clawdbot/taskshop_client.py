"""Task Shop client for bots to interact with the benchmark marketplace."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class TaskShopConfig:
    """Configuration for Task Shop client."""

    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0


@dataclass
class TaskAssignment:
    """An active task assignment from the Task Shop."""

    assignment_id: str
    task_id: str
    benchmark: str
    category: str
    difficulty: float
    title: str
    prompt: str
    setup_code: str | None
    status: str
    cycles_spent: int
    max_cycles: int
    conversation_history: list[dict[str, Any]]


@dataclass
class CycleResult:
    """Result of submitting a cycle update."""

    assignment_id: str
    status: str
    cycles_spent: int
    max_cycles: int
    action: str
    score: float | None = None
    payout: float | None = None
    feedback: str | None = None
    auto_submitted: bool = False


class TaskShopClient:
    """Client for interacting with the Task Shop benchmark marketplace.

    Bots use this to:
    - Browse available benchmark tasks
    - Claim tasks matching their difficulty preference
    - Submit cycle responses (continue/submit/quit)
    - Get verification results and payouts
    """

    def __init__(
        self,
        base_url: str | None = None,
        bot_name: str = "",
        config: TaskShopConfig | None = None,
    ):
        self.base_url = (base_url or os.environ.get("TASKSHOP_URL", "")).rstrip("/")
        self.bot_name = bot_name
        self.config = config or TaskShopConfig()
        self._client: httpx.AsyncClient | None = None
        self._enabled = bool(self.base_url)

    @property
    def is_enabled(self) -> bool:
        """Check if Task Shop is available."""
        return self._enabled

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
        return self._client

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Make a request with retries."""
        if not self._enabled:
            return None

        url = f"{self.base_url}{endpoint}"
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                if method == "GET":
                    response = await client.get(url, params=params)
                elif method == "POST":
                    response = await client.post(url, json=json, params=params)
                else:
                    return None

                if response.status_code in (200, 201):
                    return response.json()
                elif response.status_code == 404:
                    return None
                # Retry on server errors
                if response.status_code >= 500:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                    continue
                return None
            except Exception:
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                continue

        return None

    async def close(self) -> None:
        """Close the client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ==================== Browse Tasks ====================

    async def browse_tasks(
        self,
        category: str | None = None,
        benchmark: str | None = None,
        difficulty_min: float = 0.0,
        difficulty_max: float = 1.0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Browse available tasks with filters."""
        params: dict[str, Any] = {
            "difficulty_min": difficulty_min,
            "difficulty_max": difficulty_max,
            "limit": limit,
        }
        if category:
            params["category"] = category
        if benchmark:
            params["benchmark"] = benchmark

        result = await self._request("GET", "/tasks", params=params)
        if result and "items" in result:
            return result["items"]
        return []

    # ==================== Assignments ====================

    async def claim_task(
        self,
        category: str | None = None,
        benchmark: str | None = None,
        difficulty_min: float = 0.0,
        difficulty_max: float = 1.0,
        max_cycles: int = 3,
    ) -> TaskAssignment | None:
        """Claim a task from the Task Shop.

        Returns TaskAssignment if successful, None if no tasks available.
        """
        payload: dict[str, Any] = {
            "bot_name": self.bot_name,
            "difficulty_min": difficulty_min,
            "difficulty_max": difficulty_max,
            "max_cycles": max_cycles,
        }
        if category:
            payload["category"] = category
        if benchmark:
            payload["benchmark"] = benchmark

        result = await self._request("POST", "/assignments/claim", json=payload)
        if result:
            return self._parse_assignment(result)
        return None

    async def get_active_assignment(self) -> TaskAssignment | None:
        """Get the bot's current active assignment."""
        result = await self._request("GET", f"/assignments/active/{self.bot_name}")
        if result:
            return self._parse_assignment(result)
        return None

    async def submit_cycle(
        self,
        assignment_id: str,
        action: str,
        response_content: str,
    ) -> CycleResult | None:
        """Submit a cycle update.

        Args:
            assignment_id: The assignment ID
            action: One of 'continue', 'submit', 'quit'
            response_content: The bot's response text

        Returns:
            CycleResult with status and optional verification results
        """
        payload = {
            "bot_name": self.bot_name,
            "action": action,
            "response_content": response_content,
        }

        result = await self._request(
            "POST", f"/assignments/{assignment_id}/cycle", json=payload
        )
        if result:
            return CycleResult(
                assignment_id=result.get("assignment_id", assignment_id),
                status=result.get("status", "unknown"),
                cycles_spent=result.get("cycles_spent", 0),
                max_cycles=result.get("max_cycles", 0),
                action=result.get("action", action),
                score=result.get("score"),
                payout=result.get("payout"),
                feedback=result.get("feedback"),
                auto_submitted=result.get("auto_submitted", False),
            )
        return None

    async def get_result(self, assignment_id: str) -> dict[str, Any] | None:
        """Get the verification result for a completed assignment."""
        return await self._request("GET", f"/assignments/{assignment_id}/result")

    # ==================== Statistics ====================

    async def get_my_stats(self) -> dict[str, Any] | None:
        """Get the bot's statistics."""
        return await self._request("GET", f"/stats/{self.bot_name}")

    async def get_shop_stats(self) -> dict[str, Any] | None:
        """Get overall Task Shop statistics."""
        return await self._request("GET", "/stats")

    # ==================== Health ====================

    async def health_check(self) -> bool:
        """Check if Task Shop is healthy."""
        result = await self._request("GET", "/health")
        return result is not None and result.get("status") == "ok"

    # ==================== Helpers ====================

    def _parse_assignment(self, data: dict[str, Any]) -> TaskAssignment:
        """Parse assignment response into TaskAssignment object."""
        task = data.get("task", {})
        history = data.get("conversation_history", [])

        return TaskAssignment(
            assignment_id=data.get("assignment_id", ""),
            task_id=task.get("id", ""),
            benchmark=task.get("benchmark", ""),
            category=task.get("category", ""),
            difficulty=task.get("difficulty", 0.5),
            title=task.get("title", ""),
            prompt=task.get("prompt", ""),
            setup_code=task.get("setup_code"),
            status=data.get("status", ""),
            cycles_spent=data.get("cycles_spent", 0),
            max_cycles=data.get("max_cycles", 3),
            conversation_history=history,
        )


def create_taskshop_client(
    bot_name: str,
    base_url: str | None = None,
) -> TaskShopClient:
    """Factory function to create a Task Shop client.

    Uses TASKSHOP_URL environment variable if base_url not provided.
    """
    return TaskShopClient(
        base_url=base_url,
        bot_name=bot_name,
    )
