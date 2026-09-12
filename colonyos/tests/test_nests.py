"""Nest Economy substrate tests (NEST_ECONOMY.md): claims, handshake,
two-gate spawn refusals, endowment buffer, bequest, determinism.

Run: cd colonyos && uv run pytest tests/test_nests.py -q
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

import pytest
import yaml

from colonyos.config import (
    BotConfig,
    ColonyConfig,
    ModelRoute,
    NestClaim,
    SiteConfig,
    load_bot_configs,
)
from colonyos.lease import LeaseStore
from colonyos.nests import (
    ClaimExpiredError,
    ClaimVerifyError,
    NestRegistry,
    verify_handshake,
)
from colonyos.spawn import SpawnRefusedError, spawn_child
from colonyos.supervisor import Supervisor


def _site(tmp_path: Path) -> SiteConfig:
    """A site whose handshake marker (state/ledger.jsonl) exists."""
    root = tmp_path / "site"
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "ledger.jsonl").write_text("")
    return SiteConfig(
        site_id="nest-alpha",
        host="host-0",
        route="glm-flash",
        workspace_root=str(root),
        substrate_version="colonyos-0.1.0",
    )


def _colony(site: SiteConfig, enabled: bool = True) -> ColonyConfig:
    return ColonyConfig(
        models={"glm-flash": ModelRoute(url="http://localhost:8080", api_key_env="K")},
        nests={"enabled": enabled, "sites": [site]},
    )


def _bot(name: str = "bot-0", tokens: int = 1000) -> BotConfig:
    return BotConfig(
        name=name,
        model="glm-flash",
        soul={"purpose": "p", "boundaries": ["b1", "b2"], "values": ["v1", "v2"]},
        lease={"initial_tokens": tokens, "model": "glm-flash"},
    )


def _claim(registry: NestRegistry) -> NestClaim:
    """A valid claim for the fixture site (issued at tick 0, expires at 50)."""
    return registry.issue("nest-alpha", now_tick=0)


# ============================================================
# Claim registry
# ============================================================


class TestNestRegistry:
    def test_issue_expiry_and_live_lookup(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = _claim(registry)
        assert claim.site_id == "nest-alpha"
        assert claim.host == "host-0"
        assert claim.route == "glm-flash"
        assert claim.substrate_version == "colonyos-0.1.0"
        assert claim.expires_at == colony.nests.claim_ttl_ticks
        bot = _bot()
        bot.nest_claims = [claim]
        assert registry.live_claim(bot, now_tick=49) is claim

    def test_expired_claims_raise(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        bot = _bot()
        bot.nest_claims = [_claim(registry)]
        with pytest.raises(ClaimExpiredError):
            registry.live_claim(bot, now_tick=50)

    def test_unknown_site_claim_is_worthless(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = _claim(registry).model_copy(update={"site_id": "ghost-site"})
        bot = _bot()
        bot.nest_claims = [claim]
        assert registry.live_claim(bot, now_tick=0) is None

    def test_issue_unknown_site_refused(self, tmp_path: Path):
        registry = NestRegistry(_colony(_site(tmp_path)).nests)
        with pytest.raises(ValueError):
            registry.issue("ghost-site", now_tick=0)

    def test_consume_is_one_time(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = _claim(registry)
        registry.consume(claim, now_tick=10)
        with pytest.raises(ValueError):
            registry.consume(claim, now_tick=11)
        bot = _bot()
        bot.nest_claims = [claim]
        assert registry.live_claim(bot, now_tick=12) is None  # consumed = spent


# ============================================================
# Handshake (offline stub)
# ============================================================


class TestHandshake:
    def test_pass(self, tmp_path: Path):
        site = _site(tmp_path)
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        assert verify_handshake(claim, site) is True

    def test_bad_substrate_version(self, tmp_path: Path):
        site = _site(tmp_path)
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        forged = claim.model_copy(update={"substrate_version": "rogue-9.9"})
        assert verify_handshake(forged, site) is False
        with pytest.raises(ClaimVerifyError):
            NestRegistry(colony.nests).verify(forged)

    def test_unknown_route(self, tmp_path: Path):
        site = _site(tmp_path)
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        off_route = claim.model_copy(update={"route": "claude-sonnet"})
        assert verify_handshake(off_route, site) is False

    def test_missing_ledger_marker(self, tmp_path: Path):
        site = _site(tmp_path).model_copy(update={"workspace_root": str(tmp_path / "nowhere")})
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        assert verify_handshake(claim, site) is False


# ============================================================
# Spawn gates (nests enabled)
# ============================================================


class TestSpawnGates:
    def _setup(self, tmp_path: Path) -> tuple[ColonyConfig, NestRegistry, BotConfig]:
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        return colony, registry, _bot()

    def test_no_claim_refusal(self, tmp_path: Path):
        colony, _, parent = self._setup(tmp_path)
        with pytest.raises(SpawnRefusedError, match="no nest claim"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 100.0, "now_tick": 0},
            )

    def test_expired_claim_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)  # expires at 50
        with pytest.raises(SpawnRefusedError, match="nest claim invalid"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                nest=claim,
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 100.0, "now_tick": 60},
            )

    def test_handshake_failure_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        forged = registry.issue("nest-alpha", now_tick=0).model_copy(
            update={"substrate_version": "rogue-9.9"}
        )
        with pytest.raises(SpawnRefusedError, match="nest claim invalid"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                nest=forged,
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 100.0, "now_tick": 0},
            )

    def test_no_headroom_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        for headroom in (10, None):  # below min_child_lease=20, and unknown
            with pytest.raises(SpawnRefusedError, match="no route headroom"):
                spawn_child(
                    parent,
                    colony,
                    1,
                    1000,
                    random.Random(0),
                    nest=claim,
                    route_headroom=headroom,
                    ev_input={"ev_optimal_investment": 100.0, "now_tick": 0},
                )

    def test_endowment_floor_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        with pytest.raises(SpawnRefusedError, match="no tokens to spare"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                nest=claim,
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 5.0, "now_tick": 0},
            )

    def test_ev_sized_endowment(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        child, info = spawn_child(
            parent,
            colony,
            1,
            1000,
            random.Random(0),
            nest=claim,
            route_headroom=1000,
            ev_input={"ev_optimal_investment": 200.0, "now_tick": 0},
        )
        assert child.lease.initial_tokens == 200
        assert info["allocation"] == 200
        assert child.nest_site_id == "nest-alpha"  # provenance carried
        assert child.soul.boundaries == parent.soul.boundaries

    def test_inf_ev_sizes_at_cap(self, tmp_path: Path):
        """No history (OffspringHistory returns inf) -> size at max_alloc."""
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        child, _ = spawn_child(
            parent,
            colony,
            1,
            1000,
            random.Random(0),
            nest=claim,
            route_headroom=1000,
            ev_input={"ev_optimal_investment": math.inf, "now_tick": 0},
        )
        assert child.lease.initial_tokens == 500  # max_alloc = 1000 // 2

    def test_legacy_path_unchanged(self, tmp_path: Path):
        """Nests disabled: no claim, no headroom, rng allocation — as today."""
        colony = _colony(_site(tmp_path), enabled=False)
        child, info = spawn_child(_bot(), colony, 1, 1000, random.Random(0))
        assert child.lease.initial_tokens <= 500
        assert child.nest_site_id is None
        assert info["allocation"] == child.lease.initial_tokens


# ============================================================
# Endowment (ledger)
# ============================================================


class TestEndow:
    def test_buffer_refusal_leaves_no_ledger_entry(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 1000, expiry_hours=1)
        entries_before = len(store.entries)
        # post-split 600 at burn 100/cycle = 6 cycles < buffer 10
        assert store.endow("p", "c", 400, buffer_cycles=10, burn_rate=100.0) is False
        assert store.leases["p"].remaining_tokens == 1000
        assert len(store.entries) == entries_before

    def test_transfer_records_endowment_entry(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 1000, expiry_hours=1)
        # post-split 800 at burn 50/cycle = 16 cycles >= buffer 10
        assert store.endow("p", "c", 200, buffer_cycles=10, burn_rate=50.0) is True
        assert store.leases["p"].remaining_tokens == 800
        assert store.entries[-1].kind == "endowment"
        assert store.entries[-1].delta == -200
        assert "c" in (store.entries[-1].note or "")

    def test_profitable_parent_has_unlimited_runway(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 100, expiry_hours=1)
        assert store.endow("p", "c", 50, buffer_cycles=10, burn_rate=0.0) is True

    def test_overdraft_refused(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 100, expiry_hours=1)
        assert store.endow("p", "c", 200, buffer_cycles=10, burn_rate=1.0) is False


# ============================================================
# Bequest (kin-flow)
# ============================================================


class TestBequest:
    def test_claim_transfer_and_ledger_record(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = registry.issue("nest-alpha", now_tick=0)
        dying, heir = _bot("bot-0"), _bot("bot-1")
        dying.nest_claims = [claim]
        moved = registry.bequeath(dying, heir, now_tick=0)
        assert len(moved) == 1
        assert dying.nest_claims == []
        assert heir.nest_claims[0].site_id == "nest-alpha"
        store = LeaseStore(tmp_path / "ledger-state")
        store.birth("bot-0", 100, expiry_hours=1)
        store.bequest("bot-0", "bot-1", "nest-alpha")
        assert store.entries[-1].kind == "bequest"

    def test_expired_claims_not_bequeathed(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = registry.issue("nest-alpha", now_tick=0)  # expires at 50
        dying, heir = _bot("bot-0"), _bot("bot-1")
        dying.nest_claims = [claim]
        assert registry.bequeath(dying, heir, now_tick=60) == []
        assert len(dying.nest_claims) == 1  # kept, not transferred


# ============================================================
# Determinism
# ============================================================


class TestDeterminism:
    def test_same_seed_same_endowment_and_child(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = registry.issue("nest-alpha", now_tick=0)
        ev = {"ev_optimal_investment": 333.0, "now_tick": 0}
        results = [
            spawn_child(
                _bot(),
                colony,
                1,
                1000,
                random.Random(42),
                nest=claim,
                route_headroom=1000,
                ev_input=ev,
            )
            for _ in range(2)
        ]
        assert results[0][0].name == results[1][0].name
        assert results[0][0].lease.initial_tokens == 333
        assert results[1][0].lease.initial_tokens == 333

    def test_same_seed_same_legacy_allocation(self, tmp_path: Path):
        colony = _colony(_site(tmp_path), enabled=False)
        first = spawn_child(_bot(), colony, 1, 1000, random.Random(7))[1]["allocation"]
        second = spawn_child(_bot(), colony, 1, 1000, random.Random(7))[1]["allocation"]
        assert first == second


# ============================================================
# Supervisor gated spawn path
# ============================================================


def _supervisor(tmp_path: Path) -> Supervisor:
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    (config_dir / "bots").mkdir(parents=True, exist_ok=True)
    config_dir.joinpath("colony.yaml").write_text(
        yaml.safe_dump(
            {
                "colony": {"name": "t", "max_bots": 5, "heartbeat_interval_seconds": 30},
                "models": {"glm-flash": {"url": "http://x", "api_key_env": "K"}},
                "leases": {
                    "default_initial_tokens": 100,
                    "topup_on_task_complete": 50,
                    "expiry_hours": 1,
                },
                "nests": {
                    "enabled": True,
                    "claim_ttl_ticks": 50,
                    "sites": [
                        {
                            "site_id": "nest-alpha",
                            "host": "host-0",
                            "route": "glm-flash",
                            "workspace_root": str(tmp_path),
                            "substrate_version": "colonyos-0.1.0",
                        }
                    ],
                },
            }
        )
    )
    for name in ("bot-0", "bot-1"):
        config_dir.joinpath("bots", f"{name}.yaml").write_text(
            yaml.safe_dump(
                {
                    "bot": {
                        "name": name,
                        "model": "glm-flash",
                        "soul": {"boundaries": ["b1"]},
                        "lease": {"initial_tokens": 1000, "model": "glm-flash"},
                    }
                }
            )
        )
    for path in [config_dir / "colony.yaml", *sorted((config_dir / "bots").glob("*.yaml"))]:
        os.chmod(path, 0o644)
    return Supervisor(config_dir, state_dir=state_dir)


class TestSupervisorNestPath:
    def test_grant_claim_and_spawn(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()  # births bot-0 and bot-1 at 1000 tokens; writes the ledger
        claim = sup.grant_claim("bot-0", "nest-alpha")
        assert claim.site_id == "nest-alpha"
        assert len(load_bot_configs(sup.config_dir)["bot-0"].nest_claims) == 1

        event = sup.try_spawn("bot-0", route_headroom=1000, ev_optimal_investment=200.0)
        assert event["event"] == "spawn"
        assert event["site_id"] == "nest-alpha"
        # parent debited by the endowment; claim consumed
        assert sup.store.leases["bot-0"].remaining_tokens == 800
        assert load_bot_configs(sup.config_dir)["bot-0"].nest_claims == []
        # child config written with nest provenance
        bots = load_bot_configs(sup.config_dir)
        child_name = event["bot"]
        assert bots[child_name].nest_site_id == "nest-alpha"
        assert bots[child_name].lease.initial_tokens == 200
        assert sup.provenance[child_name] == "nest:nest-alpha"

    def test_spawn_without_claim_alerts(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()
        event = sup.try_spawn("bot-1", route_headroom=1000, ev_optimal_investment=100.0)
        assert event["event"] == "nest_refusal"
        assert event["reason"] == "no nest claim"
        assert len(load_bot_configs(sup.config_dir)) == 2  # no child written
        lines = (sup.state_dir / "events.jsonl").read_text().strip().split("\n")
        assert any('"nest_refusal"' in line for line in lines)

    def test_endowment_unsafe_alerts(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()
        sup.grant_claim("bot-0", "nest-alpha")
        # endowment 400 -> post-split 600 at burn 100/cycle = 6 < buffer 10
        event = sup.try_spawn(
            "bot-0", route_headroom=1000, ev_optimal_investment=400.0, parent_burn_rate=100.0
        )
        assert event["event"] == "nest_refusal"
        assert "endowment unsafe" in event["reason"]
        assert sup.store.leases["bot-0"].remaining_tokens == 1000  # untouched
        # claim NOT consumed on refusal
        assert len(load_bot_configs(sup.config_dir)["bot-0"].nest_claims) == 1

    def test_bequest_on_reap(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()
        sup.grant_claim("bot-0", "nest-alpha")
        sup.store.leases["bot-0"].expires_at = 0.0  # force wall-clock expiry
        result = sup.tick()
        bequests = [e for e in result["events"] if e["event"] == "bequest"]
        assert len(bequests) == 1
        assert bequests[0]["to"] == "bot-1"
        bots = load_bot_configs(sup.config_dir)
        assert bots["bot-0"].nest_claims == []
        assert bots["bot-1"].nest_claims[0].site_id == "nest-alpha"
        assert sup.store.entries[-1].kind == "bequest"
