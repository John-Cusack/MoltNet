"""Configuration for the Analyzer service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AnalyzerSettings:
    """Analyzer service configuration."""

    # Server settings
    host: str = "0.0.0.0"
    port: int = 9102

    # Data directories
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("ANALYZER_DATA_DIR", "/data")))

    @property
    def combined_db_path(self) -> Path:
        """Path to combined analysis database."""
        return self.data_dir / "combined.db"

    @property
    def runs_dir(self) -> Path:
        """Directory for individual run data."""
        return self.data_dir / "runs"

    @property
    def archives_dir(self) -> Path:
        """Directory for archived runs."""
        return self.data_dir / "archives"

    # Logging settings
    conversation_log_enabled: bool = field(
        default_factory=lambda: os.environ.get("CONVERSATION_LOG_ENABLED", "true").lower() == "true"
    )
    reflection_enabled: bool = field(
        default_factory=lambda: os.environ.get("REFLECTION_ENABLED", "true").lower() == "true"
    )
    reflection_interval_cycles: int = field(
        default_factory=lambda: int(os.environ.get("REFLECTION_INTERVAL_CYCLES", "15"))
    )

    # Run management
    auto_combine_on_shutdown: bool = field(
        default_factory=lambda: os.environ.get("AUTO_COMBINE_ON_SHUTDOWN", "true").lower() == "true"
    )
    archive_completed_runs: bool = field(
        default_factory=lambda: os.environ.get("ARCHIVE_COMPLETED_RUNS", "true").lower() == "true"
    )

    # CORS
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # Dashboard
    poll_interval_ms: int = 5000


# Singleton settings instance
settings = AnalyzerSettings()
