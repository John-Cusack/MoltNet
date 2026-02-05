"""Expanded Genome - Heritable traits for evolutionary selection."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExpandedGenome:
    """Expanded bot genome with strategy traits for evolutionary selection.

    This genome defines heritable traits that affect:
    - Task selection and preferences
    - Economic behavior (spending, saving, reproduction)
    - Model selection strategy
    - Timing parameters
    - Mutation behavior

    These traits are subject to natural selection - bots with traits
    leading to profitability survive and reproduce.
    """

    # Identity
    name: str = ""
    generation: int = 1
    parent_name: str | None = None

    # ================================================================
    # Strategy genes (task selection)
    # ================================================================

    # Weight per task type (higher = more likely to select)
    task_preferences: dict[str, float] = field(
        default_factory=lambda: {
            "math": 0.5,
            "json": 0.5,
            "logic": 0.5,
            "code": 0.5,
        }
    )

    # Risk tolerance: 0=always easy tasks, 1=always hard tasks
    risk_tolerance: float = 0.3

    # Target difficulty level (0.0-1.0)
    difficulty_preference: float = 0.4

    # ================================================================
    # Economic genes
    # ================================================================

    # Maximum budget per cycle (USD)
    budget_per_cycle: float = 0.05

    # Fraction of income to save vs spend on harder tasks
    savings_rate: float = 0.2

    # Minimum balance required before attempting reproduction
    replication_threshold: float = 0.08

    # Fraction of balance to give to child
    child_inheritance_ratio: float = 0.4

    # ================================================================
    # Model selection genes
    # ================================================================

    # Preferred model tier (1=cheapest, 4=best)
    model_preference_tier: int = 2

    # How aggressively to fall back to cheaper models (0=never, 1=always)
    fallback_aggressiveness: float = 0.7

    # Prefer local (free) models
    prefer_local: bool = True

    # ================================================================
    # Timing genes
    # ================================================================

    # Seconds between cycles
    cycle_interval_seconds: float = 30.0

    # Multiplier for task timeout (1.0 = normal)
    task_timeout_multiplier: float = 1.0

    # Maximum cycles before natural death
    max_cycles_per_run: int = 1000

    # ================================================================
    # Meta genes (mutation control)
    # ================================================================

    # Probability of mutation per gene during reproduction
    mutation_rate: float = 0.1

    # Magnitude of mutations (0.1 = ±10%)
    mutation_magnitude: float = 0.1

    def to_dict(self) -> dict[str, Any]:
        """Convert genome to dictionary for serialization."""
        return {
            "name": self.name,
            "generation": self.generation,
            "parent_name": self.parent_name,
            # Strategy
            "task_preferences": self.task_preferences,
            "risk_tolerance": self.risk_tolerance,
            "difficulty_preference": self.difficulty_preference,
            # Economic
            "budget_per_cycle": self.budget_per_cycle,
            "savings_rate": self.savings_rate,
            "replication_threshold": self.replication_threshold,
            "child_inheritance_ratio": self.child_inheritance_ratio,
            # Model selection
            "model_preference_tier": self.model_preference_tier,
            "fallback_aggressiveness": self.fallback_aggressiveness,
            "prefer_local": self.prefer_local,
            # Timing
            "cycle_interval_seconds": self.cycle_interval_seconds,
            "task_timeout_multiplier": self.task_timeout_multiplier,
            "max_cycles_per_run": self.max_cycles_per_run,
            # Meta
            "mutation_rate": self.mutation_rate,
            "mutation_magnitude": self.mutation_magnitude,
        }

    def hash(self) -> str:
        """Generate a hash of the genome (excluding name/generation)."""
        # Hash only heritable traits, not identity
        traits = {
            k: v
            for k, v in self.to_dict().items()
            if k not in ("name", "generation", "parent_name")
        }
        genome_str = json.dumps(traits, sort_keys=True)
        return hashlib.sha256(genome_str.encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpandedGenome:
        """Create genome from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def random(cls, name: str) -> ExpandedGenome:
        """Create a genome with randomized traits.

        Useful for initializing a diverse population.
        """
        return cls(
            name=name,
            generation=1,
            task_preferences={
                "math": random.uniform(0.2, 0.8),
                "json": random.uniform(0.2, 0.8),
                "logic": random.uniform(0.2, 0.8),
                "code": random.uniform(0.2, 0.8),
            },
            risk_tolerance=random.uniform(0.1, 0.7),
            difficulty_preference=random.uniform(0.2, 0.6),
            budget_per_cycle=random.uniform(0.02, 0.08),
            savings_rate=random.uniform(0.1, 0.4),
            replication_threshold=random.uniform(0.06, 0.12),
            child_inheritance_ratio=random.uniform(0.3, 0.5),
            model_preference_tier=random.randint(1, 3),
            fallback_aggressiveness=random.uniform(0.4, 0.9),
            prefer_local=random.random() > 0.3,  # 70% prefer local
            cycle_interval_seconds=random.uniform(20.0, 60.0),
            task_timeout_multiplier=random.uniform(0.8, 1.2),
            mutation_rate=random.uniform(0.05, 0.15),
            mutation_magnitude=random.uniform(0.05, 0.15),
        )

    def get_brain_config(self) -> dict[str, Any]:
        """Get brain configuration derived from genome."""
        return {
            "budget_per_cycle": self.budget_per_cycle,
            "prefer_local": self.prefer_local,
            "fallback_to_free": self.fallback_aggressiveness > 0.5,
            "routing_strategy": self._get_routing_strategy(),
        }

    def _get_routing_strategy(self) -> str:
        """Determine routing strategy from model preference tier."""
        if self.model_preference_tier >= 4:
            return "best"
        elif self.model_preference_tier <= 1:
            return "cheapest"
        else:
            return "best_value"

    def select_difficulty(self) -> float:
        """Select task difficulty based on genome traits.

        Combines difficulty_preference with some randomness based on risk_tolerance.
        """
        # Base difficulty from preference
        base = self.difficulty_preference

        # Add variance based on risk tolerance
        variance = self.risk_tolerance * 0.3
        difficulty = base + random.uniform(-variance, variance)

        return max(0.0, min(1.0, difficulty))

    def should_attempt_hard_task(self, current_balance: float, task_cost_estimate: float) -> bool:
        """Decide whether to attempt a harder (riskier) task.

        Args:
            current_balance: Current wallet balance
            task_cost_estimate: Estimated cost of the task

        Returns:
            True if should attempt hard task
        """
        # Calculate risk-adjusted threshold
        cushion = current_balance - task_cost_estimate * 2
        risk_appetite = self.risk_tolerance * cushion

        return risk_appetite > 0 and random.random() < self.risk_tolerance

    def calculate_replication_investment(self, current_balance: float) -> float:
        """Calculate how much to invest in a child.

        Args:
            current_balance: Current wallet balance

        Returns:
            Amount to transfer to child
        """
        # Base investment from inheritance ratio
        investment = current_balance * self.child_inheritance_ratio

        # Cap at half of balance (ensure parent survives)
        investment = min(investment, current_balance * 0.5)

        return investment
