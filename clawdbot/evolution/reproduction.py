"""Reproduction - Offspring tracking and reproductive decisions.

Bots track the outcomes of their offspring and use this information
to make better reproductive decisions over time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChildStatus(Enum):
    """Status of a child bot."""

    ALIVE = "alive"
    DEAD_BANKRUPTCY = "dead_bankruptcy"
    DEAD_STARVATION = "dead_starvation"
    DEAD_NATURAL = "dead_natural"
    DEAD_SHUTDOWN = "dead_shutdown"
    UNKNOWN = "unknown"  # Lost contact


@dataclass
class ChildOutcome:
    """Record of a single child's life outcome."""

    child_name: str
    birth_cycle: int  # Parent's cycle when child was born
    investment_amount: float  # How much parent gave to child

    # Nest Economy (NEST_ECONOMY.md §2): where this child was placed.
    # None = legacy placement (colony-local site, unclassified).
    route: str | None = None
    site_class: str | None = None

    # Updated over time
    status: ChildStatus = ChildStatus.ALIVE
    last_known_balance: float = 0.0
    last_known_cycle: int = 0
    last_update_cycle: int = 0  # Parent's cycle when last updated

    # Final stats (when child dies)
    death_cycle: int | None = None  # Child's cycle count at death
    death_cause: str | None = None
    final_balance: float | None = None
    grandchildren_count: int = 0  # How many children did this child have

    @property
    def survived_to_maturity(self) -> bool:
        """Did child survive past maturity threshold (20 cycles)?"""
        if self.death_cycle is not None:
            return self.death_cycle >= 20
        # If still alive, check last known cycle
        return self.last_known_cycle >= 20

    @property
    def was_successful(self) -> bool:
        """Did child achieve success (reproduced or lived long)?"""
        if self.grandchildren_count > 0:
            return True
        if self.death_cycle is not None:
            return self.death_cycle >= 50
        return self.last_known_cycle >= 50

    @property
    def died_young(self) -> bool:
        """Did child die before reaching maturity?"""
        if self.death_cycle is not None:
            return self.death_cycle < 20
        return False

    @property
    def is_alive(self) -> bool:
        """Is child still alive?"""
        return self.status == ChildStatus.ALIVE

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "child_name": self.child_name,
            "birth_cycle": self.birth_cycle,
            "investment_amount": self.investment_amount,
            "route": self.route,
            "site_class": self.site_class,
            "status": self.status.value,
            "last_known_balance": self.last_known_balance,
            "last_known_cycle": self.last_known_cycle,
            "last_update_cycle": self.last_update_cycle,
            "death_cycle": self.death_cycle,
            "death_cause": self.death_cause,
            "final_balance": self.final_balance,
            "grandchildren_count": self.grandchildren_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChildOutcome:
        """Restore from serialized data."""
        return cls(
            child_name=data["child_name"],
            birth_cycle=data["birth_cycle"],
            investment_amount=data["investment_amount"],
            route=data.get("route"),
            site_class=data.get("site_class"),
            status=ChildStatus(data.get("status", "unknown")),
            last_known_balance=data.get("last_known_balance", 0.0),
            last_known_cycle=data.get("last_known_cycle", 0),
            last_update_cycle=data.get("last_update_cycle", 0),
            death_cycle=data.get("death_cycle"),
            death_cause=data.get("death_cause"),
            final_balance=data.get("final_balance"),
            grandchildren_count=data.get("grandchildren_count", 0),
        )


@dataclass
class OffspringHistory:
    """Parent's memory of their children's fates.

    This is the CORE learning signal for reproductive strategy.
    Parents adapt their investment and timing based on offspring outcomes.
    """

    children: dict[str, ChildOutcome] = field(default_factory=dict)

    def record_birth(
        self,
        child_name: str,
        birth_cycle: int,
        investment_amount: float,
        *,
        route: str | None = None,
        site_class: str | None = None,
    ) -> None:
        """Record the birth of a new child.

        Args:
            child_name: Name of the new child
            birth_cycle: Parent's current cycle
            investment_amount: Amount invested in child
            route: Model route the child was placed on (Nest Economy)
            site_class: Nest site class the child was placed at
        """
        self.children[child_name] = ChildOutcome(
            child_name=child_name,
            birth_cycle=birth_cycle,
            investment_amount=investment_amount,
            route=route,
            site_class=site_class,
        )

    def record_child_update(
        self,
        child_name: str,
        parent_cycle: int,
        status: dict[str, Any],
    ) -> None:
        """Record a status update from a child.

        Args:
            child_name: Name of the child
            parent_cycle: Parent's current cycle
            status: Status dict from child containing:
                - cycle_count: Child's current cycle
                - balance: Child's current balance
                - children_count: Number of grandchildren
        """
        if child_name not in self.children:
            return

        child = self.children[child_name]
        child.last_known_cycle = status.get("cycle_count", child.last_known_cycle)
        child.last_known_balance = status.get("balance", child.last_known_balance)
        child.grandchildren_count = status.get("children_count", child.grandchildren_count)
        child.last_update_cycle = parent_cycle

    def record_child_death(
        self,
        child_name: str,
        cause: str,
        final_stats: dict[str, Any],
    ) -> None:
        """Record that a child has died.

        Args:
            child_name: Name of the deceased child
            cause: Death cause (e.g., 'bankruptcy', 'starvation')
            final_stats: Child's final statistics
        """
        if child_name not in self.children:
            return

        child = self.children[child_name]

        # Map cause to status
        cause_map = {
            "bankruptcy": ChildStatus.DEAD_BANKRUPTCY,
            "starvation": ChildStatus.DEAD_STARVATION,
            "natural": ChildStatus.DEAD_NATURAL,
            "shutdown": ChildStatus.DEAD_SHUTDOWN,
        }
        child.status = cause_map.get(cause, ChildStatus.UNKNOWN)

        child.death_cycle = final_stats.get("cycle_count", child.last_known_cycle)
        child.death_cause = cause
        child.final_balance = final_stats.get("balance", 0.0)
        child.grandchildren_count = final_stats.get("children_count", child.grandchildren_count)

    @property
    def total_children(self) -> int:
        """Total number of children ever spawned."""
        return len(self.children)

    @property
    def living_children(self) -> int:
        """Number of children currently alive."""
        return sum(1 for c in self.children.values() if c.is_alive)

    @property
    def dead_children(self) -> int:
        """Number of children that have died."""
        return sum(1 for c in self.children.values() if not c.is_alive)

    @property
    def early_deaths(self) -> int:
        """Number of children that died before maturity."""
        return sum(1 for c in self.children.values() if c.died_young)

    @property
    def survivors(self) -> int:
        """Number of children that survived to maturity."""
        return sum(1 for c in self.children.values() if c.survived_to_maturity)

    @property
    def successful_children(self) -> int:
        """Number of children that achieved success."""
        return sum(1 for c in self.children.values() if c.was_successful)

    @property
    def survival_rate(self) -> float:
        """Fraction of children that survived past maturity (20 cycles)."""
        if self.total_children == 0:
            return 0.5  # Neutral prior
        return self.survivors / self.total_children

    @property
    def grandchildren_count(self) -> int:
        """Total number of grandchildren."""
        return sum(c.grandchildren_count for c in self.children.values())

    def get_average_investment(self) -> float:
        """Average investment amount in children."""
        if not self.children:
            return 0.0
        return sum(c.investment_amount for c in self.children.values()) / len(self.children)

    def get_investment_survival_correlation(self) -> float:
        """Estimate correlation between investment and survival.

        Returns:
            Positive value if higher investment correlates with survival,
            negative if inverse correlation, near zero if no correlation.
        """
        if len(self.children) < 3:
            return 0.0  # Not enough data

        # Group by survival
        survivors = [c for c in self.children.values() if c.survived_to_maturity]
        non_survivors = [c for c in self.children.values() if c.died_young]

        if not survivors or not non_survivors:
            return 0.0

        avg_survivor_investment = sum(c.investment_amount for c in survivors) / len(survivors)
        avg_nonsurvivor_investment = sum(c.investment_amount for c in non_survivors) / len(
            non_survivors
        )

        # Return difference normalized by average
        avg_all = self.get_average_investment()
        if avg_all == 0:
            return 0.0

        return (avg_survivor_investment - avg_nonsurvivor_investment) / avg_all

    def should_increase_investment(self) -> bool:
        """Based on history, should I invest more in future children?"""
        # If many children died young due to bankruptcy, invest more
        if self.early_deaths > self.survivors:
            return True

        # If investment-survival correlation is positive, investing more helps
        correlation = self.get_investment_survival_correlation()
        return correlation > 0.2

    def get_recommended_investment_adjustment(self) -> float:
        """Get recommended adjustment to investment ratio.

        Returns:
            Multiplier to apply to base investment (e.g., 1.2 = 20% more)
        """
        if self.total_children < 2:
            return 1.0  # No adjustment with limited data

        # Base on early death rate
        if self.early_deaths == 0:
            return 1.0  # Current strategy working

        early_death_rate = self.early_deaths / self.total_children

        if early_death_rate > 0.5:
            return 1.3  # Major increase
        elif early_death_rate > 0.3:
            return 1.15  # Moderate increase
        elif early_death_rate > 0.1:
            return 1.05  # Minor increase

        return 1.0

    # Nest Economy (NEST_ECONOMY.md §2 Gate 2b): EV regression constants.
    INVESTMENT_RECENCY_DISCOUNT = 0.9  # weight per step of sibling age
    LAPLACE_PRIOR_RETURN = 0.5  # neutral pseudo-observation revenue-per-token

    def ev_optimal_investment(self, route: str, site_class: str) -> float:
        """Discounted mean revenue-per-token of prior children at this
        (route, site_class), Laplace-smoothed.

        Promotes OffspringHistory from telemetry to decision input: this
        sizes the child's token endowment (min with max_alloc in
        colonyos.spawn.spawn_child). Returns math.inf when there is no
        history at this nest — callers treat inf as "no evidence: size at
        the cap".
        """
        matching = [
            c for c in self.children.values() if c.route == route and c.site_class == site_class
        ]
        if not matching:
            return math.inf
        # Newest sibling first; older siblings are discounted.
        ordered = sorted(matching, key=lambda c: c.birth_cycle, reverse=True)
        weighted_return = 0.0
        weight_total = 0.0
        for age, child in enumerate(ordered):
            investment = child.investment_amount
            if investment <= 0:
                continue
            balance = (
                child.final_balance if child.final_balance is not None else child.last_known_balance
            )
            return_per_token = max(0.0, (balance - investment) / investment)
            weight = pow(self.INVESTMENT_RECENCY_DISCOUNT, age)
            weighted_return += weight * return_per_token
            weight_total += weight
        if weight_total == 0.0:
            return math.inf
        # Laplace smoothing: one pseudo-observation at the neutral prior.
        return (weighted_return + self.LAPLACE_PRIOR_RETURN) / (weight_total + 1.0)

    def get_assessment(self) -> dict[str, Any]:
        """Get summary of offspring history."""
        return {
            "total_children": self.total_children,
            "living_children": self.living_children,
            "dead_children": self.dead_children,
            "early_deaths": self.early_deaths,
            "survivors": self.survivors,
            "successful_children": self.successful_children,
            "survival_rate": self.survival_rate,
            "grandchildren_count": self.grandchildren_count,
            "average_investment": self.get_average_investment(),
            "should_increase_investment": self.should_increase_investment(),
            "investment_adjustment": self.get_recommended_investment_adjustment(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {"children": {name: child.to_dict() for name, child in self.children.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OffspringHistory:
        """Restore from serialized data."""
        children_data = data.get("children", {})
        return cls(
            children={
                name: ChildOutcome.from_dict(child_data)
                for name, child_data in children_data.items()
            }
        )


@dataclass
class ReproductiveAssessment:
    """Result of evaluating reproductive readiness.

    This encapsulates the bot's decision about whether to reproduce
    and how much to invest in offspring.
    """

    should_reproduce: bool
    confidence: float  # 0.0 to 1.0
    recommended_investment: float  # Dollar amount
    urgency: float  # 0.0 to 1.0

    # Factors that went into the decision
    factors: dict[str, Any] = field(default_factory=dict)

    # Reasons (for logging/debugging)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging."""
        return {
            "should_reproduce": self.should_reproduce,
            "confidence": self.confidence,
            "recommended_investment": self.recommended_investment,
            "urgency": self.urgency,
            "factors": self.factors,
            "reasons": self.reasons,
        }

    @classmethod
    def no(
        cls, reasons: list[str], factors: dict[str, Any] | None = None
    ) -> ReproductiveAssessment:
        """Create a 'don't reproduce' assessment."""
        return cls(
            should_reproduce=False,
            confidence=0.0,
            recommended_investment=0.0,
            urgency=0.0,
            factors=factors or {},
            reasons=reasons,
        )

    @classmethod
    def yes(
        cls,
        confidence: float,
        investment: float,
        urgency: float,
        reasons: list[str],
        factors: dict[str, Any] | None = None,
    ) -> ReproductiveAssessment:
        """Create a 'reproduce' assessment."""
        return cls(
            should_reproduce=True,
            confidence=confidence,
            recommended_investment=investment,
            urgency=urgency,
            factors=factors or {},
            reasons=reasons,
        )


class NurturingState(Enum):
    """State of post-reproduction nurturing period."""

    NONE = "none"  # Not in nurturing mode
    ACTIVE = "active"  # Currently nurturing
    COMPLETE = "complete"  # Nurturing finished


@dataclass
class NurturingTracker:
    """Tracks the nurturing period after reproduction.

    During nurturing, the parent:
    - Operates at reduced efficiency
    - May share resources with the child
    - Cannot reproduce again
    """

    state: NurturingState = NurturingState.NONE
    child_name: str | None = None
    cycles_remaining: int = 0
    total_cycles: int = 0
    efficiency: float = 1.0  # Reduced during nurturing

    def start_nurturing(
        self,
        child_name: str,
        nurturing_cycles: int,
        efficiency: float = 0.5,
    ) -> None:
        """Start nurturing a new child.

        Args:
            child_name: Name of the child being nurtured
            nurturing_cycles: Number of cycles to spend nurturing
            efficiency: Task efficiency during nurturing (0.0 to 1.0)
        """
        self.state = NurturingState.ACTIVE
        self.child_name = child_name
        self.cycles_remaining = nurturing_cycles
        self.total_cycles = nurturing_cycles
        self.efficiency = efficiency

    def tick(self) -> bool:
        """Process one cycle of nurturing.

        Returns:
            True if nurturing is complete, False if still ongoing
        """
        if self.state != NurturingState.ACTIVE:
            return True

        self.cycles_remaining -= 1

        if self.cycles_remaining <= 0:
            self.state = NurturingState.COMPLETE
            return True

        return False

    def complete_nurturing(self) -> None:
        """End the nurturing period."""
        self.state = NurturingState.NONE
        self.child_name = None
        self.cycles_remaining = 0
        self.total_cycles = 0
        self.efficiency = 1.0

    @property
    def is_nurturing(self) -> bool:
        """Is currently in nurturing state."""
        return self.state == NurturingState.ACTIVE

    @property
    def can_reproduce(self) -> bool:
        """Can reproduce (not currently nurturing)."""
        return self.state != NurturingState.ACTIVE

    @property
    def progress(self) -> float:
        """Nurturing progress (0.0 to 1.0)."""
        if self.total_cycles == 0:
            return 1.0
        return 1.0 - (self.cycles_remaining / self.total_cycles)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "state": self.state.value,
            "child_name": self.child_name,
            "cycles_remaining": self.cycles_remaining,
            "total_cycles": self.total_cycles,
            "efficiency": self.efficiency,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NurturingTracker:
        """Restore from serialized data."""
        return cls(
            state=NurturingState(data.get("state", "none")),
            child_name=data.get("child_name"),
            cycles_remaining=data.get("cycles_remaining", 0),
            total_cycles=data.get("total_cycles", 0),
            efficiency=data.get("efficiency", 1.0),
        )
