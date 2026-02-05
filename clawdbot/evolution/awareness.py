"""Awareness - Self-awareness modules for bots.

Bots can track their own economic situation, performance, and age without
needing global knowledge of the colony. This enables experience-based
decision making for reproduction and survival.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EconomicAwareness:
    """Bot tracks its own economic situation.

    Enables the bot to understand:
    - How much it typically spends per cycle
    - How much it typically earns per cycle
    - How many cycles of runway it has left
    - Whether its financial situation is improving or declining
    """

    balance_history: list[float] = field(default_factory=list)
    income_history: list[float] = field(default_factory=list)
    cost_history: list[float] = field(default_factory=list)
    current_balance: float = 0.0

    # Configuration
    history_window: int = 20  # Look at last N cycles for averages

    def record_cycle(
        self,
        balance: float,
        income: float,
        cost: float,
    ) -> None:
        """Record economic data from a completed cycle.

        Args:
            balance: Balance at end of cycle
            income: Income earned this cycle (rewards)
            cost: Costs incurred this cycle (existence cost, API spend)
        """
        self.balance_history.append(balance)
        self.income_history.append(income)
        self.cost_history.append(cost)
        self.current_balance = balance

        # Keep history bounded
        max_history = self.history_window * 5
        if len(self.balance_history) > max_history:
            self.balance_history = self.balance_history[-max_history:]
            self.income_history = self.income_history[-max_history:]
            self.cost_history = self.cost_history[-max_history:]

    @property
    def avg_cost_per_cycle(self) -> float:
        """What do I typically spend per cycle?"""
        recent = self.cost_history[-self.history_window:]
        if not recent:
            return 0.001  # Default existence cost
        return sum(recent) / len(recent)

    @property
    def avg_income_per_cycle(self) -> float:
        """What do I typically earn per cycle?"""
        recent = self.income_history[-self.history_window:]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)

    @property
    def net_burn_rate(self) -> float:
        """Net cost per cycle (positive = losing money)."""
        return self.avg_cost_per_cycle - self.avg_income_per_cycle

    @property
    def runway_cycles(self) -> float:
        """How many cycles can I survive at current burn rate?"""
        burn = self.net_burn_rate
        if burn <= 0:
            return float('inf')  # Profitable!
        if self.current_balance <= 0:
            return 0.0
        return self.current_balance / burn

    @property
    def is_profitable(self) -> bool:
        """Am I earning more than I spend?"""
        return self.net_burn_rate <= 0

    @property
    def trend(self) -> str:
        """Am I doing better or worse over time?"""
        if len(self.balance_history) < 10:
            return "unknown"

        recent = self.balance_history[-5:]
        earlier = self.balance_history[-10:-5]

        recent_avg = sum(recent) / len(recent)
        earlier_avg = sum(earlier) / len(earlier)

        if recent_avg > earlier_avg * 1.1:
            return "improving"
        elif recent_avg < earlier_avg * 0.9:
            return "declining"
        return "stable"

    def get_assessment(self) -> dict[str, Any]:
        """Get a summary of economic awareness."""
        return {
            "current_balance": self.current_balance,
            "avg_income": self.avg_income_per_cycle,
            "avg_cost": self.avg_cost_per_cycle,
            "net_burn_rate": self.net_burn_rate,
            "runway_cycles": self.runway_cycles,
            "is_profitable": self.is_profitable,
            "trend": self.trend,
            "history_length": len(self.balance_history),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "balance_history": self.balance_history[-100:],  # Keep last 100
            "income_history": self.income_history[-100:],
            "cost_history": self.cost_history[-100:],
            "current_balance": self.current_balance,
            "history_window": self.history_window,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EconomicAwareness:
        """Restore from serialized data."""
        return cls(
            balance_history=data.get("balance_history", []),
            income_history=data.get("income_history", []),
            cost_history=data.get("cost_history", []),
            current_balance=data.get("current_balance", 0.0),
            history_window=data.get("history_window", 20),
        )


@dataclass
class PerformanceAwareness:
    """Bot tracks its own task performance.

    Enables the bot to understand:
    - What's its recent success rate
    - What task types it's best at
    - Patterns in its performance
    """

    task_outcomes: list[tuple[str, bool]] = field(default_factory=list)
    # (task_type, success)

    history_window: int = 20

    def record_task(self, task_type: str, success: bool) -> None:
        """Record the outcome of a task attempt.

        Args:
            task_type: Type of task attempted
            success: Whether the task was completed successfully
        """
        self.task_outcomes.append((task_type, success))

        # Keep history bounded
        max_history = 200
        if len(self.task_outcomes) > max_history:
            self.task_outcomes = self.task_outcomes[-max_history:]

    @property
    def recent_success_rate(self) -> float:
        """What's my recent success rate?"""
        recent = self.task_outcomes[-self.history_window:]
        if not recent:
            return 0.5  # Neutral prior
        return sum(1 for _, success in recent if success) / len(recent)

    @property
    def total_success_rate(self) -> float:
        """What's my overall success rate?"""
        if not self.task_outcomes:
            return 0.5
        return sum(1 for _, success in self.task_outcomes if success) / len(self.task_outcomes)

    @property
    def consecutive_failures(self) -> int:
        """How many consecutive failures have I had?"""
        count = 0
        for _, success in reversed(self.task_outcomes):
            if success:
                break
            count += 1
        return count

    @property
    def consecutive_successes(self) -> int:
        """How many consecutive successes have I had?"""
        count = 0
        for _, success in reversed(self.task_outcomes):
            if not success:
                break
            count += 1
        return count

    def get_success_rate_by_type(self) -> dict[str, float]:
        """Get success rate broken down by task type."""
        by_type: dict[str, list[bool]] = defaultdict(list)
        for task_type, success in self.task_outcomes[-50:]:
            by_type[task_type].append(success)

        return {
            task_type: sum(outcomes) / len(outcomes)
            for task_type, outcomes in by_type.items()
        }

    def get_best_task_type(self) -> str | None:
        """What task type am I best at?"""
        rates = self.get_success_rate_by_type()
        if not rates:
            return None
        return max(rates.keys(), key=lambda t: rates[t])

    def get_worst_task_type(self) -> str | None:
        """What task type am I worst at?"""
        rates = self.get_success_rate_by_type()
        if not rates:
            return None
        return min(rates.keys(), key=lambda t: rates[t])

    def get_assessment(self) -> dict[str, Any]:
        """Get a summary of performance awareness."""
        return {
            "recent_success_rate": self.recent_success_rate,
            "total_success_rate": self.total_success_rate,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "best_task_type": self.get_best_task_type(),
            "worst_task_type": self.get_worst_task_type(),
            "tasks_attempted": len(self.task_outcomes),
            "success_by_type": self.get_success_rate_by_type(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "task_outcomes": self.task_outcomes[-100:],
            "history_window": self.history_window,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceAwareness:
        """Restore from serialized data."""
        return cls(
            task_outcomes=data.get("task_outcomes", []),
            history_window=data.get("history_window", 20),
        )


@dataclass
class AgeAwareness:
    """Bot is aware of its own aging.

    Enables the bot to understand:
    - Its current life stage (juvenile, prime, mature, elder)
    - Urgency based on approaching end of life
    - Whether it should prioritize reproduction
    """

    expected_lifespan: int = 500  # Expected cycles before natural death

    def get_life_stage(self, cycle_count: int) -> str:
        """Get current life stage.

        Args:
            cycle_count: Current cycle number

        Returns:
            Life stage: 'juvenile', 'prime', 'mature', or 'elder'
        """
        ratio = cycle_count / self.expected_lifespan
        if ratio < 0.1:
            return "juvenile"
        elif ratio < 0.5:
            return "prime"
        elif ratio < 0.8:
            return "mature"
        else:
            return "elder"

    def get_age_ratio(self, cycle_count: int) -> float:
        """Get age as a ratio of expected lifespan (0.0 to 1.0+)."""
        return cycle_count / self.expected_lifespan

    def get_mortality_anxiety(self, cycle_count: int) -> float:
        """How worried should I be about dying soon?

        Returns a value from 0.0 (no worry) to 1.0 (maximum worry).
        Anxiety increases significantly after 50% of expected lifespan.
        """
        ratio = cycle_count / self.expected_lifespan
        if ratio < 0.5:
            return 0.0
        return min(1.0, (ratio - 0.5) * 2)  # 0 at 50%, 1 at 100%

    def get_reproduction_urgency(
        self,
        cycle_count: int,
        total_children: int,
    ) -> float:
        """Calculate urgency to reproduce based on age and legacy.

        Args:
            cycle_count: Current cycle number
            total_children: Number of children already spawned

        Returns:
            Urgency from 0.0 (no urgency) to 1.0 (maximum urgency)
        """
        mortality = self.get_mortality_anxiety(cycle_count)
        age_ratio = self.get_age_ratio(cycle_count)

        # If I'm old and have no children, urgency is high
        if total_children == 0 and age_ratio > 0.5:
            return 0.8 + (age_ratio - 0.5) * 0.4  # 0.8 to 1.0

        # Base urgency from age
        base_urgency = mortality * 0.3

        # Reduce urgency if I already have children
        if total_children > 0:
            base_urgency *= 0.7  # 30% reduction
        if total_children > 2:
            base_urgency *= 0.5  # Further 50% reduction

        return min(1.0, base_urgency)

    def is_mature_enough(self, cycle_count: int, min_age: int) -> bool:
        """Check if bot has reached reproductive maturity.

        Args:
            cycle_count: Current cycle number
            min_age: Minimum age for reproduction
        """
        return cycle_count >= min_age

    def get_assessment(self, cycle_count: int, total_children: int = 0) -> dict[str, Any]:
        """Get a summary of age awareness."""
        return {
            "cycle_count": cycle_count,
            "expected_lifespan": self.expected_lifespan,
            "age_ratio": self.get_age_ratio(cycle_count),
            "life_stage": self.get_life_stage(cycle_count),
            "mortality_anxiety": self.get_mortality_anxiety(cycle_count),
            "reproduction_urgency": self.get_reproduction_urgency(cycle_count, total_children),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "expected_lifespan": self.expected_lifespan,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgeAwareness:
        """Restore from serialized data."""
        return cls(
            expected_lifespan=data.get("expected_lifespan", 500),
        )


@dataclass
class SelfAwareness:
    """Combined self-awareness module integrating all awareness types.

    This is the main interface for bots to understand their own situation.
    """

    economic: EconomicAwareness = field(default_factory=EconomicAwareness)
    performance: PerformanceAwareness = field(default_factory=PerformanceAwareness)
    age: AgeAwareness = field(default_factory=AgeAwareness)

    def record_cycle(
        self,
        balance: float,
        income: float,
        cost: float,
        task_type: str | None = None,
        task_success: bool | None = None,
    ) -> None:
        """Record data from a completed cycle.

        Args:
            balance: Balance at end of cycle
            income: Income earned this cycle
            cost: Costs incurred this cycle
            task_type: Type of task attempted (if any)
            task_success: Whether task succeeded (if attempted)
        """
        self.economic.record_cycle(balance, income, cost)

        if task_type is not None and task_success is not None:
            self.performance.record_task(task_type, task_success)

    def get_full_assessment(self, cycle_count: int, total_children: int = 0) -> dict[str, Any]:
        """Get complete self-assessment."""
        return {
            "economic": self.economic.get_assessment(),
            "performance": self.performance.get_assessment(),
            "age": self.age.get_assessment(cycle_count, total_children),
        }

    def should_reproduce(
        self,
        cycle_count: int,
        total_children: int,
        min_reproduction_age: int,
        safety_margin_cycles: int,
        min_success_rate: float,
        confidence_threshold: float,
    ) -> tuple[bool, dict[str, Any]]:
        """Evaluate whether reproduction is advisable.

        This is a soft recommendation based on self-awareness.
        The bot's genome still controls the final decision.

        Args:
            cycle_count: Current cycle number
            total_children: Number of existing children
            min_reproduction_age: Minimum age for reproduction
            safety_margin_cycles: Required runway for safety
            min_success_rate: Minimum required success rate
            confidence_threshold: Minimum confidence to reproduce

        Returns:
            Tuple of (should_reproduce, factors_dict)
        """
        factors = {}

        # Check maturity
        is_mature = self.age.is_mature_enough(cycle_count, min_reproduction_age)
        factors["is_mature"] = is_mature

        # Check economic stability
        runway = self.economic.runway_cycles
        has_runway = runway > safety_margin_cycles
        factors["has_runway"] = has_runway
        factors["runway_cycles"] = runway

        # Check performance
        success_rate = self.performance.recent_success_rate
        is_performing = success_rate >= min_success_rate
        factors["is_performing"] = is_performing
        factors["success_rate"] = success_rate

        # Check urgency
        urgency = self.age.get_reproduction_urgency(cycle_count, total_children)
        factors["urgency"] = urgency

        # Calculate confidence
        base_confidence = 0.5
        if has_runway:
            base_confidence += 0.2
        if is_performing:
            base_confidence += 0.2
        if self.economic.is_profitable:
            base_confidence += 0.1

        # Urgency can push confidence above threshold
        confidence = base_confidence + (urgency * 0.3)
        factors["confidence"] = confidence

        # Decision
        should = (
            is_mature
            and (has_runway or urgency > 0.7)  # Urgency can override runway requirement
            and confidence >= confidence_threshold
        )

        return should, factors

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "economic": self.economic.to_dict(),
            "performance": self.performance.to_dict(),
            "age": self.age.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelfAwareness:
        """Restore from serialized data."""
        return cls(
            economic=EconomicAwareness.from_dict(data.get("economic", {})),
            performance=PerformanceAwareness.from_dict(data.get("performance", {})),
            age=AgeAwareness.from_dict(data.get("age", {})),
        )
