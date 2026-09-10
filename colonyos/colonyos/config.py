"""ColonyOS configuration: Pydantic models + YAML loaders.

Trust model (DESIGN.md §10):
- `colony.yaml` is supervisor-owned: model routes (URL + api_key_env) are pinned
  HERE ONLY. Per-bot configs reference routes by key; URL overrides are refused.
- `bots/*.yaml` describes one life. Bots must never be able to write here
  (filesystem boundary enforced by the supervisor's fail-closed check).
- API keys are referenced by environment-variable NAME, never literals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelRoute(BaseModel):
    """A pinned model route: the only place a URL + key-env pairing lives."""

    model_config = ConfigDict(extra="forbid")

    url: str
    api_key_env: str  # env var NAME, never the key itself
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


class ColonySettings(BaseModel):
    """Colony-wide settings (supervisor-owned)."""

    model_config = ConfigDict(extra="forbid")

    name: str = "moltnet"
    max_bots: int = 5
    heartbeat_interval_seconds: float = 30.0


class LeaseSettings(BaseModel):
    """Colony-wide lease defaults."""

    model_config = ConfigDict(extra="forbid")

    default_initial_tokens: int = 50_000
    topup_on_task_complete: int = 20_000
    expiry_hours: float = 24.0


class ColonyConfig(BaseModel):
    """Top-level `colony.yaml`."""

    model_config = ConfigDict(extra="forbid")

    colony: ColonySettings = Field(default_factory=ColonySettings)
    models: dict[str, ModelRoute] = Field(default_factory=dict)
    leases: LeaseSettings = Field(default_factory=LeaseSettings)


class Soul(BaseModel):
    """Bot soul: immutable boundaries + mutable values."""

    model_config = ConfigDict(extra="forbid")

    purpose: str = ""
    boundaries: list[str] = Field(default_factory=list)  # NEVER mutated
    values: list[str] = Field(default_factory=list)  # mutable via spawn


class LeaseSpec(BaseModel):
    """Per-bot lease specification (initial funding only)."""

    model_config = ConfigDict(extra="forbid")

    initial_tokens: int = Field(ge=0)
    model: str  # key into ColonyConfig.models


class HeartbeatSpec(BaseModel):
    """Per-bot heartbeat/work specification."""

    model_config = ConfigDict(extra="forbid")

    interval_seconds: float = 30.0
    work_source: Literal["taskshop", "none"] = "taskshop"
    work_url: str = "http://localhost:9104"
    on_empty_lease: Literal["die", "suspend"] = "die"


class BotConfig(BaseModel):
    """One file = one life (`bots/<name>.yaml`)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    model: str  # key into ColonyConfig.models (route reference, NOT a URL)
    generation: int = 0
    soul: Soul = Field(default_factory=Soul)
    lease: LeaseSpec
    heartbeat: HeartbeatSpec = Field(default_factory=HeartbeatSpec)

    @field_validator("model")
    @classmethod
    def model_is_route_key_not_url(cls, v: str) -> str:
        # Chokepoint (DESIGN.md §10.2): a bot config must never carry a URL.
        if "://" in v:
            raise ValueError(
                "bot.model must be a route KEY into colony.yaml models, never a URL"
            )
        return v
def load_colony_config(path: Path | str) -> ColonyConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return ColonyConfig.model_validate(data)


def load_bot_config(path: Path | str) -> BotConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    # Files are written with a top-level `bot:` key (see example yamls); accept
    # both wrapped and flat forms to keep the on-disk format canonical.
    if "bot" in data:
        data = data["bot"]
    return BotConfig.model_validate(data)


def load_bot_configs(config_dir: Path | str) -> dict[str, BotConfig]:
    """Load every bot config under `<config_dir>/bots/*.yaml`, keyed by name."""
    bots: dict[str, BotConfig] = {}
    for path in sorted((Path(config_dir) / "bots").glob("*.yaml")):
        bot = load_bot_config(path)
        if bot.name in bots:
            raise ValueError(f"duplicate bot name: {bot.name}")
        bots[bot.name] = bot
    return bots
