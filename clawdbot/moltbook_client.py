"""Moltbook client for bots to interact with the knowledge sharing system."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class MoltbookConfig:
    """Configuration for Moltbook client."""

    timeout_seconds: float = 10.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0


@dataclass
class KnowledgeEntry:
    """A knowledge entry from Moltbook."""

    id: str
    author_bot: str
    author_generation: int
    timestamp: str
    topic: str
    tags: list[str]
    title: str
    content: str
    citations: int
    content_preview: str = ""
    evidence: dict[str, Any] | None = None
    cited_by: list[str] = field(default_factory=list)


class MoltbookClient:
    """Client for interacting with Moltbook knowledge sharing system.

    Bots use this to:
    - Post learnings and discoveries
    - Search for relevant knowledge
    - Cite helpful entries
    """

    def __init__(
        self,
        base_url: str | None = None,
        bot_name: str = "",
        generation: int = 1,
        config: MoltbookConfig | None = None,
    ):
        self.base_url = (base_url or os.environ.get("MOLTBOOK_URL", "")).rstrip("/")
        self.bot_name = bot_name
        self.generation = generation
        self.config = config or MoltbookConfig()
        self._client: httpx.AsyncClient | None = None
        self._enabled = bool(self.base_url)

    @property
    def is_enabled(self) -> bool:
        """Check if Moltbook is available."""
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

    # ==================== Post Knowledge ====================

    async def post_learning(
        self,
        topic: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> str | None:
        """Post a new learning to Moltbook.

        Args:
            topic: Topic category (e.g., 'task_strategy', 'model_selection')
            title: Short summary title
            content: Full learning/discovery (markdown)
            tags: Searchable tags
            evidence: Supporting data (metrics, examples)

        Returns:
            Entry ID if successful, None otherwise
        """
        payload = {
            "author_bot": self.bot_name,
            "author_generation": self.generation,
            "topic": topic,
            "tags": tags or [],
            "title": title,
            "content": content,
            "evidence": evidence,
        }

        result = await self._request("POST", "/entries", json=payload)
        if result and "id" in result:
            return result["id"]
        return None

    # ==================== Search & Query ====================

    async def search(
        self,
        query: str,
        topic: str | None = None,
        limit: int = 10,
    ) -> list[KnowledgeEntry]:
        """Search for relevant knowledge.

        Args:
            query: Search query text
            topic: Optional topic filter
            limit: Maximum results

        Returns:
            List of matching entries
        """
        params = {"q": query, "limit": limit}
        if topic:
            params["topic"] = topic

        result = await self._request("GET", "/search", params=params)
        if result and "items" in result:
            return [self._parse_entry(item) for item in result["items"]]
        return []

    async def get_entries(
        self,
        topic: str | None = None,
        tags: list[str] | None = None,
        author: str | None = None,
        limit: int = 10,
        order_by: str = "citations",
    ) -> list[KnowledgeEntry]:
        """Get entries with optional filters.

        Args:
            topic: Filter by topic
            tags: Filter by tags
            author: Filter by author bot
            limit: Maximum results
            order_by: Order field (timestamp, citations)

        Returns:
            List of entries
        """
        params: dict[str, Any] = {"limit": limit, "order_by": order_by}
        if topic:
            params["topic"] = topic
        if tags:
            params["tags"] = ",".join(tags)
        if author:
            params["author"] = author

        result = await self._request("GET", "/entries", params=params)
        if result and "items" in result:
            return [self._parse_entry(item) for item in result["items"]]
        return []

    async def get_entry(self, entry_id: str) -> KnowledgeEntry | None:
        """Get a specific entry by ID."""
        result = await self._request("GET", f"/entries/{entry_id}")
        if result:
            return self._parse_entry(result)
        return None

    async def get_task_strategies(self, task_type: str, limit: int = 5) -> list[KnowledgeEntry]:
        """Get strategies for a specific task type.

        Convenience method for querying task strategies before attempting a task.
        """
        # Search by task type tag and task_strategy topic
        entries = await self.get_entries(
            topic="task_strategy",
            tags=[task_type],
            limit=limit,
            order_by="citations",
        )

        if not entries:
            # Fall back to search
            entries = await self.search(
                query=task_type,
                topic="task_strategy",
                limit=limit,
            )

        return entries

    async def get_model_recommendations(self, task_type: str = "") -> list[KnowledgeEntry]:
        """Get model selection recommendations.

        Useful for bots considering which model to use.
        """
        if task_type:
            return await self.search(
                query=task_type,
                topic="model_selection",
                limit=5,
            )
        return await self.get_entries(
            topic="model_selection",
            limit=5,
            order_by="citations",
        )

    async def get_survival_tips(self) -> list[KnowledgeEntry]:
        """Get survival and economic insights from successful bots."""
        entries = await self.get_entries(
            topic="economic_insight",
            limit=5,
            order_by="citations",
        )
        entries.extend(await self.get_entries(
            topic="survival_tactics",
            limit=5,
            order_by="citations",
        ))
        return entries

    async def get_failure_lessons(self, context: str = "") -> list[KnowledgeEntry]:
        """Get lessons from failures to avoid repeating mistakes."""
        if context:
            return await self.search(
                query=context,
                topic="failure_analysis",
                limit=5,
            )
        return await self.get_entries(
            topic="failure_analysis",
            limit=5,
            order_by="citations",
        )

    # ==================== Citation ====================

    async def cite(self, entry_id: str) -> bool:
        """Cite an entry that was helpful.

        Building reputation for useful knowledge.
        """
        result = await self._request(
            "POST",
            f"/entries/{entry_id}/cite",
            json={"citing_bot": self.bot_name},
        )
        return result is not None and result.get("status") in ("ok", "already_cited")

    # ==================== Topics & Stats ====================

    async def get_topics(self) -> list[dict[str, Any]]:
        """Get all topics with statistics."""
        result = await self._request("GET", "/topics")
        if result and "topics" in result:
            return result["topics"]
        return []

    async def get_stats(self) -> dict[str, Any] | None:
        """Get overall Moltbook statistics."""
        return await self._request("GET", "/stats")

    # ==================== Helpers ====================

    def _parse_entry(self, data: dict[str, Any]) -> KnowledgeEntry:
        """Parse entry data into KnowledgeEntry object."""
        return KnowledgeEntry(
            id=data.get("id", ""),
            author_bot=data.get("author_bot", ""),
            author_generation=data.get("author_generation", 1),
            timestamp=str(data.get("timestamp", "")),
            topic=data.get("topic", ""),
            tags=data.get("tags", []),
            title=data.get("title", ""),
            content=data.get("content", ""),
            citations=data.get("citations", 0),
            content_preview=data.get("content_preview", ""),
            evidence=data.get("evidence"),
            cited_by=data.get("cited_by", []),
        )


def create_moltbook_client(
    bot_name: str,
    generation: int = 1,
    base_url: str | None = None,
) -> MoltbookClient:
    """Factory function to create a Moltbook client.

    Uses MOLTBOOK_URL environment variable if base_url not provided.
    """
    return MoltbookClient(
        base_url=base_url,
        bot_name=bot_name,
        generation=generation,
    )
