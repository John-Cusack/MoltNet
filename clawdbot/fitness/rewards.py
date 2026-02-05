"""Rewards - Calculate task rewards with difficulty scaling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clawdbot.fitness.tasks import Task, TaskTier, TaskType, TaskResult
from clawdbot.fitness.verifiers import VerificationResult


@dataclass
class RewardConfig:
    """Configuration for a reward structure."""

    base: float  # Base reward
    difficulty_bonus: float  # Additional reward per difficulty unit
    speed_bonus_threshold: float = 5.0  # Seconds for speed bonus
    speed_bonus_amount: float = 0.0  # Bonus for fast completion


@dataclass
class RewardStructure:
    """Complete reward configuration."""

    # Rewards by task type
    rewards: dict[str, RewardConfig] = field(default_factory=dict)

    # Tier multipliers
    tier_multipliers: dict[int, float] = field(default_factory=dict)

    @classmethod
    def default(cls) -> RewardStructure:
        """Create default reward structure."""
        return cls(
            rewards={
                # Simple tier
                "math": RewardConfig(base=0.001, difficulty_bonus=0.002),
                "json": RewardConfig(base=0.002, difficulty_bonus=0.003),
                "logic": RewardConfig(base=0.002, difficulty_bonus=0.003),
                # Medium tier
                "code": RewardConfig(base=0.005, difficulty_bonus=0.005, speed_bonus_amount=0.001),
                "humaneval": RewardConfig(
                    base=0.005, difficulty_bonus=0.005, speed_bonus_amount=0.001
                ),
                "mbpp": RewardConfig(base=0.005, difficulty_bonus=0.005, speed_bonus_amount=0.001),
                # Hard tier
                "humaneval_pro": RewardConfig(
                    base=0.015, difficulty_bonus=0.010, speed_bonus_amount=0.002
                ),
                "mbpp_pro": RewardConfig(
                    base=0.015, difficulty_bonus=0.010, speed_bonus_amount=0.002
                ),
                "algorithm": RewardConfig(
                    base=0.020, difficulty_bonus=0.015, speed_bonus_amount=0.003
                ),
                # Expert tier
                "swe_lite": RewardConfig(
                    base=0.050, difficulty_bonus=0.030, speed_bonus_amount=0.005
                ),
                "feature_impl": RewardConfig(
                    base=0.050, difficulty_bonus=0.030, speed_bonus_amount=0.005
                ),
            },
            tier_multipliers={
                TaskTier.SIMPLE.value: 1.0,
                TaskTier.MEDIUM.value: 1.5,
                TaskTier.HARD.value: 2.5,
                TaskTier.EXPERT.value: 5.0,
            },
        )

    @classmethod
    def openclaw_default(cls) -> RewardStructure:
        """Create reward structure for OpenClaw tasks (higher rewards)."""
        return cls(
            rewards={
                # OpenClaw-specific task types
                "code_generation": RewardConfig(
                    base=0.02, difficulty_bonus=0.02, speed_bonus_amount=0.005
                ),
                "bug_fix": RewardConfig(
                    base=0.03, difficulty_bonus=0.02, speed_bonus_amount=0.005
                ),
                "code_review": RewardConfig(
                    base=0.02, difficulty_bonus=0.015, speed_bonus_amount=0.003
                ),
                "refactoring": RewardConfig(
                    base=0.025, difficulty_bonus=0.02, speed_bonus_amount=0.005
                ),
                "algorithm": RewardConfig(
                    base=0.03, difficulty_bonus=0.025, speed_bonus_amount=0.005
                ),
                "file_organization": RewardConfig(
                    base=0.01, difficulty_bonus=0.01
                ),
                "data_extraction": RewardConfig(
                    base=0.015, difficulty_bonus=0.015
                ),
                "file_transformation": RewardConfig(
                    base=0.015, difficulty_bonus=0.015
                ),
                "log_analysis": RewardConfig(
                    base=0.02, difficulty_bonus=0.015
                ),
                "math_problem": RewardConfig(
                    base=0.01, difficulty_bonus=0.01
                ),
                "logic_puzzle": RewardConfig(
                    base=0.015, difficulty_bonus=0.015
                ),
                "text_analysis": RewardConfig(
                    base=0.015, difficulty_bonus=0.01
                ),
                "script_creation": RewardConfig(
                    base=0.025, difficulty_bonus=0.02, speed_bonus_amount=0.005
                ),
                "config_generation": RewardConfig(
                    base=0.015, difficulty_bonus=0.01
                ),
                "documentation": RewardConfig(
                    base=0.02, difficulty_bonus=0.015
                ),
            },
            tier_multipliers={
                1: 1.0,   # Simple
                2: 1.5,   # Medium
                3: 2.5,   # Hard
                4: 5.0,   # Expert
            },
        )


class RewardCalculator:
    """Calculate rewards for completed tasks."""

    def __init__(self, config: RewardStructure | None = None):
        """Initialize reward calculator.

        Args:
            config: Reward configuration. Uses default if None.
        """
        self.config = config or RewardStructure.default()

    def calculate(
        self,
        task: Task,
        result: TaskResult,
        verification: VerificationResult,
    ) -> float:
        """Calculate reward for a task result.

        Args:
            task: The completed task
            result: The task result
            verification: The verification result

        Returns:
            Reward amount in USD
        """
        # No reward for failed tasks
        if not verification.passed:
            # Partial credit for partial success
            if verification.score > 0:
                return self._calculate_partial_reward(task, result, verification)
            return 0.0

        # Get reward config for task type
        reward_key = task.task_type.value
        reward_config = self.config.rewards.get(reward_key)

        if reward_config is None:
            # Fallback to base math reward
            reward_config = self.config.rewards.get("math", RewardConfig(base=0.001, difficulty_bonus=0.001))

        # Base reward
        reward = reward_config.base

        # Difficulty bonus (scales with task difficulty 0.0-1.0)
        reward += reward_config.difficulty_bonus * task.difficulty

        # Speed bonus
        if reward_config.speed_bonus_amount > 0:
            if result.execution_time_seconds < reward_config.speed_bonus_threshold:
                reward += reward_config.speed_bonus_amount

        # Tier multiplier
        tier_mult = self.config.tier_multipliers.get(task.tier.value, 1.0)
        reward *= tier_mult

        return round(reward, 6)

    def _calculate_partial_reward(
        self,
        task: Task,
        result: TaskResult,
        verification: VerificationResult,
    ) -> float:
        """Calculate partial reward for partially correct results.

        Args:
            task: The task
            result: The result
            verification: Verification with partial score

        Returns:
            Partial reward amount
        """
        # Get full reward
        full_verification = VerificationResult(passed=True, score=1.0, feedback="")
        full_reward = self.calculate(task, result, full_verification)

        # Scale by verification score
        partial_reward = full_reward * verification.score * 0.5  # 50% max for partial

        return round(partial_reward, 6)

    def estimate_reward(
        self,
        task_type: TaskType,
        tier: TaskTier,
        difficulty: float,
    ) -> tuple[float, float]:
        """Estimate potential reward range for a task.

        Args:
            task_type: Type of task
            tier: Task tier
            difficulty: Task difficulty

        Returns:
            Tuple of (min_reward, max_reward)
        """
        reward_key = task_type.value
        reward_config = self.config.rewards.get(reward_key)

        if reward_config is None:
            return 0.001, 0.002

        tier_mult = self.config.tier_multipliers.get(tier.value, 1.0)

        min_reward = reward_config.base * tier_mult
        max_reward = (
            reward_config.base
            + reward_config.difficulty_bonus * difficulty
            + reward_config.speed_bonus_amount
        ) * tier_mult

        return round(min_reward, 6), round(max_reward, 6)

    def get_roi_estimate(
        self,
        task_type: TaskType,
        tier: TaskTier,
        estimated_api_cost: float,
        success_probability: float,
    ) -> float:
        """Estimate ROI for attempting a task type.

        Args:
            task_type: Type of task
            tier: Task tier
            estimated_api_cost: Estimated API cost to complete task
            success_probability: Estimated probability of success (0.0-1.0)

        Returns:
            Expected ROI (expected_reward / cost - 1)
        """
        _, max_reward = self.estimate_reward(task_type, tier, 0.7)
        expected_reward = max_reward * success_probability

        if estimated_api_cost <= 0:
            return float("inf") if expected_reward > 0 else 0.0

        roi = (expected_reward / estimated_api_cost) - 1
        return roi
