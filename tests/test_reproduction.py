"""Tests for the reproduction and awareness modules."""

import pytest
from clawdbot.evolution.awareness import (
    EconomicAwareness,
    PerformanceAwareness,
    AgeAwareness,
    SelfAwareness,
)
from clawdbot.evolution.reproduction import (
    OffspringHistory,
    ChildOutcome,
    ChildStatus,
    ReproductiveAssessment,
    NurturingTracker,
    NurturingState,
)
from clawdbot.evolution.kinship import (
    FamilyNetwork,
    KinCooperation,
    FamilyMemberStatus,
    HelpDecision,
    RELATEDNESS_PARENT_CHILD,
)


class TestEconomicAwareness:
    """Tests for EconomicAwareness class."""

    def test_initial_state(self):
        """Test initial state is empty."""
        econ = EconomicAwareness()
        assert econ.current_balance == 0.0
        assert len(econ.balance_history) == 0

    def test_record_cycle(self):
        """Test recording cycle data."""
        econ = EconomicAwareness()
        econ.record_cycle(balance=0.50, income=0.02, cost=0.001)

        assert econ.current_balance == 0.50
        assert len(econ.balance_history) == 1
        assert econ.income_history[0] == 0.02
        assert econ.cost_history[0] == 0.001

    def test_avg_cost_per_cycle(self):
        """Test average cost calculation."""
        econ = EconomicAwareness()

        # Record several cycles
        for i in range(10):
            econ.record_cycle(balance=0.50, income=0.02, cost=0.001)

        assert econ.avg_cost_per_cycle == pytest.approx(0.001)

    def test_avg_income_per_cycle(self):
        """Test average income calculation."""
        econ = EconomicAwareness()

        for i in range(10):
            econ.record_cycle(balance=0.50, income=0.02, cost=0.001)

        assert econ.avg_income_per_cycle == pytest.approx(0.02)

    def test_runway_cycles_profitable(self):
        """Test runway is infinite when profitable."""
        econ = EconomicAwareness()
        econ.current_balance = 0.50

        # Income > cost = profitable
        for i in range(10):
            econ.record_cycle(balance=0.50, income=0.02, cost=0.001)

        assert econ.is_profitable is True
        assert econ.runway_cycles == float('inf')

    def test_runway_cycles_burning(self):
        """Test runway calculation when losing money."""
        econ = EconomicAwareness()
        econ.current_balance = 0.10

        # Cost > income = burning money
        for i in range(10):
            econ.record_cycle(balance=0.10, income=0.001, cost=0.01)

        assert econ.is_profitable is False
        # Net burn = 0.01 - 0.001 = 0.009 per cycle
        # Runway = 0.10 / 0.009 = ~11 cycles
        assert econ.runway_cycles == pytest.approx(11.11, rel=0.1)

    def test_trend_improving(self):
        """Test trend detection when improving."""
        econ = EconomicAwareness()

        # Record declining then improving balances
        for i in range(5):
            econ.record_cycle(balance=0.10, income=0.01, cost=0.01)
        for i in range(5):
            econ.record_cycle(balance=0.20, income=0.01, cost=0.01)

        assert econ.trend == "improving"

    def test_trend_declining(self):
        """Test trend detection when declining."""
        econ = EconomicAwareness()

        for i in range(5):
            econ.record_cycle(balance=0.20, income=0.01, cost=0.01)
        for i in range(5):
            econ.record_cycle(balance=0.10, income=0.01, cost=0.01)

        assert econ.trend == "declining"

    def test_serialization(self):
        """Test to_dict and from_dict."""
        econ = EconomicAwareness()
        for i in range(5):
            econ.record_cycle(balance=0.50, income=0.02, cost=0.001)

        data = econ.to_dict()
        restored = EconomicAwareness.from_dict(data)

        assert restored.current_balance == econ.current_balance
        assert len(restored.balance_history) == len(econ.balance_history)


class TestPerformanceAwareness:
    """Tests for PerformanceAwareness class."""

    def test_initial_state(self):
        """Test initial state."""
        perf = PerformanceAwareness()
        assert perf.recent_success_rate == 0.5  # Neutral prior

    def test_record_task(self):
        """Test recording task outcomes."""
        perf = PerformanceAwareness()
        perf.record_task("coding", True)
        perf.record_task("coding", False)

        assert len(perf.task_outcomes) == 2

    def test_recent_success_rate(self):
        """Test success rate calculation."""
        perf = PerformanceAwareness()

        for i in range(10):
            perf.record_task("coding", i < 7)  # 7 successes, 3 failures

        assert perf.recent_success_rate == pytest.approx(0.7)

    def test_consecutive_failures(self):
        """Test consecutive failure counting."""
        perf = PerformanceAwareness()
        perf.record_task("coding", True)
        perf.record_task("coding", False)
        perf.record_task("coding", False)
        perf.record_task("coding", False)

        assert perf.consecutive_failures == 3

    def test_consecutive_successes(self):
        """Test consecutive success counting."""
        perf = PerformanceAwareness()
        perf.record_task("coding", False)
        perf.record_task("coding", True)
        perf.record_task("coding", True)

        assert perf.consecutive_successes == 2

    def test_best_task_type(self):
        """Test finding best task type."""
        perf = PerformanceAwareness()

        # Coding: 80% success
        for i in range(10):
            perf.record_task("coding", i < 8)

        # Reasoning: 40% success
        for i in range(10):
            perf.record_task("reasoning", i < 4)

        assert perf.get_best_task_type() == "coding"
        assert perf.get_worst_task_type() == "reasoning"


class TestAgeAwareness:
    """Tests for AgeAwareness class."""

    def test_life_stages(self):
        """Test life stage progression."""
        age = AgeAwareness(expected_lifespan=100)

        assert age.get_life_stage(5) == "juvenile"  # 5%
        assert age.get_life_stage(25) == "prime"     # 25%
        assert age.get_life_stage(60) == "mature"    # 60%
        assert age.get_life_stage(90) == "elder"     # 90%

    def test_mortality_anxiety(self):
        """Test mortality anxiety increases with age."""
        age = AgeAwareness(expected_lifespan=100)

        assert age.get_mortality_anxiety(40) == 0.0   # < 50%, no anxiety
        assert age.get_mortality_anxiety(75) == pytest.approx(0.5)  # 75% = 50% anxiety
        assert age.get_mortality_anxiety(100) == pytest.approx(1.0)  # 100% = max anxiety

    def test_reproduction_urgency(self):
        """Test reproduction urgency for childless elder."""
        age = AgeAwareness(expected_lifespan=100)

        # Young with no children - low urgency
        urgency_young = age.get_reproduction_urgency(20, 0)
        assert urgency_young < 0.3

        # Old with no children - high urgency
        urgency_old = age.get_reproduction_urgency(80, 0)
        assert urgency_old > 0.8

        # Old with children - lower urgency
        urgency_old_with_kids = age.get_reproduction_urgency(80, 2)
        assert urgency_old_with_kids < urgency_old


class TestOffspringHistory:
    """Tests for OffspringHistory class."""

    def test_record_birth(self):
        """Test recording a birth."""
        history = OffspringHistory()
        history.record_birth("child-1", birth_cycle=10, investment_amount=0.15)

        assert history.total_children == 1
        assert history.living_children == 1
        assert "child-1" in history.children

    def test_record_child_death(self):
        """Test recording child death."""
        history = OffspringHistory()
        history.record_birth("child-1", birth_cycle=10, investment_amount=0.15)

        # Child dies young (< 20 cycles)
        history.record_child_death(
            "child-1",
            cause="bankruptcy",
            final_stats={"cycle_count": 5, "balance": 0.0},
        )

        assert history.living_children == 0
        assert history.dead_children == 1
        assert history.early_deaths == 1
        assert history.survival_rate == 0.0

    def test_survival_rate(self):
        """Test survival rate calculation."""
        history = OffspringHistory()

        # Child 1 survives to maturity
        history.record_birth("child-1", birth_cycle=10, investment_amount=0.20)
        history.record_child_update("child-1", parent_cycle=50, status={
            "cycle_count": 30,
            "balance": 0.25,
        })

        # Child 2 dies young
        history.record_birth("child-2", birth_cycle=20, investment_amount=0.10)
        history.record_child_death("child-2", cause="bankruptcy", final_stats={
            "cycle_count": 8,
            "balance": 0.0,
        })

        # 1 survivor / 2 total = 50%
        assert history.survival_rate == pytest.approx(0.5)

    def test_investment_adjustment(self):
        """Test investment adjustment based on outcomes."""
        history = OffspringHistory()

        # Multiple children die young - should recommend increasing investment
        for i in range(3):
            history.record_birth(f"child-{i}", birth_cycle=i * 10, investment_amount=0.10)
            history.record_child_death(f"child-{i}", cause="bankruptcy", final_stats={
                "cycle_count": 5,
                "balance": 0.0,
            })

        assert history.should_increase_investment() is True
        assert history.get_recommended_investment_adjustment() > 1.0

    def test_grandchildren_count(self):
        """Test grandchildren counting."""
        history = OffspringHistory()
        history.record_birth("child-1", birth_cycle=10, investment_amount=0.20)

        # Child reports having children
        history.record_child_update("child-1", parent_cycle=50, status={
            "cycle_count": 30,
            "balance": 0.25,
            "children_count": 2,
        })

        assert history.grandchildren_count == 2


class TestNurturingTracker:
    """Tests for NurturingTracker class."""

    def test_initial_state(self):
        """Test initial state is not nurturing."""
        tracker = NurturingTracker()
        assert tracker.is_nurturing is False
        assert tracker.can_reproduce is True

    def test_start_nurturing(self):
        """Test starting nurturing period."""
        tracker = NurturingTracker()
        tracker.start_nurturing("child-1", nurturing_cycles=3, efficiency=0.5)

        assert tracker.is_nurturing is True
        assert tracker.can_reproduce is False
        assert tracker.cycles_remaining == 3
        assert tracker.child_name == "child-1"

    def test_tick_during_nurturing(self):
        """Test advancing nurturing cycles."""
        tracker = NurturingTracker()
        tracker.start_nurturing("child-1", nurturing_cycles=3, efficiency=0.5)

        # First tick
        complete = tracker.tick()
        assert complete is False
        assert tracker.cycles_remaining == 2

        # Second tick
        complete = tracker.tick()
        assert complete is False
        assert tracker.cycles_remaining == 1

        # Third tick - complete
        complete = tracker.tick()
        assert complete is True
        assert tracker.state == NurturingState.COMPLETE

    def test_complete_nurturing(self):
        """Test completing nurturing period."""
        tracker = NurturingTracker()
        tracker.start_nurturing("child-1", nurturing_cycles=1, efficiency=0.5)
        tracker.tick()
        tracker.complete_nurturing()

        assert tracker.is_nurturing is False
        assert tracker.can_reproduce is True
        assert tracker.child_name is None


class TestKinCooperation:
    """Tests for KinCooperation class (Hamilton's rule)."""

    def test_should_not_help_if_no_surplus(self):
        """Test helper with no surplus doesn't help."""
        coop = KinCooperation()
        decision = coop.should_help(
            helper_balance=0.10,
            helper_min_balance=0.15,  # No surplus
            recipient_balance=0.02,
            recipient_risk_threshold=0.05,
            relatedness=RELATEDNESS_PARENT_CHILD,
        )

        assert decision.should_help is False

    def test_should_not_help_if_recipient_ok(self):
        """Test no help if recipient is not struggling."""
        coop = KinCooperation()
        decision = coop.should_help(
            helper_balance=0.50,
            helper_min_balance=0.15,
            recipient_balance=0.10,  # Above risk threshold
            recipient_risk_threshold=0.05,
            relatedness=RELATEDNESS_PARENT_CHILD,
        )

        assert decision.should_help is False

    def test_should_help_struggling_child(self):
        """Test Hamilton's rule triggers help for struggling child."""
        coop = KinCooperation(kin_helping_threshold=0.1)
        decision = coop.should_help(
            helper_balance=0.50,
            helper_min_balance=0.15,
            recipient_balance=0.01,  # Very low, at risk
            recipient_risk_threshold=0.05,
            relatedness=RELATEDNESS_PARENT_CHILD,  # 0.5
        )

        # r * b = 0.5 * ~0.8 = 0.4, should be > cost
        assert decision.should_help is True
        assert decision.amount > 0

    def test_check_family_needs(self):
        """Test checking multiple family members."""
        coop = KinCooperation(kin_helping_threshold=0.1)
        family = FamilyNetwork()

        # Add children with different needs
        family.children["child-1"] = FamilyMemberStatus(
            name="child-1",
            relationship="child",
            relatedness=RELATEDNESS_PARENT_CHILD,
            last_known_balance=0.02,  # Struggling
            is_alive=True,
        )
        family.children["child-2"] = FamilyMemberStatus(
            name="child-2",
            relationship="child",
            relatedness=RELATEDNESS_PARENT_CHILD,
            last_known_balance=0.20,  # Doing fine
            is_alive=True,
        )

        decisions = coop.check_family_needs(
            helper_balance=0.50,
            helper_min_balance=0.15,
            family=family,
            risk_threshold=0.05,
        )

        # Should offer to help child-1 but not child-2
        assert len(decisions) == 1
        assert decisions[0][0] == "child-1"
        assert decisions[0][1].should_help is True


class TestFamilyNetwork:
    """Tests for FamilyNetwork class."""

    def test_set_parent(self):
        """Test setting parent."""
        family = FamilyNetwork()
        family.set_parent("parent-bot")
        assert family.parent_name == "parent-bot"

    def test_add_child(self):
        """Test adding a child."""
        family = FamilyNetwork()
        family.add_child("child-1")

        assert "child-1" in family.children
        assert family.children["child-1"].is_alive is True

    def test_add_sibling(self):
        """Test adding a sibling."""
        family = FamilyNetwork()
        family.add_sibling("sibling-1")

        assert "sibling-1" in family.siblings

    def test_receive_status_update(self):
        """Test receiving status update from child."""
        family = FamilyNetwork()
        family.add_child("child-1")

        family.receive_status_update(
            from_name="child-1",
            my_cycle=50,
            status={"balance": 0.25, "cycle_count": 20},
        )

        child = family.children["child-1"]
        assert child.last_known_balance == 0.25
        assert child.last_known_cycle == 20

    def test_receive_death_notification(self):
        """Test receiving death notification."""
        family = FamilyNetwork()
        family.add_child("child-1")

        family.receive_death_notification("child-1")

        assert family.children["child-1"].is_alive is False

    def test_get_struggling_children(self):
        """Test finding struggling children."""
        family = FamilyNetwork()
        family.add_child("rich-child")
        family.add_child("poor-child")

        family.children["rich-child"].last_known_balance = 0.20
        family.children["poor-child"].last_known_balance = 0.02

        struggling = family.get_struggling_children(balance_threshold=0.05)
        assert len(struggling) == 1
        assert struggling[0].name == "poor-child"


class TestReproductiveAssessment:
    """Tests for ReproductiveAssessment dataclass."""

    def test_no_factory(self):
        """Test creating a 'no' assessment."""
        assessment = ReproductiveAssessment.no(
            reasons=["Too young", "Insufficient funds"],
            factors={"age": 5},
        )

        assert assessment.should_reproduce is False
        assert len(assessment.reasons) == 2
        assert "age" in assessment.factors

    def test_yes_factory(self):
        """Test creating a 'yes' assessment."""
        assessment = ReproductiveAssessment.yes(
            confidence=0.75,
            investment=0.20,
            urgency=0.3,
            reasons=["Stable and ready"],
            factors={"runway": 50},
        )

        assert assessment.should_reproduce is True
        assert assessment.confidence == 0.75
        assert assessment.recommended_investment == 0.20
        assert assessment.urgency == 0.3

    def test_serialization(self):
        """Test to_dict method."""
        assessment = ReproductiveAssessment.yes(
            confidence=0.75,
            investment=0.20,
            urgency=0.3,
            reasons=["Ready"],
            factors={"test": True},
        )

        data = assessment.to_dict()
        assert data["should_reproduce"] is True
        assert data["confidence"] == 0.75
        assert data["recommended_investment"] == 0.20


class TestSelfAwareness:
    """Tests for combined SelfAwareness class."""

    def test_record_cycle(self):
        """Test recording cycle updates all components."""
        awareness = SelfAwareness()

        awareness.record_cycle(
            balance=0.50,
            income=0.02,
            cost=0.001,
            task_type="coding",
            task_success=True,
        )

        assert len(awareness.economic.balance_history) == 1
        assert len(awareness.performance.task_outcomes) == 1

    def test_should_reproduce(self):
        """Test reproduction recommendation."""
        awareness = SelfAwareness(
            age=AgeAwareness(expected_lifespan=500),
        )

        # Build up history
        for i in range(30):
            awareness.record_cycle(
                balance=0.50,
                income=0.02,
                cost=0.001,
                task_type="coding",
                task_success=i < 25,  # 83% success rate
            )

        should, factors = awareness.should_reproduce(
            cycle_count=30,
            total_children=0,
            min_reproduction_age=10,
            safety_margin_cycles=20,
            min_success_rate=0.5,
            confidence_threshold=0.4,
        )

        assert "is_mature" in factors
        assert "has_runway" in factors
        assert "confidence" in factors

    def test_get_full_assessment(self):
        """Test getting full assessment."""
        awareness = SelfAwareness()

        for i in range(10):
            awareness.record_cycle(
                balance=0.50,
                income=0.02,
                cost=0.001,
                task_type="coding",
                task_success=True,
            )

        assessment = awareness.get_full_assessment(cycle_count=10, total_children=0)

        assert "economic" in assessment
        assert "performance" in assessment
        assert "age" in assessment
