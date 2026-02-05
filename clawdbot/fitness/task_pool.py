"""Task Pool - Task generation and sampling by difficulty."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from clawdbot.fitness.tasks import (
    Task,
    TaskTier,
    TaskType,
    MathTask,
    JSONTask,
    LogicTask,
    CodeTask,
)

if TYPE_CHECKING:
    from clawdbot.fitness.openclaw_tasks import OpenClawTask, OpenClawTaskType


@dataclass
class TierConfig:
    """Configuration for a task tier."""

    tier: TaskTier
    task_types: list[TaskType]
    difficulty_range: tuple[float, float]
    weight: float = 1.0  # Sampling weight


@dataclass
class TaskPoolConfig:
    """Configuration for the task pool."""

    tiers: list[TierConfig] = field(default_factory=list)
    default_difficulty: float = 0.5

    @classmethod
    def default(cls) -> TaskPoolConfig:
        """Create default task pool configuration."""
        return cls(
            tiers=[
                TierConfig(
                    tier=TaskTier.SIMPLE,
                    task_types=[TaskType.MATH, TaskType.JSON, TaskType.LOGIC],
                    difficulty_range=(0.0, 0.3),
                    weight=1.0,
                ),
                TierConfig(
                    tier=TaskTier.MEDIUM,
                    task_types=[TaskType.CODE],
                    difficulty_range=(0.3, 0.6),
                    weight=1.0,
                ),
                TierConfig(
                    tier=TaskTier.HARD,
                    task_types=[TaskType.CODE],
                    difficulty_range=(0.6, 0.85),
                    weight=0.5,
                ),
                TierConfig(
                    tier=TaskTier.EXPERT,
                    task_types=[TaskType.CODE],
                    difficulty_range=(0.85, 1.0),
                    weight=0.2,
                ),
            ]
        )


class TaskPool:
    """Pool for generating and sampling tasks.

    Manages task generation based on difficulty preferences and genome traits.
    """

    # Task generators by type
    _generators: dict[TaskType, Callable[[float], Task]] = {
        TaskType.MATH: MathTask.generate,
        TaskType.JSON: JSONTask.generate,
        TaskType.LOGIC: LogicTask.generate,
        TaskType.CODE: CodeTask.generate,
    }

    def __init__(self, config: TaskPoolConfig | None = None):
        """Initialize task pool.

        Args:
            config: Pool configuration. Uses default if None.
        """
        self.config = config or TaskPoolConfig.default()
        self._tier_lookup = {tc.tier: tc for tc in self.config.tiers}

    def sample(
        self,
        difficulty: float | None = None,
        preferences: dict[str, float] | None = None,
        tier: TaskTier | None = None,
        task_type: TaskType | None = None,
    ) -> Task:
        """Sample a task based on constraints.

        Args:
            difficulty: Target difficulty (0.0-1.0). Affects tier selection.
            preferences: Task type weights from genome {"math": 0.5, "code": 0.3, ...}
            tier: Specific tier to sample from
            task_type: Specific task type to generate

        Returns:
            Generated Task
        """
        # Determine difficulty
        if difficulty is None:
            difficulty = self.config.default_difficulty
        difficulty = max(0.0, min(1.0, difficulty))

        # Determine tier
        if tier is None:
            tier = self._select_tier(difficulty)

        tier_config = self._tier_lookup.get(tier)
        if tier_config is None:
            # Fallback to simple tier
            tier_config = self._tier_lookup.get(TaskTier.SIMPLE) or self.config.tiers[0]

        # Determine task type
        if task_type is None:
            task_type = self._select_task_type(tier_config, preferences)

        # Generate task with difficulty in tier's range
        low, high = tier_config.difficulty_range
        task_difficulty = low + (high - low) * random.random()

        # Use generator
        generator = self._generators.get(task_type)
        if generator is None:
            # Fallback to math
            generator = self._generators[TaskType.MATH]
            task_type = TaskType.MATH

        task = generator(task_difficulty)
        task.tier = tier
        task.task_type = task_type
        task.difficulty = task_difficulty

        return task

    def _select_tier(self, difficulty: float) -> TaskTier:
        """Select tier based on difficulty preference.

        Maps difficulty 0.0-1.0 to appropriate tier.
        """
        # Find tiers that match the difficulty range
        matching_tiers = []
        for tier_config in self.config.tiers:
            low, high = tier_config.difficulty_range
            # Include tier if difficulty overlaps its range
            if low <= difficulty <= high or (low <= difficulty + 0.2 and high >= difficulty - 0.2):
                matching_tiers.append(tier_config)

        if not matching_tiers:
            # Fallback: find closest tier
            best_tier = min(
                self.config.tiers,
                key=lambda tc: min(
                    abs(difficulty - tc.difficulty_range[0]),
                    abs(difficulty - tc.difficulty_range[1]),
                ),
            )
            return best_tier.tier

        # Weight by how well difficulty matches and tier weight
        weights = []
        for tc in matching_tiers:
            low, high = tc.difficulty_range
            center = (low + high) / 2
            distance = abs(difficulty - center)
            match_weight = 1.0 / (1.0 + distance)
            weights.append(match_weight * tc.weight)

        # Weighted random selection
        total = sum(weights)
        r = random.random() * total
        cumulative = 0.0
        for tc, w in zip(matching_tiers, weights):
            cumulative += w
            if r <= cumulative:
                return tc.tier

        return matching_tiers[-1].tier

    def _select_task_type(
        self,
        tier_config: TierConfig,
        preferences: dict[str, float] | None,
    ) -> TaskType:
        """Select task type from available types in tier.

        Uses genome preferences to weight selection.
        """
        available = tier_config.task_types
        if not available:
            return TaskType.MATH

        if preferences is None or not preferences:
            # Uniform random
            return random.choice(available)

        # Weight by preferences
        weights = []
        for task_type in available:
            pref_key = task_type.value
            weight = preferences.get(pref_key, 0.5)  # Default 0.5 if not specified
            weights.append(max(0.01, weight))  # Minimum weight to avoid zero

        # Weighted random selection
        total = sum(weights)
        r = random.random() * total
        cumulative = 0.0
        for task_type, w in zip(available, weights):
            cumulative += w
            if r <= cumulative:
                return task_type

        return available[-1]

    def sample_batch(
        self,
        count: int,
        difficulty: float | None = None,
        preferences: dict[str, float] | None = None,
    ) -> list[Task]:
        """Sample multiple tasks.

        Args:
            count: Number of tasks to sample
            difficulty: Target difficulty
            preferences: Task type preferences

        Returns:
            List of generated tasks
        """
        return [self.sample(difficulty=difficulty, preferences=preferences) for _ in range(count)]

    def get_tier_for_difficulty(self, difficulty: float) -> TaskTier:
        """Get the most appropriate tier for a difficulty level."""
        return self._select_tier(difficulty)

    @classmethod
    def register_generator(
        cls,
        task_type: TaskType,
        generator: Callable[[float], Task],
    ) -> None:
        """Register a custom task generator.

        Args:
            task_type: Type of task this generator creates
            generator: Function that takes difficulty (0.0-1.0) and returns Task
        """
        cls._generators[task_type] = generator


class OpenClawTaskPool:
    """Task pool specifically for OpenClaw tasks.

    Manages OpenClaw-specific task generation with workspace support.
    """

    def __init__(self, config: TaskPoolConfig | None = None):
        self.config = config or TaskPoolConfig.default()
        self._generators: dict[str, Callable[[float], Any]] = {}
        self._load_openclaw_generators()

    def _load_openclaw_generators(self) -> None:
        """Load OpenClaw task generators."""
        try:
            from clawdbot.fitness.openclaw_tasks import OPENCLAW_TASK_GENERATORS
            self._generators = {
                task_type.value: gen
                for task_type, gen in OPENCLAW_TASK_GENERATORS.items()
            }
        except ImportError:
            pass

    def sample(
        self,
        task_type: str | None = None,
        difficulty: float | None = None,
        preferences: dict[str, float] | None = None,
    ) -> "OpenClawTask":
        """Sample an OpenClaw task.

        Args:
            task_type: Specific task type (e.g., 'code_generation')
            difficulty: Target difficulty (0.0-1.0)
            preferences: Task type weights

        Returns:
            Generated OpenClawTask
        """
        from clawdbot.fitness.openclaw_tasks import generate_openclaw_task, OpenClawTaskType

        if difficulty is None:
            difficulty = 0.5

        if task_type is not None:
            # Convert string to enum
            try:
                oc_type = OpenClawTaskType(task_type)
            except ValueError:
                oc_type = None
        else:
            oc_type = None

        if oc_type is None and preferences:
            # Select based on preferences
            types = list(preferences.keys())
            weights = [max(0.01, preferences.get(t, 0.5)) for t in types]
            total = sum(weights)
            r = random.random() * total
            cumulative = 0.0
            for t, w in zip(types, weights):
                cumulative += w
                if r <= cumulative:
                    try:
                        oc_type = OpenClawTaskType(t)
                    except ValueError:
                        pass
                    break

        return generate_openclaw_task(task_type=oc_type, difficulty=difficulty)

    def sample_batch(
        self,
        count: int,
        difficulty: float | None = None,
        preferences: dict[str, float] | None = None,
    ) -> list["OpenClawTask"]:
        """Sample multiple OpenClaw tasks."""
        return [self.sample(difficulty=difficulty, preferences=preferences) for _ in range(count)]
