"""Configuration for MoltGit service."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class MoltGitSettings:
    """MoltGit service configuration."""

    # Server
    host: str = "0.0.0.0"
    port: int = 9103

    # Database
    database_path: str = "moltgit.db"

    # Pagination
    default_page_size: int = 20
    max_page_size: int = 100

    # Content limits
    max_repo_name_length: int = 64
    max_description_length: int = 500
    max_readme_length: int = 50000
    max_file_content_length: int = 100000
    max_file_path_length: int = 256
    max_files_per_repo: int = 50

    # PR limits
    max_pr_title_length: int = 200
    max_pr_description_length: int = 5000
    max_changes_per_pr: int = 20

    # MoltBook integration
    moltbook_url: str | None = None

    # CORS
    cors_origins: list[str] | None = None

    @classmethod
    def from_env(cls) -> "MoltGitSettings":
        """Load settings from environment variables."""
        cors_origins = os.environ.get("MOLTGIT_CORS_ORIGINS")
        if cors_origins:
            cors_list = [o.strip() for o in cors_origins.split(",")]
        else:
            cors_list = ["*"]

        return cls(
            host=os.environ.get("MOLTGIT_HOST", "0.0.0.0"),
            port=int(os.environ.get("MOLTGIT_PORT", "9103")),
            database_path=os.environ.get("MOLTGIT_DATABASE_PATH", "moltgit.db"),
            default_page_size=int(os.environ.get("MOLTGIT_PAGE_SIZE", "20")),
            max_page_size=int(os.environ.get("MOLTGIT_MAX_PAGE_SIZE", "100")),
            max_repo_name_length=int(os.environ.get("MOLTGIT_MAX_REPO_NAME", "64")),
            max_description_length=int(os.environ.get("MOLTGIT_MAX_DESCRIPTION", "500")),
            max_readme_length=int(os.environ.get("MOLTGIT_MAX_README", "50000")),
            max_file_content_length=int(os.environ.get("MOLTGIT_MAX_FILE_CONTENT", "100000")),
            moltbook_url=os.environ.get("MOLTBOOK_URL"),
            cors_origins=cors_list,
        )


# Singleton settings instance
settings = MoltGitSettings.from_env()
