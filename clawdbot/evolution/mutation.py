"""Mutation - Operators for evolving genomes."""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from clawdbot.evolution.genome import ExpandedGenome

if TYPE_CHECKING:
    from clawdbot.evolution.openclaw_genome import OpenClawGenome


@dataclass
class MutationResult:
    """Result of applying mutations to a genome."""

    genome: ExpandedGenome
    mutations_applied: list[str]
    mutation_count: int

    def summary(self) -> str:
        """Get a summary of mutations applied."""
        if not self.mutations_applied:
            return "No mutations"
        return f"{self.mutation_count} mutations: {', '.join(self.mutations_applied)}"


@dataclass
class MutationBounds:
    """Bounds for mutable genome parameters."""

    # Strategy bounds
    task_preference_range: tuple[float, float] = (0.1, 1.0)
    risk_tolerance_range: tuple[float, float] = (0.0, 1.0)
    difficulty_preference_range: tuple[float, float] = (0.0, 1.0)

    # Economic bounds
    budget_per_cycle_range: tuple[float, float] = (0.01, 0.20)
    savings_rate_range: tuple[float, float] = (0.0, 0.5)
    replication_threshold_range: tuple[float, float] = (0.03, 0.20)
    child_inheritance_ratio_range: tuple[float, float] = (0.2, 0.6)

    # Model bounds
    model_preference_tier_range: tuple[int, int] = (1, 4)
    fallback_aggressiveness_range: tuple[float, float] = (0.0, 1.0)

    # Timing bounds
    cycle_interval_range: tuple[float, float] = (10.0, 120.0)
    task_timeout_multiplier_range: tuple[float, float] = (0.5, 2.0)

    # Meta bounds
    mutation_rate_range: tuple[float, float] = (0.01, 0.30)
    mutation_magnitude_range: tuple[float, float] = (0.02, 0.25)


class Mutator:
    """Applies mutations to genomes during reproduction.

    Mutations are the source of genetic variation in the population.
    Each trait has a chance to mutate based on the parent's mutation_rate,
    with magnitude controlled by mutation_magnitude.
    """

    def __init__(self, bounds: MutationBounds | None = None):
        """Initialize mutator.

        Args:
            bounds: Bounds for mutations. Uses default if None.
        """
        self.bounds = bounds or MutationBounds()

    def mutate(
        self,
        parent: ExpandedGenome,
        child_name: str,
        force_mutation: bool = False,
    ) -> MutationResult:
        """Create a mutated child genome from a parent.

        Args:
            parent: Parent genome to mutate
            child_name: Name for the child
            force_mutation: If True, ensure at least one mutation occurs

        Returns:
            MutationResult with mutated genome
        """
        # Deep copy parent
        child_data = copy.deepcopy(parent.to_dict())
        child_data["name"] = child_name
        child_data["generation"] = parent.generation + 1
        child_data["parent_name"] = parent.name

        mutations_applied = []

        # Helper to maybe mutate a float value
        def maybe_mutate_float(
            key: str,
            bounds: tuple[float, float],
        ) -> bool:
            if random.random() < parent.mutation_rate:
                old_val = child_data[key]
                delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
                new_val = max(bounds[0], min(bounds[1], old_val + delta))
                child_data[key] = new_val
                mutations_applied.append(f"{key}: {old_val:.4f} -> {new_val:.4f}")
                return True
            return False

        # Helper to maybe mutate an int value
        def maybe_mutate_int(
            key: str,
            bounds: tuple[int, int],
        ) -> bool:
            if random.random() < parent.mutation_rate:
                old_val = child_data[key]
                delta = random.choice([-1, 0, 1])
                new_val = max(bounds[0], min(bounds[1], old_val + delta))
                if new_val != old_val:
                    child_data[key] = new_val
                    mutations_applied.append(f"{key}: {old_val} -> {new_val}")
                    return True
            return False

        # Helper to maybe flip a boolean
        def maybe_mutate_bool(key: str) -> bool:
            if random.random() < parent.mutation_rate * 0.5:  # Half rate for booleans
                old_val = child_data[key]
                child_data[key] = not old_val
                mutations_applied.append(f"{key}: {old_val} -> {not old_val}")
                return True
            return False

        # Mutate task preferences
        task_prefs = child_data["task_preferences"]
        for task_type in list(task_prefs.keys()):
            if random.random() < parent.mutation_rate:
                old_val = task_prefs[task_type]
                delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
                new_val = max(
                    self.bounds.task_preference_range[0],
                    min(self.bounds.task_preference_range[1], old_val + delta),
                )
                task_prefs[task_type] = new_val
                mutations_applied.append(f"task_pref[{task_type}]: {old_val:.3f} -> {new_val:.3f}")

        # Mutate strategy genes
        maybe_mutate_float("risk_tolerance", self.bounds.risk_tolerance_range)
        maybe_mutate_float("difficulty_preference", self.bounds.difficulty_preference_range)

        # Mutate economic genes
        maybe_mutate_float("budget_per_cycle", self.bounds.budget_per_cycle_range)
        maybe_mutate_float("savings_rate", self.bounds.savings_rate_range)
        maybe_mutate_float("replication_threshold", self.bounds.replication_threshold_range)
        maybe_mutate_float("child_inheritance_ratio", self.bounds.child_inheritance_ratio_range)

        # Mutate model selection genes
        maybe_mutate_int("model_preference_tier", self.bounds.model_preference_tier_range)
        maybe_mutate_float("fallback_aggressiveness", self.bounds.fallback_aggressiveness_range)
        maybe_mutate_bool("prefer_local")

        # Mutate timing genes
        maybe_mutate_float("cycle_interval_seconds", self.bounds.cycle_interval_range)
        maybe_mutate_float("task_timeout_multiplier", self.bounds.task_timeout_multiplier_range)

        # Mutate meta genes (mutation rates themselves can mutate!)
        maybe_mutate_float("mutation_rate", self.bounds.mutation_rate_range)
        maybe_mutate_float("mutation_magnitude", self.bounds.mutation_magnitude_range)

        # Force at least one mutation if requested and none occurred
        if force_mutation and not mutations_applied:
            key = random.choice(["risk_tolerance", "difficulty_preference", "budget_per_cycle"])
            bounds_map = {
                "risk_tolerance": self.bounds.risk_tolerance_range,
                "difficulty_preference": self.bounds.difficulty_preference_range,
                "budget_per_cycle": self.bounds.budget_per_cycle_range,
            }
            old_val = child_data[key]
            delta = old_val * 0.1 * random.choice([-1, 1])
            bounds = bounds_map[key]
            new_val = max(bounds[0], min(bounds[1], old_val + delta))
            child_data[key] = new_val
            mutations_applied.append(f"{key}: {old_val:.4f} -> {new_val:.4f} (forced)")

        child = ExpandedGenome.from_dict(child_data)

        return MutationResult(
            genome=child,
            mutations_applied=mutations_applied,
            mutation_count=len(mutations_applied),
        )

    def crossover(
        self,
        parent1: ExpandedGenome,
        parent2: ExpandedGenome,
        child_name: str,
    ) -> MutationResult:
        """Create a child genome by crossing over two parents.

        Each trait is randomly inherited from one parent or the other.

        Args:
            parent1: First parent genome
            parent2: Second parent genome
            child_name: Name for the child

        Returns:
            MutationResult with crossed-over genome
        """
        data1 = parent1.to_dict()
        data2 = parent2.to_dict()

        child_data = {"name": child_name}
        child_data["generation"] = max(parent1.generation, parent2.generation) + 1
        child_data["parent_name"] = parent1.name  # Primary parent

        inherited_from = []

        # Inherit each trait from one parent or the other
        for key in data1:
            if key in ("name", "generation", "parent_name"):
                continue

            if key == "task_preferences":
                # Special handling for dict
                child_prefs = {}
                for task_type in data1[key]:
                    if random.random() < 0.5:
                        child_prefs[task_type] = data1[key].get(task_type, 0.5)
                        inherited_from.append(f"task_pref[{task_type}] from p1")
                    else:
                        child_prefs[task_type] = data2[key].get(task_type, 0.5)
                        inherited_from.append(f"task_pref[{task_type}] from p2")
                child_data[key] = child_prefs
            else:
                if random.random() < 0.5:
                    child_data[key] = data1[key]
                else:
                    child_data[key] = data2[key]

        child = ExpandedGenome.from_dict(child_data)

        # Apply mutation after crossover
        return self.mutate(child, child_name)


def get_mutator_for_genome(genome: ExpandedGenome | "OpenClawGenome") -> Mutator:
    """Get the appropriate mutator for a genome type.

    Args:
        genome: The genome to get a mutator for

    Returns:
        Appropriate Mutator instance
    """
    # Check if it's an OpenClaw genome
    try:
        from clawdbot.evolution.openclaw_genome import OpenClawGenome
        if isinstance(genome, OpenClawGenome):
            from clawdbot.openclaw_bot import OpenClawMutator
            return OpenClawMutator()
    except ImportError:
        pass

    return Mutator()
