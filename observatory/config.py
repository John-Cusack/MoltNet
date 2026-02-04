"""Observatory configuration from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Observatory settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_prefix="OBSERVATORY_",
        env_file=".env",
        extra="ignore",
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 9100
    debug: bool = False

    # Database settings
    database_path: str = "observatory.db"

    # CORS settings
    cors_origins: list[str] = ["*"]

    # Retention settings (in seconds)
    telemetry_retention: int = 86400 * 7  # 7 days
    event_retention: int = 86400 * 30  # 30 days

    # Dashboard settings
    poll_interval_ms: int = 5000  # 5 seconds


settings = Settings()
