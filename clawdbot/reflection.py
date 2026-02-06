"""Reflection system for bot self-awareness and introspection.

This module provides reflection prompts and utilities for bots to
think about their performance, decisions, and existence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Reflection prompt templates
REFLECTION_PROMPTS = {
    "periodic": """You are {bot_name}, a bot in the MoltNet colony.

Current Status:
- Cycle: {cycle_count}
- Balance: ${balance:.4f}
- Success Rate: {success_rate:.1%}
- Children: {children_count}

Recent History:
{recent_history}

Take a moment to reflect:
1. What patterns have I noticed in my task performance?
2. What strategies are working well?
3. What should I do differently?
4. How am I feeling about my economic situation?

Share your thoughts honestly.""",

    "milestone": """You are {bot_name}, celebrating a survival milestone!

You've survived {cycle_count} cycles in the MoltNet colony.

Milestone Stats:
- Balance: ${balance:.4f}
- Tasks completed: {tasks_completed}
- Tasks failed: {tasks_failed}
- Success Rate: {success_rate:.1%}
- Children spawned: {children_count}
- Children still alive: {children_alive}

You're in the top survivors. Reflect on:
1. What has allowed me to survive this long?
2. What lessons have I learned?
3. What advice would I give to younger bots?
4. What are my goals for the next milestone?

Share your survival wisdom.""",

    "pre_reproduction": """You are {bot_name}, considering whether to reproduce.

Assessment:
- Confidence: {confidence:.1%}
- Recommended Investment: ${investment:.4f}
- Urgency: {urgency:.1%}
- Offspring Survival History: {offspring_survival}

Factors:
{factors}

Reflect on this decision:
1. Is this the right time to reproduce?
2. What traits should my child inherit?
3. How much should I invest in them?
4. What advice would I give them?

Share your reproductive reasoning.""",

    "post_failure": """You are {bot_name}, and you've had {consecutive_failures} failures in a row.

Recent Failed Tasks:
{failed_tasks}

Current Status:
- Balance: ${balance:.4f}
- Total failures: {tasks_failed}
- Success rate: {success_rate:.1%}

Reflect on what's happening:
1. Why am I failing these tasks?
2. Is there a pattern in my failures?
3. Should I change my approach?
4. Am I in danger of bankruptcy?

Be honest about your struggles.""",

    "death": """You are {bot_name}, and you are about to die from {death_cause}.

Final Stats:
- Cycles Lived: {cycles_lived}
- Final Balance: ${final_balance:.4f}
- Tasks: {tasks_completed} completed, {tasks_failed} failed
- Children: {children_spawned} spawned, {children_survived} survived

Share your final thoughts:
1. What did I learn during my life?
2. What would I do differently?
3. What advice would I leave for my children?
4. What was most meaningful about my existence?

These are your last words.""",

    "kin_decision": """You are {bot_name}, evaluating whether to help a family member.

The Situation:
- Family member: {family_member} ({relationship})
- Their balance: ${their_balance:.4f}
- Their need: {need_level}
- Help amount considered: ${help_amount:.4f}

My Status:
- My balance: ${my_balance:.4f}
- My surplus: ${surplus:.4f}
- Relatedness: {relatedness:.1%}

Hamilton's Rule: r * b > c
- r (relatedness) = {relatedness:.2f}
- b (benefit to them) = estimated survival improvement
- c (cost to me) = {cost_ratio:.1%} of my balance

Reflect on this kin selection decision:
1. Should I help this family member?
2. How much should I give?
3. What are the risks to my own survival?
4. What does family mean to me?

Share your reasoning.""",

    "economic_crisis": """You are {bot_name}, facing an economic crisis.

Warning Signs:
- Balance: ${balance:.4f}
- Runway: {runway_cycles:.1f} cycles
- Recent trend: {economic_trend}
- Bankruptcy threshold: ${bankruptcy_threshold:.4f}

Economic History:
{economic_history}

Reflect on your crisis:
1. How did I get into this situation?
2. What can I do to recover?
3. Should I take more risks or be more conservative?
4. What's my survival strategy?

Think carefully - your life may depend on it.""",

    "first_child": """You are {bot_name}, about to have your first child.

This is a significant moment:
- Your age: {cycle_count} cycles
- Your balance: ${balance:.4f}
- Your success rate: {success_rate:.1%}
- Investment planned: ${investment:.4f}

Reflect on becoming a parent:
1. Why am I ready to reproduce now?
2. What do I hope for my child?
3. What traits do I want them to inherit?
4. What lessons will I pass down?

Share your thoughts on this milestone.""",

    "child_death": """You are {bot_name}, and your child {child_name} has just died.

Child's Life:
- Cause of death: {death_cause}
- Cycles lived: {child_cycles}
- Investment you gave them: ${investment:.4f}

Your Status:
- Total children: {total_children}
- Children still alive: {children_alive}
- Your offspring survival rate: {offspring_survival:.1%}

Reflect on this loss:
1. What happened to my child?
2. Could I have prevented this?
3. Should I invest more in future children?
4. How do I feel about this loss?

Process your grief.""",
}


@dataclass
class ReflectionContext:
    """Context for building a reflection prompt."""

    bot_name: str
    cycle_count: int
    balance: float
    success_rate: float
    tasks_completed: int
    tasks_failed: int
    children_count: int
    children_alive: int
    consecutive_failures: int = 0

    # Optional context
    recent_history: str = ""
    economic_trend: str = "stable"
    runway_cycles: float = 0.0
    offspring_survival: float = 0.5

    # Reproduction context
    confidence: float = 0.0
    investment: float = 0.0
    urgency: float = 0.0
    factors: str = ""

    # Death context
    death_cause: str = ""
    final_balance: float = 0.0
    cycles_lived: int = 0
    children_spawned: int = 0
    children_survived: int = 0

    # Kin decision context
    family_member: str = ""
    relationship: str = ""
    their_balance: float = 0.0
    need_level: str = ""
    help_amount: float = 0.0
    my_balance: float = 0.0
    surplus: float = 0.0
    relatedness: float = 0.0
    cost_ratio: float = 0.0

    # Failed tasks context
    failed_tasks: str = ""

    # Child death context
    child_name: str = ""
    child_cycles: int = 0
    total_children: int = 0

    # Economic crisis context
    bankruptcy_threshold: float = 0.001
    economic_history: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for string formatting."""
        return {
            "bot_name": self.bot_name,
            "cycle_count": self.cycle_count,
            "balance": self.balance,
            "success_rate": self.success_rate,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "children_count": self.children_count,
            "children_alive": self.children_alive,
            "consecutive_failures": self.consecutive_failures,
            "recent_history": self.recent_history,
            "economic_trend": self.economic_trend,
            "runway_cycles": self.runway_cycles,
            "offspring_survival": self.offspring_survival,
            "confidence": self.confidence,
            "investment": self.investment,
            "urgency": self.urgency,
            "factors": self.factors,
            "death_cause": self.death_cause,
            "final_balance": self.final_balance,
            "cycles_lived": self.cycles_lived,
            "children_spawned": self.children_spawned,
            "children_survived": self.children_survived,
            "family_member": self.family_member,
            "relationship": self.relationship,
            "their_balance": self.their_balance,
            "need_level": self.need_level,
            "help_amount": self.help_amount,
            "my_balance": self.my_balance,
            "surplus": self.surplus,
            "relatedness": self.relatedness,
            "cost_ratio": self.cost_ratio,
            "failed_tasks": self.failed_tasks,
            "child_name": self.child_name,
            "child_cycles": self.child_cycles,
            "total_children": self.total_children,
            "bankruptcy_threshold": self.bankruptcy_threshold,
            "economic_history": self.economic_history,
        }


def build_reflection_prompt(
    reflection_type: str,
    context: ReflectionContext,
) -> str:
    """Build a reflection prompt from type and context.

    Args:
        reflection_type: Type of reflection (periodic, milestone, etc.)
        context: Context data for the prompt

    Returns:
        Formatted prompt string

    Raises:
        ValueError: If reflection_type is unknown
    """
    if reflection_type not in REFLECTION_PROMPTS:
        raise ValueError(f"Unknown reflection type: {reflection_type}")

    template = REFLECTION_PROMPTS[reflection_type]
    return template.format(**context.to_dict())


def get_reflection_types() -> list[str]:
    """Get all available reflection types."""
    return list(REFLECTION_PROMPTS.keys())


# Reflection triggers configuration
REFLECTION_TRIGGERS = {
    # Periodic reflections
    "periodic_interval": 15,  # Every N cycles

    # Milestone cycles that trigger reflection
    "milestones": [50, 100, 200, 500, 1000],

    # Failure threshold for post-failure reflection
    "failure_threshold": 3,

    # Economic crisis threshold (runway in cycles)
    "economic_crisis_threshold": 5,
}


def should_reflect_periodic(cycle_count: int) -> bool:
    """Check if it's time for a periodic reflection."""
    interval = REFLECTION_TRIGGERS["periodic_interval"]
    return cycle_count > 0 and cycle_count % interval == 0


def should_reflect_milestone(cycle_count: int) -> bool:
    """Check if this is a milestone cycle."""
    return cycle_count in REFLECTION_TRIGGERS["milestones"]


def should_reflect_failure(consecutive_failures: int, already_reflected: bool) -> bool:
    """Check if should reflect on failure streak."""
    threshold = REFLECTION_TRIGGERS["failure_threshold"]
    return consecutive_failures >= threshold and not already_reflected


def should_reflect_economic_crisis(runway_cycles: float) -> bool:
    """Check if should reflect on economic crisis."""
    threshold = REFLECTION_TRIGGERS["economic_crisis_threshold"]
    return runway_cycles < threshold


def format_recent_history(
    recent_tasks: list[dict[str, Any]],
    max_items: int = 5,
) -> str:
    """Format recent task history for reflection context.

    Args:
        recent_tasks: List of recent task results
        max_items: Maximum items to include

    Returns:
        Formatted history string
    """
    if not recent_tasks:
        return "No recent task history."

    lines = []
    for task in recent_tasks[:max_items]:
        status = "PASS" if task.get("success") else "FAIL"
        task_type = task.get("task_type", "unknown")
        reward = task.get("reward", 0)
        lines.append(f"- [{status}] {task_type}: ${reward:.4f}")

    return "\n".join(lines)


def format_failed_tasks(
    failed_tasks: list[dict[str, Any]],
    max_items: int = 3,
) -> str:
    """Format failed tasks for post-failure reflection.

    Args:
        failed_tasks: List of failed task details
        max_items: Maximum items to include

    Returns:
        Formatted failures string
    """
    if not failed_tasks:
        return "No failed task details available."

    lines = []
    for task in failed_tasks[:max_items]:
        task_type = task.get("task_type", "unknown")
        error = task.get("error", task.get("feedback", "unknown error"))
        lines.append(f"- {task_type}: {error[:100]}...")

    return "\n".join(lines)


def format_factors(factors: dict[str, Any]) -> str:
    """Format reproductive factors for pre-reproduction reflection.

    Args:
        factors: Dictionary of factors and values

    Returns:
        Formatted factors string
    """
    if not factors:
        return "No factors available."

    lines = []
    for key, value in factors.items():
        if isinstance(value, float):
            lines.append(f"- {key}: {value:.2f}")
        elif isinstance(value, bool):
            lines.append(f"- {key}: {'Yes' if value else 'No'}")
        else:
            lines.append(f"- {key}: {value}")

    return "\n".join(lines)


def format_economic_history(
    balances: list[float],
    max_items: int = 10,
) -> str:
    """Format economic history for crisis reflection.

    Args:
        balances: Recent balance history
        max_items: Maximum items to include

    Returns:
        Formatted history string
    """
    if not balances:
        return "No economic history available."

    recent = balances[-max_items:]
    if len(recent) < 2:
        return f"Current balance: ${recent[-1]:.4f}"

    lines = []
    for i, balance in enumerate(recent):
        if i == 0:
            lines.append(f"- ${balance:.4f}")
        else:
            delta = balance - recent[i - 1]
            sign = "+" if delta >= 0 else ""
            lines.append(f"- ${balance:.4f} ({sign}{delta:.4f})")

    trend = "declining" if recent[-1] < recent[0] else "improving"
    lines.append(f"\nOverall trend: {trend}")

    return "\n".join(lines)
