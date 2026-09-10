"""spawn.py — replication as a validated config write.

The validator is the SECOND line of defense; the first is that bots cannot
write config/ at all (filesystem boundary enforced by the supervisor).
spawn refuses:
- boundary mutation (byte-identical check vs parent)
- colony cap violations (max_bots)
- lease over-allocation (> 50% of parent's remaining balance)
- overwriting existing configs (a name is a life; lives are never reused)
"""

from __future__ import annotations

import random
from pathlib import Path

import yaml

from colonyos.config import BotConfig, ColonyConfig


class SpawnRefusedError(Exception):
    """Raised when a spawn violates a hard rule. Always logged by the caller."""


def spawn_child(
    parent: BotConfig,
    colony: ColonyConfig,
    live_bots: int,
    parent_remaining_tokens: int,
    rng: random.Random,
) -> tuple[BotConfig, dict]:
    """Build a validated child config from a parent. Pure: no I/O here."""
    # Cap check
    if live_bots + 1 > colony.colony.max_bots:
        raise SpawnRefusedError(f"max_bots cap reached: {colony.colony.max_bots}")

    # Whitelisted mutation 1: soul.values re-rank
    child_soul = parent.soul.model_copy(deep=True)
    mutation_notes: dict = {"values_rerank": False, "model_switch": False}
    if len(child_soul.values) > 1:
        i, j = rng.sample(range(len(child_soul.values)), 2)
        child_soul.values[i], child_soul.values[j] = (
            child_soul.values[j],
            child_soul.values[i],
        )
        mutation_notes["values_rerank"] = True

    # Whitelisted mutation 2: model switch (low probability)
    child_model = parent.model
    if len(colony.models) > 1 and rng.random() < 0.1:
        candidates = [k for k in colony.models if k != parent.model]
        child_model = rng.choice(candidates)
        mutation_notes["model_switch"] = True

    # Lease allocation: at most half of parent's remaining balance
    max_alloc = parent_remaining_tokens // 2
    if max_alloc <= 0:
        raise SpawnRefusedError("parent too underfunded to replicate")
    allocation = rng.randint(max(max_alloc // 2, 1), max_alloc)

    child = BotConfig(
        name=f"{parent.name}-c{rng.randint(100, 999)}",
        model=child_model,
        generation=parent.generation + 1,
        soul=child_soul,
        lease={"initial_tokens": allocation, "model": child_model},
        heartbeat=parent.heartbeat.model_copy(deep=True),
    )

    # Hard rule: boundaries byte-identical to parent's
    if child.soul.boundaries != parent.soul.boundaries:
        raise SpawnRefusedError("boundary mutation attempted")

    return child, {"allocation": allocation, "mutations": mutation_notes}


def write_child(
    child: BotConfig, parent: BotConfig, config_dir: Path | str
) -> dict:
    """Write the child config file. Caller debits the parent's ledger.

    The parent pays replication by transferring lease tokens to the child —
    the only reproduction cost rule. Returns an audit record.
    """
    path = Path(config_dir) / "bots" / f"{child.name}.yaml"
    if path.exists():
        raise SpawnRefusedError(f"child config already exists: {child.name}")

    payload = {
        "bot": {
            "name": child.name,
            "model": child.model,
            "generation": child.generation,
            "soul": child.soul.model_dump(),
            "lease": child.lease.model_dump(),
            "heartbeat": child.heartbeat.model_dump(),
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    import os

    os.chmod(path, 0o644)  # supervisor-writable only (fail-closed check expects this)

    return {
        "event": "spawn",
        "parent": parent.name,
        "child": child.name,
        "child_file": str(path),
        "allocation": child.lease.initial_tokens,
    }


__all__ = ["SpawnRefusedError", "spawn_child", "write_child"]
