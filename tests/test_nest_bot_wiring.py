"""Nest Economy bot-side wiring tests (NEST_ECONOMY.md §3, clawdbot caller).

Covers: the OpenClawBot reproduction decision consuming the nest gates
(legacy decision untouched when nests are disabled), claim consumption on
spawn, placement provenance for the EV regression, and bequest on death.

Run (repo root): uv run pytest tests/test_nest_bot_wiring.py -q
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from clawdbot.evolution.openclaw_genome import OpenClawGenome
from clawdbot.evolution.reproduction import ReproductiveAssessment
from clawdbot.evolution.selection import DeathCause
from clawdbot.nests import (
    NestLedger,
    NestPolicy,
    NestSite,
    load_nest_policy,
    reset_nest_policy,
)
from clawdbot.openclaw_bot import OpenClawBot

_NEST_KEYS = (
    "has_live_claim",
    "route_headroom_ok",
    "ev_positive",
    "endowment_safe",
    "nest_requirements_met",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_enabled_config(base: Path, **overrides) -> Path:
    nests = {
        "enabled": True,
        "min_child_lease": 20,
        "parent_survival_buffer_cycles": 10,
        "min_offspring_return": 0.0,
        "claim_ttl_ticks": 50,
        "route_limits": {},
        "sites": [
            {"site_id": "nest-alpha", "host": "host-0", "route": "opus", "site_class": "premium"}
        ],
    }
    nests.update(overrides)
    cfg = base / "openclaw_config.yaml"
    cfg.write_text(yaml.safe_dump({"reproduction": {"nests": nests}}))
    return cfg


def _boot_bot(
    base: Path,
    name: str,
    balance: float,
    income: float,
    cost: float,
) -> OpenClawBot:
    """A mature, high-performing bot under a permissive genome.

    `income`/`cost` shape the economic history: profitable bots pass the
    legacy factors with runway to spare; burning bots pass legacy but leave
    no survival buffer after the split.
    """
    genome = OpenClawGenome(
        name=name,
        min_reproduction_age=10,
        safety_margin_cycles=5,
        reproduction_confidence_threshold=0.3,
        min_success_rate_for_reproduction=0.3,
    )
    bot = OpenClawBot(genome=genome, workspace_base=base, initial_balance=balance)
    bot.state.cycle_count = 15
    bot.state.consecutive_failures = 0
    for _ in range(20):
        bot.awareness.record_cycle(
            balance=balance, income=income, cost=cost, task_type="coding", task_success=True
        )
    return bot


def _make_legacy_green(base: Path, name: str = "nest-bot") -> OpenClawBot:
    """Mature, profitable, high-performing bot (legacy-green)."""
    return _boot_bot(base, name=name, balance=1.00, income=0.02, cost=0.001)


def _make_greedy_parent(base: Path, name: str = "greedy-parent") -> OpenClawBot:
    """Legacy-green but burning hard: balance 10, burn 1/cycle.

    Runway 10 > margin 5 passes the legacy factors, but the child split
    (3.5 of 10) leaves post-split runway 6.5 < the 10-cycle nest buffer.
    """
    return _boot_bot(base, name=name, balance=10.00, income=0.0, cost=1.0)


# ---------------------------------------------------------------------------
# Fixtures: policy injection + class-level state isolation
# ---------------------------------------------------------------------------


@pytest.fixture
def nest_env(tmp_path, monkeypatch):
    """Nests enabled via a temp config; isolated class-level state."""
    cfg = _write_enabled_config(tmp_path)
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(cfg))
    reset_nest_policy()
    OpenClawBot._nest_ledger = None
    OpenClawBot._colony.clear()
    yield tmp_path
    reset_nest_policy()
    OpenClawBot._nest_ledger = None
    OpenClawBot._colony.clear()


@pytest.fixture
def legacy_env(monkeypatch):
    """No OPENCLAW_CONFIG_PATH override: repo default (nests disabled)."""
    monkeypatch.delenv("OPENCLAW_CONFIG_PATH", raising=False)
    reset_nest_policy()
    OpenClawBot._nest_ledger = None
    OpenClawBot._colony.clear()
    yield
    reset_nest_policy()
    OpenClawBot._nest_ledger = None
    OpenClawBot._colony.clear()


# ---------------------------------------------------------------------------
# Policy loader
# ---------------------------------------------------------------------------


class TestNestPolicyLoading:
    def test_missing_file_means_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        reset_nest_policy()
        try:
            policy = load_nest_policy()
            assert policy.enabled is False
            assert policy.sites == ()
        finally:
            reset_nest_policy()

    def test_disabled_section_means_disabled(self, tmp_path, monkeypatch):
        cfg = tmp_path / "openclaw_config.yaml"
        cfg.write_text(yaml.safe_dump({"reproduction": {"nests": {"enabled": False}}}))
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(cfg))
        reset_nest_policy()
        try:
            assert load_nest_policy().enabled is False
        finally:
            reset_nest_policy()

    def test_enabled_policy_parsed(self, tmp_path):
        cfg = _write_enabled_config(tmp_path, claim_ttl_ticks=7)
        policy = load_nest_policy(cfg)
        assert policy.enabled is True
        assert policy.claim_ttl_ticks == 7
        assert policy.parent_survival_buffer_cycles == 10
        assert policy.min_offspring_return == 0.0
        assert policy.sites[0].site_id == "nest-alpha"
        assert policy.sites[0].route == "opus"
        assert policy.sites[0].site_class == "premium"
        assert policy.route_limits == {}

    def test_route_limits_parsed(self, tmp_path):
        cfg = _write_enabled_config(tmp_path, route_limits={"opus": 0.5})
        policy = load_nest_policy(cfg)
        assert policy.route_limits == {"opus": 0.5}

    def test_handshake_requires_route_match_and_marker(self, tmp_path):
        from clawdbot.nests import BotNestClaim

        marker_root = tmp_path / "site"
        (marker_root / "state").mkdir(parents=True)
        (marker_root / "state" / "ledger.jsonl").write_text("")
        empty_root = tmp_path / "empty"
        empty_root.mkdir()

        def claim(route: str) -> BotNestClaim:
            return BotNestClaim(
                site_id="a", host="", route=route, site_class=None, expires_cycle=10
            )

        # Route match + ledger marker present -> verified
        verified = NestPolicy(
            enabled=True,
            sites=(NestSite(site_id="a", route="opus", workspace_root=str(marker_root)),),
        )
        assert verified.handshake_ok(claim("opus")) is True
        # Route mismatch -> refused
        assert verified.handshake_ok(claim("sonnet")) is False
        # Missing ledger marker -> refused
        missing = NestPolicy(
            enabled=True,
            sites=(NestSite(site_id="a", route="opus", workspace_root=str(empty_root)),),
        )
        assert missing.handshake_ok(claim("opus")) is False
        # No workspace_root configured -> no marker check
        open_site = NestPolicy(enabled=True, sites=(NestSite(site_id="a", route="opus"),))
        assert open_site.handshake_ok(claim("opus")) is True


# ---------------------------------------------------------------------------
# NestLedger lifecycle
# ---------------------------------------------------------------------------


class TestNestLedger:
    def _policy(self, **kw) -> NestPolicy:
        site = NestSite(site_id="nest-alpha", route="opus", site_class="premium")
        return NestPolicy(enabled=True, sites=(site,), **kw)

    def test_issue_live_consume(self):
        ledger = NestLedger(self._policy(claim_ttl_ticks=50))
        claim = ledger.issue("parent", "nest-alpha", now_cycle=10)
        assert claim.route == "opus"
        assert claim.expires_cycle == 60
        assert ledger.live_claim("parent", now_cycle=20) is claim
        ledger.consume("parent", claim, now_cycle=20)
        assert ledger.live_claim("parent", now_cycle=20) is None

    def test_consume_is_one_time(self):
        ledger = NestLedger(self._policy())
        claim = ledger.issue("p", "nest-alpha", 0)
        ledger.consume("p", claim, 1)
        with pytest.raises(ValueError, match="already consumed"):
            ledger.consume("p", claim, 1)

    def test_expiry_drops_claim(self):
        ledger = NestLedger(self._policy(claim_ttl_ticks=50))
        ledger.issue("p", "nest-alpha", 0)
        assert ledger.live_claim("p", now_cycle=60) is None
        assert ledger.live_claim("p", now_cycle=10) is None  # dropped from store

    def test_unknown_site_refused(self):
        ledger = NestLedger(self._policy())
        with pytest.raises(ValueError, match="unknown nest site"):
            ledger.issue("p", "no-such-site", 0)

    def test_bequest_moves_live_claims(self):
        ledger = NestLedger(self._policy(claim_ttl_ticks=50))
        claim = ledger.issue("dying", "nest-alpha", 0)
        moved = ledger.bequeath("dying", "heir", now_cycle=10)
        assert moved == [claim]
        assert ledger.live_claim("heir", 10) is claim
        assert ledger.live_claim("dying", 10) is None

    def test_bequest_skips_expired(self):
        ledger = NestLedger(self._policy(claim_ttl_ticks=50))
        ledger.issue("dying", "nest-alpha", 0)
        assert ledger.bequeath("dying", "heir", now_cycle=100) == []


# ---------------------------------------------------------------------------
# Decision wiring
# ---------------------------------------------------------------------------


class TestDecisionWiring:
    def test_legacy_decision_unchanged_nests_disabled(self, legacy_env, tmp_path):
        bot = _make_legacy_green(tmp_path)
        assessment = bot._assess_reproduction_readiness()
        assert assessment.should_reproduce is True
        for key in _NEST_KEYS:
            assert key not in assessment.factors

    def test_no_claim_blocks_reproduction(self, nest_env):
        bot = _make_legacy_green(nest_env)
        assessment = bot._assess_reproduction_readiness()
        assert assessment.should_reproduce is False
        assert assessment.factors["has_live_claim"] is False
        assert assessment.factors["nest_requirements_met"] is False
        assert any("nest" in r.lower() for r in assessment.reasons)

    def test_all_gates_pass_with_live_claim(self, nest_env):
        bot = _make_legacy_green(nest_env)
        OpenClawBot._nest_ledger.issue(bot.name, "nest-alpha", now_cycle=bot.state.cycle_count)
        assessment = bot._assess_reproduction_readiness()
        assert assessment.factors["has_live_claim"] is True
        assert assessment.factors["route_headroom_ok"] is True
        assert assessment.factors["ev_positive"] is True
        assert assessment.factors["endowment_safe"] is True
        assert assessment.factors["nest_requirements_met"] is True
        assert assessment.should_reproduce is True
        assert assessment.factors["nest_site_id"] == "nest-alpha"

    def test_expired_claim_blocks_reproduction(self, nest_env):
        bot = _make_legacy_green(nest_env)
        OpenClawBot._nest_ledger.issue(bot.name, "nest-alpha", now_cycle=0)  # ttl 50
        bot.state.cycle_count = 60
        assessment = bot._assess_reproduction_readiness()
        assert assessment.should_reproduce is False
        assert assessment.factors["has_live_claim"] is False

    def test_route_mismatch_blocks_reproduction(self, nest_env):
        # Site pinned to a different route than the bot resolves: handshake fails
        _write_enabled_config(
            nest_env,
            sites=[
                {"site_id": "nest-alpha", "host": "h", "route": "sonnet", "site_class": "premium"}
            ],
        )
        reset_nest_policy()
        try:
            bot = _make_legacy_green(nest_env)
            OpenClawBot._nest_ledger.issue(bot.name, "nest-alpha", now_cycle=bot.state.cycle_count)
            assessment = bot._assess_reproduction_readiness()
            assert assessment.factors["has_live_claim"] is False
            assert any("serves route 'sonnet'" in r for r in assessment.reasons)
        finally:
            reset_nest_policy()
            OpenClawBot._nest_ledger = None

    def test_no_route_headroom_blocks_reproduction(self, nest_env):
        _write_enabled_config(nest_env, route_limits={"opus": 0.0005})
        reset_nest_policy()
        try:
            bot = _make_legacy_green(nest_env)
            OpenClawBot._nest_ledger.issue(bot.name, "nest-alpha", now_cycle=bot.state.cycle_count)
            assessment = bot._assess_reproduction_readiness()
            assert assessment.factors["route_headroom_ok"] is False
            assert any("headroom" in r for r in assessment.reasons)
        finally:
            reset_nest_policy()
            OpenClawBot._nest_ledger = None

    def test_negative_ev_blocks_reproduction(self, nest_env):
        bot = _make_legacy_green(nest_env)
        OpenClawBot._nest_ledger.issue(bot.name, "nest-alpha", now_cycle=bot.state.cycle_count)
        # A prior child at this (route, site_class) burned its whole endowment:
        # per-dollar return floors to 0, Laplace-smoothed to 0.25 < 1.0.
        bot.offspring_history.record_birth(
            child_name="child-x",
            birth_cycle=0,
            investment_amount=1.0,
            route="opus",
            site_class="premium",
        )
        bot.offspring_history.record_child_death(
            "child-x", "bankruptcy", final_stats={"cycle_count": 5, "balance": 0.0}
        )
        assessment = bot._assess_reproduction_readiness()
        assert assessment.factors["ev_positive"] is False
        assert any("expected value" in r for r in assessment.reasons)

    def test_unsafe_endowment_blocks_reproduction(self, nest_env):
        bot = _make_greedy_parent(nest_env)
        OpenClawBot._nest_ledger.issue(bot.name, "nest-alpha", now_cycle=bot.state.cycle_count)
        assessment = bot._assess_reproduction_readiness()
        # The legacy leg passes (runway 10 > margin 5); Gate 2b refuses.
        assert assessment.factors["endowment_safe"] is False
        assert any("endowment unsafe" in r for r in assessment.reasons)


# ---------------------------------------------------------------------------
# Spawn and bequest
# ---------------------------------------------------------------------------


class TestSpawnAndBequest:
    @pytest.mark.asyncio
    async def test_replicate_refuses_without_claim(self, nest_env):
        bot = _make_legacy_green(nest_env)
        with patch.object(OpenClawBot, "run", new_callable=AsyncMock):
            assessment = bot._assess_reproduction_readiness()
            assert assessment.should_reproduce is False  # Gate 1 blocks
            child = await bot._replicate(
                ReproductiveAssessment.yes(
                    confidence=0.9, investment=0.1, urgency=0.0, reasons=["test"]
                )
            )
        assert child is None
        assert bot.state.wallet_balance == 1.00  # no cost moved
        assert bot.state.children_spawned == 0

    @pytest.mark.asyncio
    async def test_replicate_consumes_claim_and_records_provenance(self, nest_env):
        bot = _make_legacy_green(nest_env)
        OpenClawBot._nest_ledger.issue(bot.name, "nest-alpha", now_cycle=bot.state.cycle_count)
        with patch.object(OpenClawBot, "run", new_callable=AsyncMock):
            assessment = bot._assess_reproduction_readiness()
            assert assessment.should_reproduce is True
            child = await bot._replicate(assessment)
        assert child is not None
        # Claim debited on use
        assert OpenClawBot._nest_ledger.live_claim(bot.name, bot.state.cycle_count) is None
        # Placement provenance recorded for the EV regression
        record = bot.offspring_history.children[child.name]
        assert record.route == "opus"
        assert record.site_class == "premium"
        # The child holds no claim (claims are consumed, not inherited)
        assert OpenClawBot._nest_ledger.live_claim(child.name, child.state.cycle_count) is None

    @pytest.mark.asyncio
    async def test_death_bequeaths_claims_to_living_child(self, nest_env):
        parent = _make_legacy_green(nest_env, name="dying-parent")
        heir = _make_legacy_green(nest_env, name="heir-child")
        parent._children.append(heir.name)
        OpenClawBot._nest_ledger.issue(
            parent.name, "nest-alpha", now_cycle=parent.state.cycle_count
        )
        parent._die(DeathCause.BANKRUPTCY, {})
        await asyncio.sleep(0)
        assert OpenClawBot._nest_ledger.live_claim(heir.name, heir.state.cycle_count) is not None
        assert OpenClawBot._nest_ledger.live_claim(parent.name, parent.state.cycle_count) is None
        await parent.close()
        await heir.close()
