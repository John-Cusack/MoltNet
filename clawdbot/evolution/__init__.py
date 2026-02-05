"""Evolution package - Selection pressure and genome management."""

from clawdbot.evolution.genome import ExpandedGenome
from clawdbot.evolution.selection import (
    SelectionPressure,
    SelectionConfig,
    DeathCause,
    ViabilityCheck,
)
from clawdbot.evolution.mutation import (
    Mutator,
    MutationResult,
    MutationBounds,
    get_mutator_for_genome,
)
from clawdbot.evolution.openclaw_genome import (
    OpenClawGenome,
    OpenClawMutationBounds,
    AVAILABLE_MODELS,
    THINKING_LEVELS,
    SAFE_TOOLS,
    SOUL_TRAITS,
    generate_soul_prompt,
    mutate_soul_prompt,
)
from clawdbot.evolution.awareness import (
    SelfAwareness,
    EconomicAwareness,
    PerformanceAwareness,
    AgeAwareness,
)
from clawdbot.evolution.reproduction import (
    OffspringHistory,
    ChildOutcome,
    ChildStatus,
    ReproductiveAssessment,
    NurturingTracker,
    NurturingState,
)
from clawdbot.evolution.kinship import (
    FamilyNetwork,
    FamilyMemberStatus,
    KinCooperation,
    HelpDecision,
    FamilyMessage,
    RELATEDNESS_PARENT_CHILD,
    RELATEDNESS_SIBLINGS,
)

__all__ = [
    # Genome
    "ExpandedGenome",
    "OpenClawGenome",
    # Selection
    "SelectionPressure",
    "SelectionConfig",
    "DeathCause",
    "ViabilityCheck",
    # Mutation
    "Mutator",
    "MutationResult",
    "MutationBounds",
    "OpenClawMutationBounds",
    "get_mutator_for_genome",
    # Genome constants
    "AVAILABLE_MODELS",
    "THINKING_LEVELS",
    "SAFE_TOOLS",
    "SOUL_TRAITS",
    "generate_soul_prompt",
    "mutate_soul_prompt",
    # Awareness
    "SelfAwareness",
    "EconomicAwareness",
    "PerformanceAwareness",
    "AgeAwareness",
    # Reproduction
    "OffspringHistory",
    "ChildOutcome",
    "ChildStatus",
    "ReproductiveAssessment",
    "NurturingTracker",
    "NurturingState",
    # Kinship
    "FamilyNetwork",
    "FamilyMemberStatus",
    "KinCooperation",
    "HelpDecision",
    "FamilyMessage",
    "RELATEDNESS_PARENT_CHILD",
    "RELATEDNESS_SIBLINGS",
]
