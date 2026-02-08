"""Payout calculation for Task Shop assignments."""

from __future__ import annotations

# Base payouts per benchmark
BASE_PAYOUTS: dict[str, float] = {
    "humaneval": 0.025,
    "mbpp": 0.020,
    "gsm8k": 0.010,
    "math": 0.015,
    "qasper": 0.015,
    "sciq": 0.010,
}

# Difficulty multipliers (maps difficulty 0.0-1.0 to multiplier)
DIFFICULTY_BRACKETS: list[tuple[float, float]] = [
    (0.2, 0.6),   # Easy: 0.6x
    (0.4, 1.0),   # Medium: 1.0x
    (0.6, 1.5),   # Hard: 1.5x
    (0.8, 2.0),   # Very hard: 2.0x
    (1.0, 2.5),   # Expert: 2.5x
]

# Cycle decay factor: rewards faster solutions
CYCLE_DECAY: float = 0.9


def get_difficulty_multiplier(difficulty: float) -> float:
    """Get payout multiplier based on task difficulty."""
    for threshold, multiplier in DIFFICULTY_BRACKETS:
        if difficulty <= threshold:
            return multiplier
    return DIFFICULTY_BRACKETS[-1][1]


def calculate_payout(
    benchmark: str,
    difficulty: float,
    score: float,
    cycles_spent: int,
) -> float:
    """Calculate payout for a completed assignment.

    Formula: base_payout * difficulty_multiplier * score * cycle_decay

    Args:
        benchmark: Benchmark name (humaneval, mbpp, gsm8k, math)
        difficulty: Task difficulty (0.0-1.0)
        score: Verification score (0.0-1.0)
        cycles_spent: Number of cycles the bot spent

    Returns:
        Payout amount in tokens
    """
    base = BASE_PAYOUTS.get(benchmark, 0.015)
    diff_mult = get_difficulty_multiplier(difficulty)
    decay = CYCLE_DECAY ** (cycles_spent - 1)

    return base * diff_mult * score * decay
