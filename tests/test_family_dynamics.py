"""Integration tests for family dynamics and reproductive behavior."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from clawdbot.evolution.openclaw_genome import OpenClawGenome
from clawdbot.evolution.awareness import SelfAwareness, AgeAwareness
from clawdbot.evolution.reproduction import (
    OffspringHistory,
    ReproductiveAssessment,
    NurturingTracker,
)
from clawdbot.evolution.kinship import (
    FamilyNetwork,
    KinCooperation,
    FamilyMemberStatus,
    FamilyMessage,
    RELATEDNESS_PARENT_CHILD,
)


class TestParentChildFeedbackLoop:
    """Test the feedback loop where parent learns from offspring outcomes."""

    def test_parent_learns_from_dying_children(self):
        """Parent should increase investment after children die young."""
        history = OffspringHistory()

        # Initial children with low investment all die
        for i in range(3):
            history.record_birth(f"child-{i}", birth_cycle=i * 10, investment_amount=0.10)
            history.record_child_death(f"child-{i}", cause="bankruptcy", final_stats={
                "cycle_count": 5,
                "balance": 0.0,
            })

        # Parent should learn to invest more
        assert history.should_increase_investment() is True
        adjustment = history.get_recommended_investment_adjustment()
        assert adjustment > 1.2  # At least 20% more

    def test_parent_maintains_strategy_with_successful_children(self):
        """Parent should maintain strategy when children succeed."""
        history = OffspringHistory()

        # Children survive to maturity
        for i in range(3):
            history.record_birth(f"child-{i}", birth_cycle=i * 10, investment_amount=0.20)
            history.record_child_update(f"child-{i}", parent_cycle=50, status={
                "cycle_count": 30,  # Past maturity
                "balance": 0.25,
                "children_count": 0,
            })

        # Parent should not drastically change strategy
        adjustment = history.get_recommended_investment_adjustment()
        assert 0.9 <= adjustment <= 1.1  # Within 10% of current

    def test_grandchildren_indicate_ultimate_success(self):
        """Having grandchildren is the ultimate success signal."""
        history = OffspringHistory()

        history.record_birth("child-1", birth_cycle=10, investment_amount=0.20)

        # Child reports having children of its own
        history.record_child_update("child-1", parent_cycle=100, status={
            "cycle_count": 80,
            "balance": 0.30,
            "children_count": 2,
        })

        assert history.grandchildren_count == 2
        assert history.children["child-1"].was_successful is True


class TestParentHelpingStrugglingChild:
    """Test parent helping struggling children via Hamilton's rule."""

    def test_parent_sends_resources_to_struggling_child(self):
        """Parent should help child when Hamilton's rule is satisfied."""
        coop = KinCooperation(kin_helping_threshold=0.1)
        family = FamilyNetwork()

        # Add a struggling child
        family.add_child("struggling-child")
        family.children["struggling-child"].last_known_balance = 0.02

        # Check if parent should help
        decisions = coop.check_family_needs(
            helper_balance=0.50,
            helper_min_balance=0.15,
            family=family,
            risk_threshold=0.05,
        )

        assert len(decisions) == 1
        child_name, decision = decisions[0]
        assert child_name == "struggling-child"
        assert decision.should_help is True
        assert decision.amount > 0.01

    def test_parent_prioritizes_neediest_child(self):
        """Parent should help neediest child first."""
        coop = KinCooperation(kin_helping_threshold=0.1)
        family = FamilyNetwork()

        # Add children with different need levels
        family.add_child("very-poor")
        family.children["very-poor"].last_known_balance = 0.01

        family.add_child("somewhat-poor")
        family.children["somewhat-poor"].last_known_balance = 0.03

        family.add_child("doing-ok")
        family.children["doing-ok"].last_known_balance = 0.10

        decisions = coop.check_family_needs(
            helper_balance=0.50,
            helper_min_balance=0.15,
            family=family,
            risk_threshold=0.05,
        )

        # Should help very-poor and somewhat-poor but not doing-ok
        helped_names = [name for name, _ in decisions]
        assert "very-poor" in helped_names
        assert "somewhat-poor" in helped_names
        assert "doing-ok" not in helped_names

    def test_parent_wont_help_if_no_surplus(self):
        """Parent shouldn't help if it would endanger their own survival."""
        coop = KinCooperation(kin_helping_threshold=0.1)
        family = FamilyNetwork()

        family.add_child("struggling-child")
        family.children["struggling-child"].last_known_balance = 0.02

        # Parent has no surplus
        decisions = coop.check_family_needs(
            helper_balance=0.10,
            helper_min_balance=0.15,  # No surplus
            family=family,
            risk_threshold=0.05,
        )

        assert len(decisions) == 0


class TestSiblingAwareness:
    """Test sibling awareness and introduction."""

    def test_siblings_are_introduced(self):
        """Parent introduces siblings to each other."""
        family = FamilyNetwork()

        # First child
        family.add_child("child-1")

        # Second child - should get sibling intro
        siblings_for_child_2 = family.introduce_siblings_to_child("child-2")
        family.add_child("child-2")

        assert "child-1" in siblings_for_child_2

        # Third child - should know both siblings
        siblings_for_child_3 = family.introduce_siblings_to_child("child-3")
        family.add_child("child-3")

        assert "child-1" in siblings_for_child_3
        assert "child-2" in siblings_for_child_3

    def test_dead_siblings_not_introduced(self):
        """Dead siblings shouldn't be introduced."""
        family = FamilyNetwork()

        family.add_child("alive-sibling")
        family.add_child("dead-sibling")
        family.children["dead-sibling"].is_alive = False

        siblings_for_new_child = family.introduce_siblings_to_child("new-child")

        assert "alive-sibling" in siblings_for_new_child
        assert "dead-sibling" not in siblings_for_new_child


class TestRKStrategies:
    """Test that r/K strategies emerge from genome traits."""

    def test_r_strategy_traits(self):
        """Test r-strategy: many cheap offspring, quick reproduction."""
        # r-strategy genome
        r_genome = OpenClawGenome(
            name="r-strategist",
            offspring_investment_ratio=0.2,  # Low investment per child
            safety_margin_cycles=5,           # Quick to reproduce
            min_success_rate_for_reproduction=0.3,  # Low bar
            min_reproduction_age=5,           # Early maturity
            nurturing_cycles=1,               # Short nurturing
        )

        # Should reproduce quickly with lower investment
        assert r_genome.offspring_investment_ratio < 0.3
        assert r_genome.safety_margin_cycles < 10
        assert r_genome.nurturing_cycles < 2

    def test_k_strategy_traits(self):
        """Test K-strategy: few expensive offspring, careful reproduction."""
        # K-strategy genome
        k_genome = OpenClawGenome(
            name="k-strategist",
            offspring_investment_ratio=0.5,  # High investment per child
            safety_margin_cycles=40,          # Wait for stability
            min_success_rate_for_reproduction=0.7,  # High bar
            min_reproduction_age=20,          # Late maturity
            nurturing_cycles=5,               # Long nurturing
        )

        # Should reproduce carefully with higher investment
        assert k_genome.offspring_investment_ratio > 0.4
        assert k_genome.safety_margin_cycles > 30
        assert k_genome.nurturing_cycles > 3


class TestBehavioralScenarios:
    """Test specific behavioral scenarios from the design doc."""

    def test_scenario_a_dying_children_increase_investment(self):
        """Scenario A: Bot with many dying children should increase investment."""
        history = OffspringHistory()

        # Many children die young due to insufficient investment
        for i in range(5):
            history.record_birth(f"child-{i}", birth_cycle=i * 10, investment_amount=0.12)
            history.record_child_death(f"child-{i}", cause="bankruptcy", final_stats={
                "cycle_count": 8,  # Died before maturity
                "balance": 0.0,
            })

        # Bot should learn to invest more
        assert history.early_deaths == 5
        assert history.should_increase_investment() is True

        # Recommended adjustment should be significant
        adjustment = history.get_recommended_investment_adjustment()
        assert adjustment >= 1.3  # At least 30% more

    def test_scenario_b_successful_children_maintain_strategy(self):
        """Scenario B: Bot with successful children should maintain strategy."""
        history = OffspringHistory()

        # Children survive and thrive
        for i in range(3):
            history.record_birth(f"child-{i}", birth_cycle=i * 20, investment_amount=0.20)
            # Children survived past maturity
            history.record_child_update(f"child-{i}", parent_cycle=100, status={
                "cycle_count": 50,
                "balance": 0.30,
                "children_count": 1,  # Had grandchildren
            })

        assert history.survival_rate == 1.0
        assert history.grandchildren_count == 3

        # No need to change strategy
        adjustment = history.get_recommended_investment_adjustment()
        assert 0.95 <= adjustment <= 1.05

    def test_scenario_c_struggling_child_receives_help(self):
        """Scenario C: Struggling child should receive help from parent."""
        coop = KinCooperation(kin_helping_threshold=0.1)
        family = FamilyNetwork()

        # Child is struggling
        family.add_child("struggling")
        family.children["struggling"].last_known_balance = 0.02
        family.children["struggling"].last_known_cycle = 15

        # Parent has resources to share
        decision = coop.evaluate_child_help(
            helper_balance=0.40,
            helper_min_balance=0.15,
            child=family.children["struggling"],
            risk_threshold=0.05,
        )

        assert decision.should_help is True
        assert decision.amount >= 0.01

    def test_scenario_d_old_bot_without_children_feels_urgency(self):
        """Scenario D: Old bot without children should feel reproduction urgency."""
        age = AgeAwareness(expected_lifespan=100)

        # Old bot (75% of lifespan) with no children
        urgency = age.get_reproduction_urgency(cycle_count=75, total_children=0)

        # Should feel high urgency
        assert urgency > 0.8

        # Compare to bot with children
        urgency_with_kids = age.get_reproduction_urgency(cycle_count=75, total_children=2)
        assert urgency_with_kids < urgency


class TestNurturingBehavior:
    """Test nurturing period behavior."""

    def test_nurturing_prevents_reproduction(self):
        """Bot cannot reproduce while nurturing."""
        tracker = NurturingTracker()
        tracker.start_nurturing("child-1", nurturing_cycles=3, efficiency=0.5)

        assert tracker.can_reproduce is False

    def test_nurturing_reduces_efficiency(self):
        """Bot operates at reduced efficiency during nurturing."""
        tracker = NurturingTracker()
        tracker.start_nurturing("child-1", nurturing_cycles=3, efficiency=0.5)

        assert tracker.efficiency == 0.5

    def test_nurturing_completes_after_cycles(self):
        """Nurturing ends after specified cycles."""
        tracker = NurturingTracker()
        tracker.start_nurturing("child-1", nurturing_cycles=3, efficiency=0.5)

        # Tick through nurturing
        for _ in range(2):
            assert tracker.tick() is False  # Not done yet

        assert tracker.tick() is True  # Done!
        tracker.complete_nurturing()

        assert tracker.is_nurturing is False
        assert tracker.can_reproduce is True


class TestFamilyMessaging:
    """Test family message creation and handling."""

    def test_status_update_message(self):
        """Test creating status update message."""
        msg = FamilyMessage.status_update(
            from_name="child-1",
            to_name="parent",
            cycle_count=25,
            balance=0.30,
            children_count=1,
        )

        assert msg.message_type == "status_update"
        assert msg.from_name == "child-1"
        assert msg.data["cycle_count"] == 25

    def test_death_notification_message(self):
        """Test creating death notification."""
        msg = FamilyMessage.death_notification(
            deceased_name="child-1",
            to_name="parent",
            cause="bankruptcy",
            final_stats={"cycle_count": 15, "balance": 0.0},
        )

        assert msg.message_type == "death_notification"
        assert msg.data["cause"] == "bankruptcy"

    def test_resource_transfer_message(self):
        """Test creating resource transfer message."""
        msg = FamilyMessage.resource_transfer(
            from_name="parent",
            to_name="child-1",
            amount=0.05,
            reason="child_struggling",
        )

        assert msg.message_type == "resource_transfer"
        assert msg.data["amount"] == 0.05
        assert msg.data["reason"] == "child_struggling"

    def test_sibling_introduction_message(self):
        """Test creating sibling introduction."""
        msg = FamilyMessage.sibling_introduction(
            from_name="parent",
            to_name="child-2",
            sibling_name="child-1",
        )

        assert msg.message_type == "sibling_introduction"
        assert msg.data["sibling_name"] == "child-1"


class TestExperienceBasedDecisions:
    """Test that decisions are based on experience, not global knowledge."""

    def test_bot_uses_own_stats_only(self):
        """Bot decisions should be based on self-knowledge only."""
        awareness = SelfAwareness(
            age=AgeAwareness(expected_lifespan=500),
        )

        # Build up experience
        for i in range(30):
            awareness.record_cycle(
                balance=0.40,
                income=0.015,
                cost=0.001,
                task_type="coding",
                task_success=i < 24,  # 80% success
            )

        # Get assessment - should use own stats
        assessment = awareness.get_full_assessment(cycle_count=30, total_children=0)

        # Verify it's using self-knowledge
        assert assessment["economic"]["history_length"] == 30
        assert assessment["performance"]["tasks_attempted"] == 30
        assert assessment["age"]["cycle_count"] == 30

    def test_offspring_feedback_loop(self):
        """Offspring outcomes should influence future reproductive decisions."""
        history = OffspringHistory()

        # First generation: low investment, high mortality
        for i in range(3):
            history.record_birth(f"gen1-child-{i}", birth_cycle=i * 10, investment_amount=0.12)
            history.record_child_death(f"gen1-child-{i}", cause="bankruptcy", final_stats={
                "cycle_count": 7,
                "balance": 0.0,
            })

        initial_adjustment = history.get_recommended_investment_adjustment()

        # Second generation: higher investment, better survival
        for i in range(3):
            history.record_birth(f"gen2-child-{i}", birth_cycle=50 + i * 10, investment_amount=0.22)
            history.record_child_update(f"gen2-child-{i}", parent_cycle=100, status={
                "cycle_count": 30,
                "balance": 0.25,
            })

        final_adjustment = history.get_recommended_investment_adjustment()

        # After better outcomes, should need less adjustment
        assert final_adjustment < initial_adjustment
