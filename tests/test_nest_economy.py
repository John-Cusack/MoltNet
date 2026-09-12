"""Nest Economy bot-side tests: awareness nest gate + OffspringHistory EV.

Run (repo root): uv run pytest tests/test_nest_economy.py -q
"""

from __future__ import annotations

import math

import pytest

from clawdbot.evolution.awareness import AgeAwareness, SelfAwareness
from clawdbot.evolution.reproduction import OffspringHistory


def _aware_parent() -> SelfAwareness:
    """30 mature, profitable, high-performing cycles (legacy-green)."""
    awareness = SelfAwareness(age=AgeAwareness(expected_lifespan=500))
    for i in range(30):
        awareness.record_cycle(
            balance=0.50,
            income=0.02,
            cost=0.001,
            task_type="coding",
            task_success=i < 25,  # ~83% success rate
        )
    return awareness


_BASE_KWARGS = {
    "cycle_count": 30,
    "total_children": 0,
    "min_reproduction_age": 10,
    "safety_margin_cycles": 20,
    "min_success_rate": 0.5,
    "confidence_threshold": 0.4,
}


class TestShouldReproduceNestGate:
    def test_legacy_decision_unchanged_without_nest_args(self):
        should, factors = _aware_parent().should_reproduce(**_BASE_KWARGS)
        assert should is True
        # Nest factors are appended, never replacing legacy keys.
        for key in ("has_live_claim", "route_headroom_ok", "ev_positive", "endowment_safe"):
            assert key in factors
        assert factors["nest_requirements_met"] is True

    def test_no_live_claim_blocks_reproduction(self):
        should, factors = _aware_parent().should_reproduce(
            **_BASE_KWARGS, nests_enabled=True, has_live_claim=False
        )
        assert should is False
        assert factors["nest_requirements_met"] is False

    def test_each_nest_gate_is_load_bearing(self):
        for failing in ("route_headroom_ok", "ev_positive", "endowment_safe"):
            should, factors = _aware_parent().should_reproduce(
                **_BASE_KWARGS, nests_enabled=True, **{failing: False}
            )
            assert should is False, failing
            assert factors["nest_requirements_met"] is False

    def test_all_nest_gates_pass(self):
        should, _ = _aware_parent().should_reproduce(
            **_BASE_KWARGS,
            nests_enabled=True,
            has_live_claim=True,
            route_headroom_ok=True,
            ev_positive=True,
            endowment_safe=True,
        )
        assert should is True


class TestEvOptimalInvestment:
    def test_no_history_returns_inf(self):
        history = OffspringHistory()
        assert history.ev_optimal_investment("glm-flash", "nest-alpha") == math.inf

    def test_unmatched_route_returns_inf(self):
        history = OffspringHistory()
        history.record_birth(
            "child-a",
            birth_cycle=10,
            investment_amount=100.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        assert history.ev_optimal_investment("claude-sonnet", "nest-alpha") == math.inf

    def test_discounted_smoothed_mean(self):
        history = OffspringHistory()
        history.record_birth(
            "child-a",
            birth_cycle=10,
            investment_amount=100.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        history.record_child_update(
            "child-a",
            parent_cycle=30,
            status={"cycle_count": 25, "balance": 150.0},  # revenue/token = 0.5
        )
        history.record_birth(
            "child-b",
            birth_cycle=20,
            investment_amount=200.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        history.record_child_update(
            "child-b",
            parent_cycle=40,
            status={"cycle_count": 30, "balance": 500.0},  # revenue/token = 1.5
        )
        # Newest (child-b, rtp 1.5) weight 1.0; older (child-a, rtp 0.5) weight 0.9;
        # Laplace-smoothed with one pseudo-observation at 0.5.
        expected = ((1.0 * 1.5 + 0.9 * 0.5) + 0.5) / (1.9 + 1.0)
        assert history.ev_optimal_investment("glm-flash", "nest-alpha") == pytest.approx(expected)

    def test_serialization_round_trip_keeps_placement(self):
        history = OffspringHistory()
        history.record_birth(
            "child-a",
            birth_cycle=10,
            investment_amount=100.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        restored = OffspringHistory.from_dict(history.to_dict())
        child = restored.children["child-a"]
        assert child.route == "glm-flash"
        assert child.site_class == "nest-alpha"
