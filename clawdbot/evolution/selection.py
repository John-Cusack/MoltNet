"""Selection - Death mechanisms and viability checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DeathCause(Enum):
    """Causes of bot death."""

    ALIVE = "alive"  # Not dead
    BANKRUPTCY = "bankruptcy"  # Wallet below minimum
    CULLING = "culling"  # Killed by population pressure
    NATURAL = "natural"  # Exceeded max cycles
    SHUTDOWN = "shutdown"  # Manual stop


@dataclass
class ViabilityCheck:
    """Result of checking bot viability."""

    viable: bool
    cause: DeathCause
    details: dict[str, Any]

    @classmethod
    def alive(cls) -> ViabilityCheck:
        """Create a 'still alive' result."""
        return cls(viable=True, cause=DeathCause.ALIVE, details={})

    @classmethod
    def dead(cls, cause: DeathCause, **details) -> ViabilityCheck:
        """Create a 'dead' result with cause."""
        return cls(viable=False, cause=cause, details=details)


@dataclass
class SelectionConfig:
    """Configuration for selection pressure."""

    # Bankruptcy threshold (death if balance below this)
    minimum_viable_balance: float = 0.001

    # Existence cost per cycle (metabolism)
    existence_cost_per_cycle: float = 0.0001

    # Culling settings
    enable_culling: bool = False
    culling_interval_cycles: int = 100
    culling_bottom_percentile: float = 0.1  # Kill bottom 10%

    @classmethod
    def default(cls) -> SelectionConfig:
        """Create default selection configuration."""
        return cls()

    @classmethod
    def harsh(cls) -> SelectionConfig:
        """Create harsh selection pressure."""
        return cls(
            minimum_viable_balance=0.005,
            existence_cost_per_cycle=0.0002,
            enable_culling=True,
            culling_interval_cycles=50,
            culling_bottom_percentile=0.15,
        )

    @classmethod
    def gentle(cls) -> SelectionConfig:
        """Create gentle selection pressure."""
        return cls(
            minimum_viable_balance=0.0001,
            existence_cost_per_cycle=0.00005,
            enable_culling=False,
        )

    @classmethod
    def openclaw_default(cls) -> SelectionConfig:
        """Create default selection config for OpenClaw bots."""
        return cls(
            minimum_viable_balance=0.01,  # Higher threshold for OpenClaw
            existence_cost_per_cycle=0.001,  # Higher cost (full agent)
            enable_culling=False,
        )

    @classmethod
    def openclaw_harsh(cls) -> SelectionConfig:
        """Create harsh selection for OpenClaw bots."""
        return cls(
            minimum_viable_balance=0.02,
            existence_cost_per_cycle=0.002,
            enable_culling=True,
            culling_interval_cycles=25,
            culling_bottom_percentile=0.20,
        )


class SelectionPressure:
    """Applies selection pressure through death mechanisms.

    This class implements the core evolutionary selection:
    - Bots that can't pay their bills die (bankruptcy)
    - Optionally, weakest bots are culled periodically
    """

    def __init__(self, config: SelectionConfig | None = None):
        """Initialize selection pressure.

        Args:
            config: Selection configuration. Uses default if None.
        """
        self.config = config or SelectionConfig.default()

    def check_viability(
        self,
        wallet_balance: float,
        consecutive_failures: int,
        cycle_count: int,
        max_cycles: int,
    ) -> ViabilityCheck:
        """Check if a bot is still viable.

        Args:
            wallet_balance: Current wallet balance
            consecutive_failures: Number of consecutive task failures (kept for API compatibility)
            cycle_count: Current cycle number
            max_cycles: Maximum allowed cycles

        Returns:
            ViabilityCheck indicating if bot should live or die
        """
        # Check bankruptcy
        if wallet_balance < self.config.minimum_viable_balance:
            return ViabilityCheck.dead(
                DeathCause.BANKRUPTCY,
                balance=wallet_balance,
                threshold=self.config.minimum_viable_balance,
            )

        # Check natural death (age limit)
        if cycle_count >= max_cycles:
            return ViabilityCheck.dead(
                DeathCause.NATURAL,
                cycle_count=cycle_count,
                max_cycles=max_cycles,
            )

        return ViabilityCheck.alive()

    def get_existence_cost(self) -> float:
        """Get the cost of existing for one cycle."""
        return self.config.existence_cost_per_cycle

    def should_cull(self, cycle_count: int) -> bool:
        """Check if culling should occur this cycle.

        Args:
            cycle_count: Current cycle number

        Returns:
            True if culling should happen
        """
        if not self.config.enable_culling:
            return False

        return cycle_count > 0 and cycle_count % self.config.culling_interval_cycles == 0

    def select_for_culling(
        self,
        bots: list[dict[str, Any]],
    ) -> list[str]:
        """Select bots to cull based on fitness.

        Args:
            bots: List of bot info dicts with 'name' and 'fitness' keys

        Returns:
            List of bot names to cull
        """
        if not bots or not self.config.enable_culling:
            return []

        # Sort by fitness (lowest first)
        sorted_bots = sorted(bots, key=lambda b: b.get("fitness", 0))

        # Calculate how many to cull
        cull_count = int(len(sorted_bots) * self.config.culling_bottom_percentile)

        # Get names of bots to cull
        return [b["name"] for b in sorted_bots[:cull_count]]

    def calculate_display_fitness(
        self,
        survival_time: int,
        economic_roi: float,
        task_success_rate: float,
        offspring_survival_rate: float,
    ) -> float:
        """Calculate display fitness for analytics.

        This is NOT used for selection (that's emergent from survival).
        This is only for displaying fitness in the observatory.

        Args:
            survival_time: Number of cycles survived
            economic_roi: (revenue - costs) / costs
            task_success_rate: Fraction of tasks completed successfully
            offspring_survival_rate: Fraction of offspring still alive

        Returns:
            Display fitness score (0.0-1.0)
        """
        # Normalize each component to 0-1
        survival_score = min(1.0, survival_time / 100)  # 100 cycles = max
        roi_score = max(0.0, min(1.0, (economic_roi + 1) / 2))  # -1 to 1 -> 0 to 1
        success_score = task_success_rate
        offspring_score = offspring_survival_rate

        # Weighted average
        fitness = (
            0.20 * survival_score
            + 0.30 * roi_score
            + 0.20 * success_score
            + 0.30 * offspring_score
        )

        return round(fitness, 4)


# Convenience functions for common checks
def is_bankrupt(balance: float, threshold: float = 0.001) -> bool:
    """Check if a balance indicates bankruptcy."""
    return balance < threshold
