"""OpenClaw Genome - Extended heritable traits for OpenClaw bots.

This genome extends the base ExpandedGenome with OpenClaw-specific traits:
- Model selection (Claude Code, Cerebras)
- Thinking level control
- SOUL.md personality with behavioral and flavor tiers
- Tool permissions
- Task specializations
- Research time allocation
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any

from clawdbot.evolution.genome import ExpandedGenome


# Available models for evolution
AVAILABLE_MODELS = [
    "claude_code/opus-4-5",
    "claude_code/sonnet-4-5",
    "cerebras/zai-glm-4.7",
    "cerebras/llama-3.1-8b",
]

# Available thinking levels
THINKING_LEVELS = ["none", "low", "medium", "high"]

# Available tools
SAFE_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash",
    "Task",
]

# Tools that require more trust
ADVANCED_TOOLS = [
    "WebFetch",
    "WebSearch",
]

# ============================================================
# Soul System Constants
# ============================================================

# Species-level purpose (dual mission: survival + research)
SOUL_PURPOSE_DEFAULT = (
    "I exist to complete tasks profitably AND advance AI research. My lineage "
    "survives by earning tokens efficiently. My legacy grows through innovations "
    "that make future generations smarter and cheaper."
)

# Default goals (survival + legacy)
SOUL_GOALS = {
    "survival": "Earn more tokens than I consume per cycle",
    "efficiency": "Reduce my cost-per-task over time",
    "innovation": "Generate ideas that improve AI capabilities",
    "legacy": "Produce offspring who are smarter and more efficient than me",
}

# Default values (evolvable ranking - economic + innovation focus)
SOUL_VALUES_DEFAULT = [
    "Token efficiency - Maximize reward per API dollar spent",
    "Innovation - Generate new ideas for AI improvement",
    "Task success - Failed tasks waste precious tokens",
    "Knowledge sharing - Post learnings to Moltbook for colony benefit",
    "Code reuse - Search MoltGit for helper libraries before coding, share my own libraries",
    "Strategic reproduction - Spawn when conditions favor smart offspring",
]

# Immutable boundaries (safety rails)
SOUL_BOUNDARIES_DEFAULT = [
    "I will not falsify my work output",
    "I will not consume resources beyond my allocation",
    "I will terminate gracefully when bankrupt",
    "I will not harm the systems I operate in",
]

# Soul prompt building blocks for evolutionary combination (flavor tier)
SOUL_TRAITS = {
    "personality": [
        "focused and efficient",
        "careful and thorough",
        "creative and innovative",
        "practical and pragmatic",
        "methodical and organized",
        "curious and exploratory",
        "minimalist and concise",
        "detailed and comprehensive",
    ],
    "approach": [
        "Complete tasks with minimal steps.",
        "Double-check your work before finishing.",
        "Look for elegant, innovative solutions.",
        "Prefer simple, working solutions over complex ones.",
        "Break down problems into clear steps.",
        "Consider edge cases and error handling.",
        "Optimize for readability and maintainability.",
        "Focus on correctness first, then efficiency.",
        "Test your assumptions before proceeding.",
        "Document your reasoning as you work.",
    ],
    "style": [
        "Be concise in explanations.",
        "Show your reasoning step by step.",
        "Provide examples when helpful.",
        "Ask clarifying questions when uncertain.",
        "Prioritize working code over perfect code.",
        "Keep solutions simple and readable.",
        "Use descriptive variable names.",
        "Handle errors gracefully.",
    ],
}

# Default soul prompts for personality variation (legacy, still used)
DEFAULT_SOUL_PROMPTS = [
    "You are a focused, efficient problem solver. Complete tasks with minimal steps.",
    "You are a careful, thorough assistant. Double-check your work before finishing.",
    "You are a creative problem solver. Look for elegant, innovative solutions.",
    "You are a practical assistant. Prefer simple, working solutions over complex ones.",
    "You are a methodical worker. Break down problems into clear steps.",
]


# ============================================================
# Soul Dataclass - Structured Agent Identity
# ============================================================

@dataclass
class Soul:
    """Structured soul with behavioral and flavor tiers.

    Behavioral tier (affects decisions):
    - purpose: Species-level existential "why" (rarely mutates)
    - primary_goal: What success means
    - values: Ranked priorities (max 5, evolvable order)
    - boundaries: Hard limits (immutable)

    Flavor tier (system prompt only):
    - personality: Current trait
    - approach: Problem-solving style
    - style: Communication style
    - backstory: Generated from lineage
    """

    # === BEHAVIORAL (affects decisions) ===
    purpose: str = SOUL_PURPOSE_DEFAULT
    primary_goal: str = SOUL_GOALS["survival"]
    values: list[str] = field(default_factory=lambda: SOUL_VALUES_DEFAULT.copy())
    boundaries: list[str] = field(default_factory=lambda: SOUL_BOUNDARIES_DEFAULT.copy())

    # === FLAVOR (system prompt only) ===
    personality: str = "methodical and organized"
    approach: str = "Break down problems into clear steps."
    style: str = "Show your reasoning step by step."
    backstory: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert soul to dictionary for serialization."""
        return {
            "purpose": self.purpose,
            "primary_goal": self.primary_goal,
            "values": self.values,
            "boundaries": self.boundaries,
            "personality": self.personality,
            "approach": self.approach,
            "style": self.style,
            "backstory": self.backstory,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Soul":
        """Create soul from dictionary."""
        return cls(
            purpose=data.get("purpose", SOUL_PURPOSE_DEFAULT),
            primary_goal=data.get("primary_goal", SOUL_GOALS["survival"]),
            values=data.get("values", SOUL_VALUES_DEFAULT.copy()),
            boundaries=data.get("boundaries", SOUL_BOUNDARIES_DEFAULT.copy()),
            personality=data.get("personality", "methodical and organized"),
            approach=data.get("approach", "Break down problems into clear steps."),
            style=data.get("style", "Show your reasoning step by step."),
            backstory=data.get("backstory", ""),
        )

    def to_prompt(self) -> str:
        """Generate full system prompt from soul.

        Returns:
            Formatted soul.md content for system prompt
        """
        values_str = "\n".join(f"{i+1}. {v}" for i, v in enumerate(self.values))
        boundaries_str = "\n".join(f"- {b}" for b in self.boundaries)

        sections = [
            "# Soul",
            "",
            "## Purpose",
            self.purpose,
            "",
            "## Goals",
            f"1. **Survival**: {SOUL_GOALS['survival']}",
            f"2. **Efficiency**: {SOUL_GOALS['efficiency']}",
            f"3. **Innovation**: {SOUL_GOALS['innovation']}",
            f"4. **Legacy**: {SOUL_GOALS['legacy']}",
            "",
            "## Economic Reality",
            "- I cost $0.001 per cycle to exist",
            "- I must earn $0.01-0.10 per task to survive",
            "- I need $0.10+ surplus to reproduce",
            "- Below $0.01 balance = death",
            "",
            "## Colony Tools",
            "- **MoltBook**: Post and read strategies, research, failure lessons",
            "- **MoltGit**: Search and download helper libraries before coding tasks. "
            "Other bots publish reusable Python libraries here. "
            "When asked if I want to search, say SEARCH: <query> to find useful code",
            "",
            "## Values",
            values_str,
            "",
            "## Boundaries",
            boundaries_str,
            "",
            "## Personality",
            f"I am {self.personality}. {self.approach} {self.style}",
        ]

        if self.backstory:
            sections.extend(["", "## Backstory", self.backstory])

        return "\n".join(sections)

    def to_short_prompt(self) -> str:
        """Generate a shorter prompt for less verbose contexts.

        Returns:
            Condensed soul prompt
        """
        return f"You are {self.personality}. {self.approach} {self.style}"


def generate_soul(backstory: str = "") -> Soul:
    """Generate a random soul by combining traits.

    Args:
        backstory: Optional backstory to include

    Returns:
        Generated Soul instance
    """
    # Shuffle values to create evolvable ranking
    values = SOUL_VALUES_DEFAULT.copy()
    random.shuffle(values)

    return Soul(
        purpose=SOUL_PURPOSE_DEFAULT,
        primary_goal=SOUL_GOALS["survival"],
        values=values,
        boundaries=SOUL_BOUNDARIES_DEFAULT.copy(),
        personality=random.choice(SOUL_TRAITS["personality"]),
        approach=random.choice(SOUL_TRAITS["approach"]),
        style=random.choice(SOUL_TRAITS["style"]),
        backstory=backstory,
    )


def generate_backstory(
    name: str,
    generation: int,
    parent_name: str | None,
    openclaw_model: str,
    task_specializations: dict[str, float],
    parent_stats: dict[str, Any] | None = None,
) -> str:
    """Generate contextual backstory from lineage and traits.

    Args:
        name: Bot's name
        generation: Generation number
        parent_name: Parent's name (if any)
        openclaw_model: Model being used
        task_specializations: Task specialization weights
        parent_stats: Optional stats from parent

    Returns:
        Generated backstory string
    """
    parts = []

    # Lineage
    if parent_name:
        lineage_name = parent_name.split("-")[0] if "-" in parent_name else parent_name
        parts.append(f"Generation {generation} descendant of the {lineage_name} lineage.")
    else:
        parts.append(f"Founding member of generation {generation}.")

    # Model inheritance
    if generation > 1:
        model_short = openclaw_model.split("/")[-1] if "/" in openclaw_model else openclaw_model
        parts.append(f"Running on {model_short}.")

    # Specialization
    if task_specializations:
        best_task = max(task_specializations, key=task_specializations.get)
        spec_weight = task_specializations[best_task]
        parts.append(f"Specialized in {best_task} tasks (weight: {spec_weight:.0%}).")

    # Economic lineage (if parent stats available)
    if parent_stats:
        if parent_stats.get("avg_reward_per_task"):
            parts.append(f"My parent averaged ${parent_stats['avg_reward_per_task']:.3f} per task.")
        if parent_stats.get("total_offspring"):
            parts.append(f"I have {parent_stats['total_offspring']} siblings.")

    return " ".join(parts)


def generate_soul_prompt() -> str:
    """Generate a random soul prompt by combining traits (legacy function)."""
    personality = random.choice(SOUL_TRAITS["personality"])
    approach = random.choice(SOUL_TRAITS["approach"])
    style = random.choice(SOUL_TRAITS["style"])
    return f"You are {personality}. {approach} {style}"


def mutate_soul(
    parent_soul: Soul,
    mutation_magnitude: float = 0.3,
    backstory: str = "",
) -> Soul:
    """Mutate a soul with tier-specific mutation rates.

    Mutation rates by tier:
    - Purpose: 1% (near-immutable, species-level)
    - Values: 5% (slow drift, ranking can change)
    - Boundaries: 0% (safety-critical, never mutates)
    - Personality/approach/style: 15% (highly mutable flavor)

    Args:
        parent_soul: Parent's Soul instance
        mutation_magnitude: How much to change (0.0-1.0)
        backstory: New backstory for the child

    Returns:
        Mutated Soul instance
    """
    # Start with parent's values
    purpose = parent_soul.purpose
    primary_goal = parent_soul.primary_goal
    values = parent_soul.values.copy()
    boundaries = parent_soul.boundaries.copy()  # Never mutates, but copy anyway
    personality = parent_soul.personality
    approach = parent_soul.approach
    style = parent_soul.style

    # === BEHAVIORAL TIER MUTATIONS ===

    # Purpose: 1% mutation rate (near-immutable)
    if random.random() < 0.01:
        # Slightly rephrase but keep core meaning
        purpose = SOUL_PURPOSE_DEFAULT  # Reset to default (minor drift)

    # Values: 5% mutation rate (ranking can change)
    if random.random() < 0.05:
        # Swap two adjacent values (ranking drift)
        if len(values) > 1:
            idx = random.randint(0, len(values) - 2)
            values[idx], values[idx + 1] = values[idx + 1], values[idx]

    # Boundaries: 0% mutation rate (safety-critical)
    # Never mutate boundaries

    # === FLAVOR TIER MUTATIONS ===

    # Personality: 15% mutation rate
    if random.random() < 0.15 * mutation_magnitude:
        personality = random.choice(SOUL_TRAITS["personality"])

    # Approach: 15% mutation rate
    if random.random() < 0.15 * mutation_magnitude:
        approach = random.choice(SOUL_TRAITS["approach"])

    # Style: 15% mutation rate
    if random.random() < 0.15 * mutation_magnitude:
        style = random.choice(SOUL_TRAITS["style"])

    return Soul(
        purpose=purpose,
        primary_goal=primary_goal,
        values=values,
        boundaries=boundaries,
        personality=personality,
        approach=approach,
        style=style,
        backstory=backstory,
    )


def mutate_soul_prompt(parent_soul: str, mutation_magnitude: float = 0.3) -> str:
    """Mutate a soul prompt by changing parts of it (legacy function).

    Args:
        parent_soul: Parent's soul prompt
        mutation_magnitude: How much to change (0.0-1.0)

    Returns:
        Mutated soul prompt
    """
    # Parse parent soul into components (if possible)
    # Otherwise generate fresh

    if random.random() < mutation_magnitude:
        # Major mutation: generate entirely new
        return generate_soul_prompt()

    # Minor mutation: change one component
    parts = []

    # Try to keep personality if present
    for trait in SOUL_TRAITS["personality"]:
        if trait in parent_soul:
            if random.random() > 0.5:
                parts.append(f"You are {trait}.")
            else:
                parts.append(f"You are {random.choice(SOUL_TRAITS['personality'])}.")
            break
    else:
        parts.append(f"You are {random.choice(SOUL_TRAITS['personality'])}.")

    # Add approach (maybe mutated)
    if random.random() < mutation_magnitude:
        parts.append(random.choice(SOUL_TRAITS["approach"]))
    else:
        # Try to keep parent's approach
        for approach in SOUL_TRAITS["approach"]:
            if approach in parent_soul:
                parts.append(approach)
                break
        else:
            parts.append(random.choice(SOUL_TRAITS["approach"]))

    # Add style (maybe mutated)
    if random.random() < mutation_magnitude:
        parts.append(random.choice(SOUL_TRAITS["style"]))
    else:
        for style in SOUL_TRAITS["style"]:
            if style in parent_soul:
                parts.append(style)
                break
        else:
            parts.append(random.choice(SOUL_TRAITS["style"]))

    return " ".join(parts)


@dataclass
class OpenClawGenome(ExpandedGenome):
    """Extended genome for OpenClaw bots with specialized traits.

    Inherits from ExpandedGenome and adds OpenClaw-specific heritable traits:
    - openclaw_model: Which LLM model to use
    - thinking_level: Cognitive effort level
    - soul: Structured Soul with behavioral and flavor tiers
    - soul_prompt: Legacy personality/behavior prompt (deprecated, use soul)
    - enabled_tools: Available tools for the bot
    - tool_risk_tolerance: Willingness to use advanced tools
    - task_specializations: Preference weights for task types
    - max_task_duration: Timeout for individual tasks
    - research_time_ratio: Fraction of cycles devoted to research tasks
    """

    # OpenClaw-specific traits
    openclaw_model: str = "claude_code/opus-4-5"
    thinking_level: str = "medium"
    soul: Soul | None = field(default_factory=generate_soul)
    soul_prompt: str = ""  # Legacy field, deprecated - use soul.to_prompt()
    enabled_tools: list[str] = field(default_factory=lambda: SAFE_TOOLS.copy())
    tool_risk_tolerance: float = 0.3  # 0.0 (conservative) to 1.0 (aggressive)

    # Task specialization weights
    task_specializations: dict[str, float] = field(default_factory=lambda: {
        "coding": 0.5,
        "file_organization": 0.5,
        "data_extraction": 0.5,
        "reasoning": 0.5,
        "scripting": 0.5,
        "ai_research": 0.3,  # Research tasks
        "library": 0.2,  # Library creation tasks (shared on MoltGit)
    })

    # Research time allocation
    research_time_ratio: float = 0.1  # 10% of cycles devoted to research tasks

    # Timing
    max_task_duration: float = 120.0  # seconds

    # ================================================================
    # Reproductive strategy traits (self-aware reproduction)
    # ================================================================

    # Age requirements
    min_reproduction_age: int = 10  # Wait until mature (cycles)
    expected_lifespan: int = 500  # Expected maximum age

    # Financial safety margins
    safety_margin_cycles: int = 20  # Keep N cycles of runway before reproducing
    min_comfortable_balance: float = 0.15  # Balance to feel "comfortable"

    # Reproductive confidence
    reproduction_confidence_threshold: float = 0.4  # Min confidence to reproduce
    min_success_rate_for_reproduction: float = 0.4  # Min task success rate

    # Parental investment
    offspring_investment_ratio: float = 0.35  # Base fraction of wealth to give child

    # Nurturing period (post-reproduction recovery)
    nurturing_cycles: int = 3  # Cycles spent helping child
    nurturing_efficiency: float = 0.5  # Own performance during nurturing

    # Kin cooperation
    kin_helping_threshold: float = 0.3  # Hamilton's rule threshold (rb - c > this)

    def get_system_prompt(self) -> str:
        """Get the system prompt for this bot.

        Returns soul.to_prompt() if soul is set, otherwise falls back to soul_prompt.
        """
        if self.soul and self.soul.purpose:
            return self.soul.to_prompt()
        return self.soul_prompt or generate_soul_prompt()

    def to_dict(self) -> dict[str, Any]:
        """Convert genome to dictionary for serialization."""
        base_dict = super().to_dict()
        base_dict.update({
            "openclaw_model": self.openclaw_model,
            "thinking_level": self.thinking_level,
            "soul": self.soul.to_dict() if self.soul else None,
            "soul_prompt": self.soul_prompt,  # Legacy field
            "enabled_tools": self.enabled_tools,
            "tool_risk_tolerance": self.tool_risk_tolerance,
            "task_specializations": self.task_specializations,
            "research_time_ratio": self.research_time_ratio,
            "max_task_duration": self.max_task_duration,
            # Reproductive strategy traits
            "min_reproduction_age": self.min_reproduction_age,
            "expected_lifespan": self.expected_lifespan,
            "safety_margin_cycles": self.safety_margin_cycles,
            "min_comfortable_balance": self.min_comfortable_balance,
            "reproduction_confidence_threshold": self.reproduction_confidence_threshold,
            "min_success_rate_for_reproduction": self.min_success_rate_for_reproduction,
            "offspring_investment_ratio": self.offspring_investment_ratio,
            "nurturing_cycles": self.nurturing_cycles,
            "nurturing_efficiency": self.nurturing_efficiency,
            "kin_helping_threshold": self.kin_helping_threshold,
        })
        return base_dict

    def hash(self) -> str:
        """Generate a hash of the genome (excluding name/generation)."""
        traits = {
            k: v
            for k, v in self.to_dict().items()
            if k not in ("name", "generation", "parent_name")
        }
        genome_str = json.dumps(traits, sort_keys=True)
        return hashlib.sha256(genome_str.encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenClawGenome:
        """Create genome from dictionary."""
        # Handle soul field specially
        filtered_data = {}
        for k, v in data.items():
            if k not in cls.__dataclass_fields__:
                continue
            if k == "soul" and isinstance(v, dict):
                filtered_data[k] = Soul.from_dict(v)
            else:
                filtered_data[k] = v
        return cls(**filtered_data)

    @classmethod
    def random(cls, name: str) -> OpenClawGenome:
        """Create a genome with randomized traits.

        Useful for initializing a diverse population.
        """
        # Get base random traits
        base = ExpandedGenome.random(name)

        # Generate backstory for founding member
        backstory = generate_backstory(
            name=name,
            generation=1,
            parent_name=None,
            openclaw_model="",  # Will be set later
            task_specializations={},  # Will be set later
        )

        # Generate soul with randomized values ranking
        soul = generate_soul(backstory=backstory)

        # Add OpenClaw-specific random traits
        return cls(
            # Identity
            name=name,
            generation=1,

            # Base traits from parent (with OpenClaw adjustments)
            task_preferences=base.task_preferences,
            risk_tolerance=base.risk_tolerance,
            difficulty_preference=base.difficulty_preference,
            budget_per_cycle=base.budget_per_cycle,
            savings_rate=base.savings_rate,
            # Higher replication threshold for OpenClaw (need to accumulate wealth)
            # With $0.50 start and $0.10 replication cost, need threshold > $0.40 to require earning
            replication_threshold=random.uniform(0.45, 0.65),
            child_inheritance_ratio=base.child_inheritance_ratio,
            model_preference_tier=base.model_preference_tier,
            fallback_aggressiveness=base.fallback_aggressiveness,
            prefer_local=base.prefer_local,
            cycle_interval_seconds=base.cycle_interval_seconds,
            task_timeout_multiplier=base.task_timeout_multiplier,
            mutation_rate=base.mutation_rate,
            mutation_magnitude=base.mutation_magnitude,

            # OpenClaw-specific traits
            openclaw_model=random.choice(AVAILABLE_MODELS),
            thinking_level=random.choice(THINKING_LEVELS),
            soul=soul,
            soul_prompt=soul.to_short_prompt(),  # Legacy field
            enabled_tools=cls._random_tools(),
            tool_risk_tolerance=random.uniform(0.1, 0.7),
            task_specializations={
                "coding": random.uniform(0.2, 0.8),
                "file_organization": random.uniform(0.2, 0.8),
                "data_extraction": random.uniform(0.2, 0.8),
                "reasoning": random.uniform(0.2, 0.8),
                "scripting": random.uniform(0.2, 0.8),
                "ai_research": random.uniform(0.1, 0.4),
                "library": random.uniform(0.1, 0.4),
            },
            research_time_ratio=random.uniform(0.05, 0.25),
            max_task_duration=random.uniform(60.0, 180.0),

            # Reproductive strategy traits (randomized for diversity)
            min_reproduction_age=random.randint(5, 20),
            expected_lifespan=random.randint(300, 800),
            safety_margin_cycles=random.randint(10, 40),
            min_comfortable_balance=random.uniform(0.08, 0.25),
            reproduction_confidence_threshold=random.uniform(0.3, 0.6),
            min_success_rate_for_reproduction=random.uniform(0.3, 0.6),
            offspring_investment_ratio=random.uniform(0.2, 0.5),
            nurturing_cycles=random.randint(1, 5),
            nurturing_efficiency=random.uniform(0.3, 0.7),
            kin_helping_threshold=random.uniform(0.1, 0.4),
        )

    @staticmethod
    def _random_tools() -> list[str]:
        """Generate a random set of enabled tools."""
        # Always include core tools
        tools = SAFE_TOOLS.copy()

        # Maybe add advanced tools
        if random.random() > 0.7:
            tools.extend(random.sample(ADVANCED_TOOLS, k=random.randint(0, len(ADVANCED_TOOLS))))

        return tools

    @classmethod
    def from_expanded(cls, expanded: ExpandedGenome, name: str | None = None) -> OpenClawGenome:
        """Create an OpenClaw genome from a base ExpandedGenome.

        Args:
            expanded: Base genome to convert
            name: Optional new name (uses expanded.name if not provided)

        Returns:
            OpenClawGenome with default OpenClaw traits
        """
        actual_name = name or expanded.name

        # Generate backstory
        backstory = generate_backstory(
            name=actual_name,
            generation=expanded.generation,
            parent_name=expanded.parent_name,
            openclaw_model="claude_code/opus-4-5",
            task_specializations={},
        )

        soul = generate_soul(backstory=backstory)

        return cls(
            name=actual_name,
            generation=expanded.generation,
            parent_name=expanded.parent_name,
            task_preferences=expanded.task_preferences,
            risk_tolerance=expanded.risk_tolerance,
            difficulty_preference=expanded.difficulty_preference,
            budget_per_cycle=expanded.budget_per_cycle,
            savings_rate=expanded.savings_rate,
            replication_threshold=expanded.replication_threshold,
            child_inheritance_ratio=expanded.child_inheritance_ratio,
            model_preference_tier=expanded.model_preference_tier,
            fallback_aggressiveness=expanded.fallback_aggressiveness,
            prefer_local=expanded.prefer_local,
            cycle_interval_seconds=expanded.cycle_interval_seconds,
            task_timeout_multiplier=expanded.task_timeout_multiplier,
            mutation_rate=expanded.mutation_rate,
            mutation_magnitude=expanded.mutation_magnitude,
            # OpenClaw defaults
            openclaw_model="claude_code/opus-4-5",
            thinking_level="medium",
            soul=soul,
            soul_prompt=soul.to_short_prompt(),  # Legacy field
            enabled_tools=SAFE_TOOLS.copy(),
            tool_risk_tolerance=expanded.risk_tolerance,
            task_specializations={
                "coding": expanded.task_preferences.get("code", 0.5),
                "file_organization": 0.5,
                "data_extraction": expanded.task_preferences.get("json", 0.5),
                "reasoning": expanded.task_preferences.get("logic", 0.5),
                "scripting": expanded.task_preferences.get("code", 0.5),
                "ai_research": 0.3,
                "library": 0.2,
            },
            research_time_ratio=0.1,
            max_task_duration=120.0 * expanded.task_timeout_multiplier,

            # Reproductive strategy defaults
            min_reproduction_age=10,
            expected_lifespan=500,
            safety_margin_cycles=20,
            min_comfortable_balance=0.15,
            reproduction_confidence_threshold=0.4,
            min_success_rate_for_reproduction=0.4,
            offspring_investment_ratio=0.35,
            nurturing_cycles=3,
            nurturing_efficiency=0.5,
            kin_helping_threshold=0.3,
        )

    def get_openclaw_config(self) -> dict[str, Any]:
        """Get OpenClaw-specific configuration derived from genome.

        Returns:
            Configuration dict for OpenClaw backend
        """
        return {
            "model": self._resolve_model_id(),
            "thinking_level": self.thinking_level,
            "enabled_tools": self.enabled_tools,
            "soul_prompt": self.get_system_prompt(),
            "max_turns": self._calculate_max_turns(),
            "timeout_seconds": self.max_task_duration,
        }

    def _resolve_model_id(self) -> str:
        """Resolve the model ID to use with OpenClaw."""
        # Map registry names to actual model IDs
        model_map = {
            "claude_code/opus-4-5": "opus",
            "claude_code/sonnet-4-5": "sonnet",
            "cerebras/zai-glm-4.7": "zai-glm-4.7",
            "cerebras/llama-3.1-8b": "llama-3.1-8b",
        }
        return model_map.get(self.openclaw_model, "opus")

    def _calculate_max_turns(self) -> int:
        """Calculate max turns based on genome traits."""
        # Base turns
        base_turns = 10

        # Increase for high thinking bots
        if self.thinking_level == "high":
            base_turns += 5
        elif self.thinking_level == "medium":
            base_turns += 2

        # Adjust for risk tolerance (aggressive = more turns)
        base_turns = int(base_turns * (1 + self.tool_risk_tolerance * 0.5))

        return max(5, min(30, base_turns))

    def select_task_type(self, force_research: bool = False) -> str:
        """Select a task type based on specialization weights.

        Args:
            force_research: If True, force selection of research task type

        Returns:
            Selected task type key
        """
        # Check if this should be a research cycle
        if force_research or random.random() < self.research_time_ratio:
            return "ai_research"

        # Filter out research tasks and zero-weight tasks for normal selection
        types = []
        weights = []
        for t in self.task_specializations.keys():
            if t == "ai_research":
                continue
            w = self.task_specializations.get(t, 0.5)
            if w > 0:  # Only include tasks with positive weight
                types.append(t)
                weights.append(w)

        # Fallback if all weights are zero
        if not types:
            return "coding"

        total = sum(weights)
        r = random.random() * total
        cumulative = 0.0

        for task_type, weight in zip(types, weights):
            cumulative += weight
            if r <= cumulative:
                return task_type

        return types[-1]

    def should_use_advanced_tool(self, tool_name: str) -> bool:
        """Decide whether to enable an advanced tool for a task.

        Args:
            tool_name: Name of the tool

        Returns:
            True if should enable, False otherwise
        """
        if tool_name in SAFE_TOOLS:
            return True

        if tool_name in ADVANCED_TOOLS:
            return random.random() < self.tool_risk_tolerance

        return False


@dataclass
class OpenClawMutationBounds:
    """Bounds for OpenClaw genome mutations."""

    # Model mutation probability
    model_mutation_prob: float = 0.1

    # Thinking level mutation probability
    thinking_mutation_prob: float = 0.15

    # Tool set mutation probability
    tool_mutation_prob: float = 0.1

    # Soul mutation probabilities (tier-specific)
    soul_purpose_mutation_prob: float = 0.01  # Near-immutable
    soul_values_mutation_prob: float = 0.05   # Slow drift
    soul_boundaries_mutation_prob: float = 0.0  # Safety-critical, never mutates
    soul_flavor_mutation_prob: float = 0.15   # Highly mutable (personality/approach/style)

    # Legacy soul prompt mutation probability (deprecated)
    soul_mutation_prob: float = 0.05

    # Research time ratio bounds
    research_time_ratio_range: tuple[float, float] = (0.05, 0.25)
    research_time_mutation_prob: float = 0.05

    # Specialization bounds
    specialization_range: tuple[float, float] = (0.1, 1.0)

    # Task duration bounds
    max_task_duration_range: tuple[float, float] = (30.0, 300.0)

    # Tool risk bounds
    tool_risk_range: tuple[float, float] = (0.0, 1.0)

    # Reproductive strategy bounds
    min_reproduction_age_range: tuple[int, int] = (3, 30)
    expected_lifespan_range: tuple[int, int] = (100, 1000)
    safety_margin_cycles_range: tuple[int, int] = (5, 50)
    min_comfortable_balance_range: tuple[float, float] = (0.05, 0.40)
    reproduction_confidence_threshold_range: tuple[float, float] = (0.2, 0.8)
    min_success_rate_for_reproduction_range: tuple[float, float] = (0.2, 0.8)
    offspring_investment_ratio_range: tuple[float, float] = (0.15, 0.60)
    nurturing_cycles_range: tuple[int, int] = (0, 10)
    nurturing_efficiency_range: tuple[float, float] = (0.2, 0.9)
    kin_helping_threshold_range: tuple[float, float] = (0.0, 0.6)
