"""Configuration for Task Shop service."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class TaskShopSettings:
    """Task Shop service configuration."""

    # Server
    host: str = "0.0.0.0"
    port: int = 9104

    # Database
    database_path: str = "taskshop.db"

    # Benchmarks
    benchmark_dir: str = "data/benchmarks"

    # Verification
    verification_timeout: float = 30.0

    # Pagination
    default_page_size: int = 20
    max_page_size: int = 100

    # Assignment limits
    max_active_assignments: int = 1  # Per bot
    default_max_cycles: int = 3

    # CORS
    cors_origins: list[str] | None = None

    @classmethod
    def from_env(cls) -> TaskShopSettings:
        """Load settings from environment variables."""
        cors_origins = os.environ.get("TASKSHOP_CORS_ORIGINS")
        if cors_origins:
            cors_list = [o.strip() for o in cors_origins.split(",")]
        else:
            cors_list = ["*"]

        return cls(
            host=os.environ.get("TASKSHOP_HOST", "0.0.0.0"),
            port=int(os.environ.get("TASKSHOP_PORT", "9104")),
            database_path=os.environ.get("TASKSHOP_DATABASE_PATH", "taskshop.db"),
            benchmark_dir=os.environ.get("TASKSHOP_BENCHMARK_DIR", "data/benchmarks"),
            verification_timeout=float(
                os.environ.get("TASKSHOP_VERIFICATION_TIMEOUT", "30.0")
            ),
            default_page_size=int(os.environ.get("TASKSHOP_PAGE_SIZE", "20")),
            max_page_size=int(os.environ.get("TASKSHOP_MAX_PAGE_SIZE", "100")),
            max_active_assignments=int(
                os.environ.get("TASKSHOP_MAX_ACTIVE_ASSIGNMENTS", "1")
            ),
            default_max_cycles=int(os.environ.get("TASKSHOP_DEFAULT_MAX_CYCLES", "3")),
            cors_origins=cors_list,
        )


# Singleton settings instance
settings = TaskShopSettings.from_env()
