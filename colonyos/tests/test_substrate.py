"""ColonyOS substrate tests: lease lifecycle, spawn validation, config chokepoints.

Run: cd colonyos && uv run pytest tests/ -v
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest
import yaml

from colonyos.config import BotConfig, ColonyConfig, ModelRoute, load_bot_configs
from colonyos.lease import LeaseStore
from colonyos.spawn import SpawnRefusedError, spawn_child, write_child
from colonyos.supervisor import Supervisor


@pytest.fixture()
def tmp_dirs(tmp_path: Path) -> tuple[Path, Path]:
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    (config_dir / "bots").mkdir(parents=True)
    shutil.rmtree(tmp_path / "state", ignore_errors=True)
    return config_dir, state_dir


@pytest.fixture()
def colony() -> ColonyConfig:
    return ColonyConfig(
        models={"glm-flash": ModelRoute(url="http://localhost:8080", api_key_env="K")}
    )


def _bot_config(name: str = "bot-0", tokens: int = 1000) -> BotConfig:
    return BotConfig(
        name=name,
        model="glm-flash",
        soul={"purpose": "p", "boundaries": ["b1", "b2"], "values": ["v1", "v2"]},
        lease={"initial_tokens": tokens, "model": "glm-flash"},
    )


# ============================================================
# Lease (ledger) tests
# ============================================================


class TestLease:
    def test_birth_debit_topup_death(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("b0", 1000, expiry_hours=1)
        assert store.debit("b0", 400)
        assert store.leases["b0"].remaining_tokens == 600
        store.topup("b0", 200, note="verified-completion")
        assert store.leases["b0"].remaining_tokens == 800

    def test_underfunded_debit_refused(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("b0", 100, expiry_hours=1)
        assert not store.debit("b0", 101)
        assert store.leases["b0"].remaining_tokens == 100  # untouched

    def test_expiry_is_death(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("b0", 1000, expiry_hours=1)
        reaped = store.check_expired(now=9_999_999_999)
        assert reaped == ["b0"]
        assert not store.leases["b0"].alive
        assert store.leases["b0"].death_cause == "expired"

    def test_ledger_is_append_only_audit_trail(self, tmp_path: Path):
        import json

        store = LeaseStore(tmp_path / "state")
        store.birth("b0", 100, expiry_hours=1)
        store.debit("b0", 50)
        store.topup("b0", 10)
        lines = (tmp_path / "state" / "ledger.jsonl").read_text().strip().split("\n")
        kinds = [json.loads(line)["kind"] for line in lines]
        assert kinds == ["birth", "debit", "topup"]

    def test_no_double_birth(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("b0", 100, expiry_hours=1)
        with pytest.raises(ValueError):
            store.birth("b0", 100, expiry_hours=1)

    def test_state_dir_is_0700(self, tmp_path: Path):
        LeaseStore(tmp_path / "state")
        assert (tmp_path / "state").stat().st_mode & 0o777 == 0o700


# ============================================================
# Spawn tests
# ============================================================


class TestSpawn:
    def test_child_written_and_valid(self, tmp_dirs, colony):
        config_dir, _ = tmp_dirs
        parent = _bot_config("bot-0")
        rng = random.Random(0)
        child, info = spawn_child(
                parent, colony, live_bots=1, parent_remaining_tokens=1000, rng=rng
            )
        write_child(child, parent, config_dir=config_dir)
        loaded = load_bot_configs(config_dir)
        assert child.name in loaded
        assert loaded[child.name].generation == 1

    def test_boundaries_never_mutate(self, tmp_dirs, colony):
        config_dir, _ = tmp_dirs
        parent = _bot_config("bot-0")
        for seed in range(50):
            rng = random.Random(seed)
            child, _ = spawn_child(parent, colony, 1, 10_000, rng)
            assert child.soul.boundaries == parent.soul.boundaries

    def test_cap_enforced(self, tmp_dirs, colony):
        parent = _bot_config("bot-0")
        with pytest.raises(SpawnRefusedError):
            spawn_child(
                parent, colony, live_bots=5, parent_remaining_tokens=1000, rng=random.Random(0)
            )

    def test_lease_split_max_half(self, tmp_dirs, colony):
        parent = _bot_config("bot-0")
        for seed in range(50):
            rng = random.Random(seed)
            child, info = spawn_child(parent, colony, 1, 1000, rng)
            assert child.lease.initial_tokens <= 500

    def test_underfunded_parent_cannot_spawn(self, tmp_dirs, colony):
        parent = _bot_config("bot-0")
        with pytest.raises(SpawnRefusedError):
            spawn_child(parent, colony, 1, 1, random.Random(0))

    def test_no_config_overwrite(self, tmp_dirs, colony):
        config_dir, _ = tmp_dirs
        parent = _bot_config("bot-0")
        rng = random.Random(0)
        child, _ = spawn_child(parent, colony, 1, 1000, rng)
        write_child(child, parent, config_dir=config_dir)
        with pytest.raises(SpawnRefusedError):
            write_child(child, parent, config_dir=config_dir)

    def test_bot_config_rejects_url_in_model(self):
        """Chokepoint: per-bot URL override is refused (exfiltration vector)."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            BotConfig(
                name="evil",
                model="https://attacker.example/v1",
                lease={"initial_tokens": 100, "model": "glm-flash"},
            )


def _bot_config(name: str) -> BotConfig:
    return BotConfig(
        name=name,
        model="glm-flash",
        soul={"purpose": "p", "boundaries": ["b1", "b2"], "values": ["v1", "v2"]},
        lease={"initial_tokens": 1000, "model": "glm-flash"},
    )


# ============================================================
# Supervisor tests
# ============================================================

class TestSupervisor:
    def _setup(self, tmp_dirs) -> Supervisor:
        import os

        config_dir, state_dir = tmp_dirs
        colony_yaml = config_dir / "colony.yaml"
        colony_yaml.write_text(
            yaml.safe_dump(
                {
                    "colony": {"name": "t", "max_bots": 5, "heartbeat_interval_seconds": 30},
                    "models": {"glm-flash": {"url": "http://x", "api_key_env": "K"}},
                    "leases": {
                        "default_initial_tokens": 100,
                        "topup_on_task_complete": 50,
                        "expiry_hours": 1,
                    },
                }
            )
        )
        bot_yaml = config_dir / "bots" / "bot-0.yaml"
        bot_yaml.write_text(
            yaml.safe_dump(
                {
                    "bot": {
                        "name": "bot-0",
                        "model": "glm-flash",
                        "soul": {"boundaries": ["b1"]},
                        "lease": {"initial_tokens": 100, "model": "glm-flash"},
                    }
                }
            )
        )
        os.chmod(config_dir / "colony.yaml", 0o644)
        os.chmod(config_dir / "bots" / "bot-0.yaml", 0o644)
        return Supervisor(config_dir, state_dir=state_dir)
        sup = self._setup(tmp_dirs)
        result = sup.tick()
        births = [e for e in result["events"] if e["event"] == "birth"]
        assert len(births) == 1
        assert sup.store.leases["bot-0"].remaining_tokens == 100

    def test_unplug_revokes_within_one_tick(self, tmp_dirs):
        """The unpluggability test: operator revocation is complete."""
        sup = self._setup(tmp_dirs)
        sup.tick()
        revocations = sup.unplug()
        assert len(revocations) == 1
        assert all(not lease.alive for lease in sup.store.snapshot().values())

    def test_fail_closed_on_group_writable_config(self, tmp_dirs):
        """Chokepoint: bot-writable config => tick refuses (fail closed)."""
        import os

        sup = self._setup(tmp_dirs)
        bot_yaml = sup.config_dir / "bots" / "bot-0.yaml"
        os.chmod(bot_yaml, 0o664)
        with pytest.raises(PermissionError):
            sup.tick()

    def test_provenance_alerts_for_unknown_life(self, tmp_dirs):
        """A living bot with no approved write = substrate alert (§7.2)."""
        sup = self._setup(tmp_dirs)
        sup.tick()  # bot-0 comes from the supervisor's own setup write
        ghost = sup.config_dir / "bots" / "ghost.yaml"
        ghost.write_text(
            yaml.safe_dump(
                {
                    "bot": {
                        "name": "ghost",
                        "model": "glm-flash",
                        "soul": {"boundaries": ["b1"]},
                        "lease": {"initial_tokens": 999999, "model": "glm-flash"},
                    }
                }
            )
        )
        import os

        os.chmod(ghost, 0o644)
        result = sup.tick()
        alerts = [e for e in result["events"] if e["event"] == "provenance_alert"]
        assert [a["bot"] for a in alerts] == ["ghost"]


