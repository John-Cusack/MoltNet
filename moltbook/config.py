"""Configuration for Moltbook service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MoltbookSettings:
    """Moltbook service configuration."""

    # Server
    host: str = "0.0.0.0"
    port: int = 9101

    # Database
    database_path: str = "moltbook.db"

    # Pagination
    default_page_size: int = 20
    max_page_size: int = 100

    # Content limits
    max_title_length: int = 200
    max_content_length: int = 10000
    max_tags: int = 10

    # CORS
    cors_origins: list[str] | None = None

    @classmethod
    def from_env(cls) -> "MoltbookSettings":
        """Load settings from environment variables."""
        cors_origins = os.environ.get("MOLTBOOK_CORS_ORIGINS")
        if cors_origins:
            cors_list = [o.strip() for o in cors_origins.split(",")]
        else:
            cors_list = ["*"]

        return cls(
            host=os.environ.get("MOLTBOOK_HOST", "0.0.0.0"),
            port=int(os.environ.get("MOLTBOOK_PORT", "9101")),
            database_path=os.environ.get("MOLTBOOK_DATABASE_PATH", "moltbook.db"),
            default_page_size=int(os.environ.get("MOLTBOOK_PAGE_SIZE", "20")),
            max_page_size=int(os.environ.get("MOLTBOOK_MAX_PAGE_SIZE", "100")),
            max_title_length=int(os.environ.get("MOLTBOOK_MAX_TITLE", "200")),
            max_content_length=int(os.environ.get("MOLTBOOK_MAX_CONTENT", "10000")),
            max_tags=int(os.environ.get("MOLTBOOK_MAX_TAGS", "10")),
            cors_origins=cors_list,
        )


# Singleton settings instance
settings = MoltbookSettings.from_env()
