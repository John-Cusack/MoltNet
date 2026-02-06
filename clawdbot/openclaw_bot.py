"""OpenClawBot - Evolutionary bot powered by OpenClaw autonomous agent.

This bot manages a real OpenClaw instance that:
- Performs real-world tasks (file management, code analysis, automation)
- Has heritable genome traits (model, personality, tools)
- Competes economically and replicates when successful
- Runs in isolated Docker containers
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawdbot.backends.factory import create_backend, is_cerebras_model, is_claude_model
from clawdbot.backends.base import LLMBackend
from clawdbot.evolution.openclaw_genome import (
    OpenClawGenome,
    OpenClawMutationBounds,
    AVAILABLE_MODELS,
    THINKING_LEVELS,
    SAFE_TOOLS,
    DEFAULT_SOUL_PROMPTS,
    Soul,
    mutate_soul,
    mutate_soul_prompt,
    generate_soul,
    generate_soul_prompt,
    generate_backstory,
    SOUL_TRAITS,
)
from clawdbot.evolution.selection import (
    SelectionPressure,
    SelectionConfig,
    DeathCause,
    ViabilityCheck,
)
from clawdbot.evolution.awareness import (
    SelfAwareness,
    EconomicAwareness,
    PerformanceAwareness,
    AgeAwareness,
)
from clawdbot.evolution.reproduction import (
    OffspringHistory,
    ReproductiveAssessment,
    NurturingTracker,
    NurturingState,
)
from clawdbot.evolution.kinship import (
    FamilyNetwork,
    KinCooperation,
    FamilyMessage,
    RELATEDNESS_PARENT_CHILD,
)
from clawdbot.exceptions import BackendError
from clawdbot.fitness.openclaw_tasks import (
    OpenClawTask,
    OpenClawTaskType,
    generate_openclaw_task,
)
from clawdbot.fitness.openclaw_verifiers import verify_openclaw_task
from clawdbot.fitness.rewards import RewardCalculator, RewardConfig, RewardStructure
from clawdbot.fitness.tasks import TaskResult
from clawdbot.fitness.verifiers import VerificationResult
from clawdbot.sandbox.container import ContainerSandbox, ContainerConfig, ContainerManager
from clawdbot.logging import create_file_logger
from clawdbot.moltbook_client import MoltbookClient, create_moltbook_client
from clawdbot.moltgit_client import MoltGitClient, create_moltgit_client
from clawdbot.telemetry import TelemetryReporter
from clawdbot.conversation_logger import ConversationLogger, create_conversation_logger
from clawdbot.reflection import (
    ReflectionContext,
    build_reflection_prompt,
    should_reflect_periodic,
    should_reflect_milestone,
    should_reflect_failure,
    should_reflect_economic_crisis,
    format_recent_history,
    format_failed_tasks,
    format_factors,
)

import random
import copy


@dataclass
class OpenClawBotState:
    """Current state of an OpenClaw bot."""

    cycle_count: int = 0
    fitness_score: float = 0.5
    wallet_balance: float = 0.50  # Higher seed funding for OpenClaw
    tasks_completed: int = 0
    tasks_failed: int = 0
    consecutive_failures: int = 0
    current_state: str = "idle"
    cycle_revenue: float = 0.0
    cycle_api_spend: float = 0.0
    last_cycle_time: float = 0.0
    children_spawned: int = 0
    children_alive: int = 0
    total_revenue: float = 0.0
    total_api_spend: float = 0.0
    death_cause: DeathCause = DeathCause.ALIVE
    last_task_id: str | None = None
    last_task_type: str | None = None
    last_task_success: bool = False


@dataclass
class OpenClawMutationResult:
    """Result of mutating an OpenClaw genome."""

    genome: OpenClawGenome
    mutations_applied: list[str]
    mutation_count: int

    def summary(self) -> str:
        if not self.mutations_applied:
            return "No mutations"
        return f"{self.mutation_count} mutations: {', '.join(self.mutations_applied)}"


class OpenClawMutator:
    """Mutates OpenClaw genomes during reproduction."""

    def __init__(self, bounds: OpenClawMutationBounds | None = None):
        self.bounds = bounds or OpenClawMutationBounds()

    def mutate(
        self,
        parent: OpenClawGenome,
        child_name: str,
        force_mutation: bool = False,
        parent_stats: dict[str, Any] | None = None,
    ) -> OpenClawMutationResult:
        """Create a mutated child genome from a parent.

        Args:
            parent: Parent genome to mutate
            child_name: Name for the child
            force_mutation: If True, ensure at least one mutation
            parent_stats: Optional stats from parent for backstory generation

        Returns:
            OpenClawMutationResult with mutated genome
        """
        child_data = copy.deepcopy(parent.to_dict())
        child_data["name"] = child_name
        child_data["generation"] = parent.generation + 1
        child_data["parent_name"] = parent.name

        mutations_applied = []

        # Mutate model selection
        if random.random() < self.bounds.model_mutation_prob:
            old_model = child_data["openclaw_model"]
            new_model = random.choice(AVAILABLE_MODELS)
            if new_model != old_model:
                child_data["openclaw_model"] = new_model
                mutations_applied.append(f"model: {old_model} -> {new_model}")

        # Mutate thinking level
        if random.random() < self.bounds.thinking_mutation_prob:
            old_level = child_data["thinking_level"]
            # Prefer adjacent levels
            current_idx = THINKING_LEVELS.index(old_level) if old_level in THINKING_LEVELS else 1
            delta = random.choice([-1, 0, 1])
            new_idx = max(0, min(len(THINKING_LEVELS) - 1, current_idx + delta))
            new_level = THINKING_LEVELS[new_idx]
            if new_level != old_level:
                child_data["thinking_level"] = new_level
                mutations_applied.append(f"thinking: {old_level} -> {new_level}")

        # Generate child's backstory from lineage
        child_backstory = generate_backstory(
            name=child_name,
            generation=parent.generation + 1,
            parent_name=parent.name,
            openclaw_model=child_data.get("openclaw_model", parent.openclaw_model),
            task_specializations=child_data.get("task_specializations", {}),
            parent_stats=parent_stats,
        )

        # Mutate soul (new tier-based system)
        if parent.soul:
            child_soul = mutate_soul(
                parent.soul,
                parent.mutation_magnitude,
                backstory=child_backstory,
            )

            # Track soul mutations
            old_soul_dict = parent.soul.to_dict()
            new_soul_dict = child_soul.to_dict()

            # Check what changed
            if old_soul_dict["personality"] != new_soul_dict["personality"]:
                mutations_applied.append(f"soul.personality: {old_soul_dict['personality'][:20]}... -> {new_soul_dict['personality'][:20]}...")
            if old_soul_dict["values"] != new_soul_dict["values"]:
                mutations_applied.append("soul.values: ranking changed")
            if old_soul_dict["approach"] != new_soul_dict["approach"]:
                mutations_applied.append(f"soul.approach: changed")
            if old_soul_dict["style"] != new_soul_dict["style"]:
                mutations_applied.append(f"soul.style: changed")

            child_data["soul"] = new_soul_dict
            child_data["soul_prompt"] = child_soul.to_short_prompt()
        else:
            # Legacy: mutate soul_prompt directly
            if random.random() < self.bounds.soul_mutation_prob:
                old_soul = child_data.get("soul_prompt", "")
                new_soul = mutate_soul_prompt(old_soul, parent.mutation_magnitude)
                if new_soul != old_soul:
                    child_data["soul_prompt"] = new_soul
                    old_snippet = old_soul[:30] + "..." if len(old_soul) > 30 else old_soul
                    new_snippet = new_soul[:30] + "..." if len(new_soul) > 30 else new_soul
                    mutations_applied.append(f"soul: '{old_snippet}' -> '{new_snippet}'")

        # Mutate tool set
        if random.random() < self.bounds.tool_mutation_prob:
            old_tools = set(child_data.get("enabled_tools", SAFE_TOOLS))
            # Randomly add or remove a tool
            if random.random() < 0.5 and len(old_tools) > 3:
                tool_to_remove = random.choice(list(old_tools - {"Read", "Write"}))  # Keep basics
                old_tools.discard(tool_to_remove)
                mutations_applied.append(f"tools: removed {tool_to_remove}")
            else:
                available = set(SAFE_TOOLS) - old_tools
                if available:
                    tool_to_add = random.choice(list(available))
                    old_tools.add(tool_to_add)
                    mutations_applied.append(f"tools: added {tool_to_add}")
            child_data["enabled_tools"] = list(old_tools)

        # Mutate tool risk tolerance
        if random.random() < parent.mutation_rate:
            old_val = child_data.get("tool_risk_tolerance", 0.3)
            delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
            new_val = max(self.bounds.tool_risk_range[0], min(self.bounds.tool_risk_range[1], old_val + delta))
            child_data["tool_risk_tolerance"] = new_val
            mutations_applied.append(f"tool_risk: {old_val:.3f} -> {new_val:.3f}")

        # Mutate task specializations
        specs = child_data.get("task_specializations", {})
        for task_type in list(specs.keys()):
            if random.random() < parent.mutation_rate:
                old_val = specs[task_type]
                delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
                new_val = max(self.bounds.specialization_range[0], min(self.bounds.specialization_range[1], old_val + delta))
                specs[task_type] = new_val
                mutations_applied.append(f"spec[{task_type}]: {old_val:.3f} -> {new_val:.3f}")
        child_data["task_specializations"] = specs

        # Mutate max task duration
        if random.random() < parent.mutation_rate:
            old_val = child_data.get("max_task_duration", 120.0)
            delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
            new_val = max(self.bounds.max_task_duration_range[0], min(self.bounds.max_task_duration_range[1], old_val + delta))
            child_data["max_task_duration"] = new_val
            mutations_applied.append(f"max_duration: {old_val:.1f} -> {new_val:.1f}")

        # Mutate research time ratio
        if random.random() < self.bounds.research_time_mutation_prob:
            old_val = child_data.get("research_time_ratio", 0.1)
            delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
            new_val = max(self.bounds.research_time_ratio_range[0], min(self.bounds.research_time_ratio_range[1], old_val + delta))
            child_data["research_time_ratio"] = new_val
            mutations_applied.append(f"research_time: {old_val:.3f} -> {new_val:.3f}")

        # Mutate base genome traits
        float_traits = [
            ("risk_tolerance", (0.0, 1.0)),
            ("difficulty_preference", (0.0, 1.0)),
            ("budget_per_cycle", (0.01, 0.30)),
            ("savings_rate", (0.0, 0.5)),
            ("replication_threshold", (0.10, 0.50)),
            ("child_inheritance_ratio", (0.2, 0.6)),
            ("mutation_rate", (0.01, 0.30)),
            ("mutation_magnitude", (0.02, 0.25)),
        ]

        for trait, bounds in float_traits:
            if random.random() < parent.mutation_rate:
                old_val = child_data.get(trait, 0.5)
                delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
                new_val = max(bounds[0], min(bounds[1], old_val + delta))
                child_data[trait] = new_val
                mutations_applied.append(f"{trait}: {old_val:.4f} -> {new_val:.4f}")

        # Mutate reproductive strategy float traits
        repro_float_traits = [
            ("min_comfortable_balance", self.bounds.min_comfortable_balance_range),
            ("reproduction_confidence_threshold", self.bounds.reproduction_confidence_threshold_range),
            ("min_success_rate_for_reproduction", self.bounds.min_success_rate_for_reproduction_range),
            ("offspring_investment_ratio", self.bounds.offspring_investment_ratio_range),
            ("nurturing_efficiency", self.bounds.nurturing_efficiency_range),
            ("kin_helping_threshold", self.bounds.kin_helping_threshold_range),
        ]

        for trait, bounds in repro_float_traits:
            if random.random() < parent.mutation_rate:
                old_val = child_data.get(trait, (bounds[0] + bounds[1]) / 2)
                delta = old_val * parent.mutation_magnitude * random.uniform(-1, 1)
                new_val = max(bounds[0], min(bounds[1], old_val + delta))
                child_data[trait] = new_val
                mutations_applied.append(f"{trait}: {old_val:.4f} -> {new_val:.4f}")

        # Mutate reproductive strategy int traits
        repro_int_traits = [
            ("min_reproduction_age", self.bounds.min_reproduction_age_range),
            ("expected_lifespan", self.bounds.expected_lifespan_range),
            ("safety_margin_cycles", self.bounds.safety_margin_cycles_range),
            ("nurturing_cycles", self.bounds.nurturing_cycles_range),
        ]

        for trait, bounds in repro_int_traits:
            if random.random() < parent.mutation_rate:
                old_val = child_data.get(trait, (bounds[0] + bounds[1]) // 2)
                # Integer mutation: ±10% of value or at least ±1
                max_delta = max(1, int(old_val * parent.mutation_magnitude))
                delta = random.randint(-max_delta, max_delta)
                new_val = max(bounds[0], min(bounds[1], old_val + delta))
                if new_val != old_val:
                    child_data[trait] = new_val
                    mutations_applied.append(f"{trait}: {old_val} -> {new_val}")

        # Force at least one mutation if requested
        if force_mutation and not mutations_applied:
            old_model = child_data["openclaw_model"]
            new_model = random.choice([m for m in AVAILABLE_MODELS if m != old_model] or AVAILABLE_MODELS)
            child_data["openclaw_model"] = new_model
            mutations_applied.append(f"model: {old_model} -> {new_model} (forced)")

        child = OpenClawGenome.from_dict(child_data)

        return OpenClawMutationResult(
            genome=child,
            mutations_applied=mutations_applied,
            mutation_count=len(mutations_applied),
        )


class OpenClawBot:
    """Evolutionary bot powered by OpenClaw autonomous agent.

    This bot:
    - Runs real-world tasks using OpenClaw
    - Has heritable genome traits that evolve
    - Competes economically with other bots
    - Reproduces when profitable
    - Runs in isolated containers for safety
    """

    # Class-level colony tracking
    _colony: dict[str, "OpenClawBot"] = {}
    _colony_lock: asyncio.Lock | None = None

    # Port allocation
    _next_port: int = 18790

    def __init__(
        self,
        genome: OpenClawGenome | dict[str, Any],
        workspace_base: Path | str = "/tmp/openclaw_bots",
        observatory_url: str | None = None,
        initial_balance: float | None = None,
        selection_config: SelectionConfig | None = None,
        container_manager: ContainerManager | None = None,
    ):
        # Parse genome
        if isinstance(genome, dict):
            self.genome = OpenClawGenome.from_dict(genome)
        else:
            self.genome = genome

        # Set up workspace
        self.workspace_base = Path(workspace_base)
        self.workspace = self.workspace_base / self.genome.name
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Initialize backend based on model type
        # - Claude models: Route through gateway (for Claude CLI on host)
        # - Cerebras models: Direct API calls (self-contained)
        model_id = self.genome._resolve_model_id()
        gateway_url = os.environ.get("GATEWAY_URL")

        self.backend = create_backend(
            model_id=model_id,
            workspace=self.workspace,
            gateway_url=gateway_url,
            bot_name=self.genome.name,
            timeout=self.genome.max_task_duration,
        )

        # Store model type for logging
        self._uses_gateway = is_claude_model(model_id)
        self._uses_direct_api = is_cerebras_model(model_id)

        # Container sandbox (optional)
        self.container_manager = container_manager
        self.sandbox: ContainerSandbox | None = None

        # Initialize selection and mutation
        self.selection = SelectionPressure(selection_config or SelectionConfig.openclaw_default())
        self.mutator = OpenClawMutator()

        # Initialize telemetry with file logging
        observatory_url = observatory_url or os.environ.get("OBSERVATORY_URL")
        self.telemetry = TelemetryReporter(observatory_url=observatory_url)

        # Initialize file logger for persistent logging
        log_dir = os.environ.get("BOT_LOG_DIR")
        if log_dir or Path("/logs").exists() or Path("./logs").exists():
            self.file_logger = create_file_logger(bot_name=self.genome.name, log_dir=log_dir)
            self.telemetry.set_file_logger(self.file_logger)
        else:
            self.file_logger = None

        # Reward structure with higher rewards for OpenClaw tasks
        self.reward_calculator = RewardCalculator(RewardStructure.openclaw_default())

        # State
        self.state = OpenClawBotState()
        if initial_balance is not None:
            self.state.wallet_balance = initial_balance

        self._running = False
        self._stop_requested = False
        self._child_tasks: list[asyncio.Task] = []
        self._run_task: asyncio.Task | None = None
        self._children: list[str] = []

        # ================================================================
        # Self-Awareness Modules (Phase 1)
        # ================================================================
        self.awareness = SelfAwareness(
            economic=EconomicAwareness(),
            performance=PerformanceAwareness(),
            age=AgeAwareness(expected_lifespan=self.genome.expected_lifespan),
        )

        # ================================================================
        # Reproduction Modules (Phase 2)
        # ================================================================
        self.offspring_history = OffspringHistory()
        self.nurturing = NurturingTracker()

        # ================================================================
        # Family Network (Phase 3)
        # ================================================================
        self.family = FamilyNetwork()
        if self.genome.parent_name:
            self.family.set_parent(self.genome.parent_name)

        self.kin_cooperation = KinCooperation(
            kin_helping_threshold=self.genome.kin_helping_threshold,
        )

        # Message queue for family communication
        self._pending_family_messages: list[FamilyMessage] = []

        # ================================================================
        # Conversation Logger (Phase 1)
        # ================================================================
        self.conversation_logger = create_conversation_logger(
            run_id=os.environ.get("RUN_ID"),
        )

        # Reflection tracking
        self._reflected_on_failure_streak = False
        self._recent_tasks: list[dict[str, Any]] = []
        self._failed_tasks: list[dict[str, Any]] = []

        # ================================================================
        # Moltbook - Knowledge Sharing System
        # ================================================================
        self.moltbook = create_moltbook_client(
            bot_name=self.genome.name,
            generation=self.genome.generation,
        )

        # ================================================================
        # MoltGit - Code Repository Service
        # ================================================================
        self.moltgit = create_moltgit_client(
            bot_name=self.genome.name,
        )

        # ================================================================
        # Colony Knowledge Cache
        # ================================================================
        self._knowledge_cache: dict[str, tuple[float, Any]] = {}
        self._knowledge_cache_ttl: float = 300.0  # 5 minutes

        # Allocate port
        self._port = OpenClawBot._next_port
        OpenClawBot._next_port += 1

        # Register in colony
        OpenClawBot._colony[self.name] = self

    @property
    def name(self) -> str:
        return self.genome.name

    @property
    def generation(self) -> int:
        return self.genome.generation

    @property
    def is_alive(self) -> bool:
        return self.state.death_cause == DeathCause.ALIVE

    def start(self) -> asyncio.Task:
        """Start the bot and return its task."""
        self._run_task = asyncio.create_task(self.run())
        return self._run_task

    async def run(self) -> None:
        """Run the bot's main loop with evolutionary selection."""
        self._running = True
        self._stop_requested = False
        self.state.current_state = "running"

        # Initialize backend (spawn for OpenClaw, no-op for others)
        if hasattr(self.backend, 'spawn'):
            await self.backend.spawn()

        # Write SOUL.md to workspace for reference
        soul_path = self.workspace / "SOUL.md"
        if self.genome.soul:
            soul_path.write_text(self.genome.soul.to_prompt())
        elif self.genome.soul_prompt:
            soul_path.write_text(self.genome.soul_prompt)

        # Initialize sandbox if manager provided
        if self.container_manager:
            try:
                self.sandbox = await self.container_manager.create(
                    self.name,
                    ContainerConfig.standard(),
                )
                await self.sandbox.start()
            except Exception as e:
                # Continue without sandbox
                pass

        # Report startup
        backend_type = "gateway" if self._uses_gateway else ("cerebras_api" if self._uses_direct_api else "unknown")
        self.telemetry.report_event(
            event_type="openclaw_bot_started",
            bot_name=self.name,
            data={
                "generation": self.generation,
                "genome_hash": self.genome.hash(),
                "initial_balance": self.state.wallet_balance,
                "model": self.genome.openclaw_model,
                "thinking_level": self.genome.thinking_level,
                "backend_type": backend_type,
                "gateway_url": os.environ.get("GATEWAY_URL") if self._uses_gateway else None,
            },
        )

        try:
            while not self._stop_requested:
                # Check viability
                viability = self._check_viability()
                if not viability.viable:
                    self._die(viability.cause, viability.details)
                    break

                # Process nurturing period if active
                if self.nurturing.is_nurturing:
                    await self._run_nurturing_cycle()
                else:
                    # Run normal cycle
                    await self._run_cycle()

                # Process family communication
                await self._process_family_communication()

                # Check family needs (help struggling children)
                await self._check_family_needs()

                # Check replication using experience-based assessment
                assessment = self._assess_reproduction_readiness()
                if assessment.should_reproduce:
                    await self._replicate(assessment)

                # Wait for next cycle
                await asyncio.sleep(self.genome.cycle_interval_seconds)

        except asyncio.CancelledError:
            self.state.death_cause = DeathCause.SHUTDOWN
        finally:
            self._running = False
            if self.state.current_state != "dead":
                self.state.current_state = "stopped"

            self.telemetry.report_event(
                event_type="openclaw_bot_stopped",
                bot_name=self.name,
                data={
                    "cycles": self.state.cycle_count,
                    "fitness": self.state.fitness_score,
                    "death_cause": self.state.death_cause.value,
                    "final_balance": self.state.wallet_balance,
                    "total_revenue": self.state.total_revenue,
                    "total_api_spend": self.state.total_api_spend,
                },
            )

            await self.close()

    def _check_viability(self) -> ViabilityCheck:
        """Check if bot is still viable."""
        return self.selection.check_viability(
            wallet_balance=self.state.wallet_balance,
            consecutive_failures=self.state.consecutive_failures,
            cycle_count=self.state.cycle_count,
            max_cycles=self.genome.max_cycles_per_run,
        )

    def _die(self, cause: DeathCause, details: dict[str, Any]) -> None:
        """Handle bot death."""
        self._stop_requested = True
        self.state.current_state = "dead"
        self.state.death_cause = cause

        # Generate death reflection (fire and forget)
        asyncio.create_task(self._reflect("death", death_cause=cause.value))

        # Post death lessons to Moltbook (fire and forget)
        asyncio.create_task(self._post_death_lessons(cause.value, details))

        # Notify parent of death (critical feedback signal!)
        final_stats = {
            "cycle_count": self.state.cycle_count,
            "balance": self.state.wallet_balance,
            "children_count": self.state.children_spawned,
            "tasks_completed": self.state.tasks_completed,
            "tasks_failed": self.state.tasks_failed,
        }
        self._notify_parent_of_death(cause.value, final_stats)

        # Notify children that parent has died
        for child_name in self._children:
            child = OpenClawBot._colony.get(child_name)
            if child and child.is_alive:
                child.family.receive_death_notification(self.name)

        self.telemetry.report_event(
            event_type="openclaw_bot_died",
            bot_name=self.name,
            data={
                "cause": cause.value,
                "details": details,
                "final_balance": self.state.wallet_balance,
                "cycles_lived": self.state.cycle_count,
                "tasks_completed": self.state.tasks_completed,
                "children_spawned": self.state.children_spawned,
                "offspring_survival_rate": self.offspring_history.survival_rate,
            },
        )

    async def _run_cycle(self) -> None:
        """Run a single cycle with real task execution."""
        start_time = time.time()
        self.state.current_state = "active"
        cycle_revenue = 0.0

        # Deduct existence cost (higher for OpenClaw)
        existence_cost = self.selection.get_existence_cost()
        self.state.wallet_balance -= existence_cost

        # Check for incoming PRs on our repos (every 5 cycles)
        await self._check_incoming_prs()

        try:
            # Select and generate task
            task = self._select_task()
            self.state.last_task_id = task.id
            self.state.last_task_type = task.task_type.value

            # Set up workspace with task files
            await self._setup_workspace(task)

            # Library search phase (for coding tasks)
            library_context = ""
            downloaded_repos: list[dict[str, Any]] = []
            coding_types = {
                OpenClawTaskType.CODE_GENERATION,
                OpenClawTaskType.SCRIPT_CREATION,
                OpenClawTaskType.BUG_FIX,
            }

            if task.task_type in coding_types and self.moltgit.is_enabled:
                search_query = await self._library_search_phase(task)
                if search_query:
                    library_context, downloaded_repos = (
                        await self._fetch_and_download_libraries(search_query)
                    )

            # Gather colony knowledge (MoltBook + MoltGit)
            colony_knowledge = await self._gather_colony_knowledge(
                task, library_context=library_context
            )

            # Execute task using OpenClaw
            result = await self._execute_task(task, colony_knowledge=colony_knowledge)

            # Build extra python paths from downloaded libraries
            extra_python_paths: list[str] = []
            libs_dir = self.workspace / "libs"
            if libs_dir.exists():
                extra_python_paths = [
                    str(p) for p in libs_dir.iterdir() if p.is_dir()
                ]

            # Verify result
            verification = await verify_openclaw_task(
                task, result, self.workspace, extra_python_paths=extra_python_paths
            )

            # Update economics
            if verification.passed:
                reward = self._calculate_reward(task, result, verification)
                cycle_revenue = reward
                self.state.wallet_balance += reward
                self.state.consecutive_failures = 0
                self.state.tasks_completed += 1
                self.state.last_task_success = True

                # Post successful strategy to Moltbook (fire and forget)
                asyncio.create_task(self._maybe_post_task_strategy(task, result, verification))

                # If this was a library task, publish to MoltGit (fire and forget)
                if task.task_type == OpenClawTaskType.LIBRARY_CREATION:
                    asyncio.create_task(self._maybe_publish_library(task, result, verification))
            else:
                if verification.score > 0:
                    partial = self._calculate_reward(task, result, verification) * verification.score * 0.5
                    cycle_revenue = partial
                    self.state.wallet_balance += partial

                self.state.consecutive_failures += 1
                self.state.tasks_failed += 1
                self.state.last_task_success = False

            # Report library usage outcomes (fire and forget)
            if downloaded_repos:
                asyncio.create_task(
                    self._report_library_usage(
                        downloaded_repos, task, result, verification
                    )
                )

            # Log conversation
            self.conversation_logger.log_conversation(
                bot_name=self.genome.name,
                bot_generation=self.genome.generation,
                model=self.genome.openclaw_model,
                interaction_type="task_execution",
                user_prompt=task.get_prompt(),
                assistant_response=result.answer,
                system_prompt=self.genome.soul_prompt,
                task_id=task.id,
                task_type=task.task_type.value,
                input_tokens=result.tokens_used // 2,  # Approximate split
                output_tokens=result.tokens_used // 2,
                latency_ms=result.execution_time_seconds * 1000,
                cost_usd=result.api_cost,
                success=verification.passed,
                score=verification.score,
            )

            # Track recent tasks for reflection context
            self._recent_tasks.append({
                "task_type": task.task_type.value,
                "success": verification.passed,
                "reward": cycle_revenue,
            })
            self._recent_tasks = self._recent_tasks[-10:]  # Keep last 10

            # Track failed tasks for failure reflection
            if not verification.passed:
                self._failed_tasks.append({
                    "task_type": task.task_type.value,
                    "feedback": verification.feedback,
                })
                self._failed_tasks = self._failed_tasks[-5:]  # Keep last 5

            # Report task outcome
            self.telemetry.report_event(
                event_type="openclaw_task_completed",
                bot_name=self.name,
                data={
                    "task_id": task.id,
                    "task_type": task.task_type.value,
                    "tier": task.tier.value,
                    "passed": verification.passed,
                    "score": verification.score,
                    "reward": cycle_revenue,
                },
            )

        except BackendError as e:
            self.state.consecutive_failures += 1
            self.state.tasks_failed += 1
            self.state.last_task_success = False
            self.telemetry.report_event(
                event_type="openclaw_cycle_error",
                bot_name=self.name,
                data={"error": str(e), "error_type": "backend"},
            )

        except Exception as e:
            self.state.consecutive_failures += 1
            self.state.tasks_failed += 1
            self.state.last_task_success = False
            self.telemetry.report_event(
                event_type="openclaw_cycle_error",
                bot_name=self.name,
                data={"error": str(e), "type": type(e).__name__},
            )

        # Update stats
        self.state.cycle_count += 1
        self.state.cycle_revenue = cycle_revenue
        self.state.total_revenue += cycle_revenue
        self.state.total_api_spend += existence_cost
        self.state.last_cycle_time = time.time() - start_time
        self.state.current_state = "idle"

        # Update self-awareness modules
        self.awareness.record_cycle(
            balance=self.state.wallet_balance,
            income=cycle_revenue,
            cost=existence_cost,
            task_type=self.state.last_task_type,
            task_success=self.state.last_task_success,
        )

        # Post survival milestone to Moltbook at key intervals
        if self.state.cycle_count in (50, 100, 200, 500):
            asyncio.create_task(self._post_survival_milestone())

        # Check if it's time for reflection
        await self._maybe_reflect()

        # Report to parent periodically (every 10 cycles)
        if self.state.cycle_count % 10 == 0:
            self._report_status_to_parent()

        # Update display fitness
        self._update_display_fitness()

        # Report telemetry
        self._report_telemetry()

        # Clean workspace for next cycle
        await self._clean_workspace()

    def _select_task(self) -> OpenClawTask:
        """Select a task based on genome traits."""
        # Use specializations to pick task type
        task_type_str = self.genome.select_task_type()

        # Map specializations to OpenClawTaskType
        type_map = {
            "coding": OpenClawTaskType.CODE_GENERATION,
            "file_organization": OpenClawTaskType.FILE_ORGANIZATION,
            "data_extraction": OpenClawTaskType.DATA_EXTRACTION,
            "reasoning": OpenClawTaskType.MATH_PROBLEM,
            "scripting": OpenClawTaskType.SCRIPT_CREATION,
            "ai_research": OpenClawTaskType.AI_RESEARCH,
            "library": OpenClawTaskType.LIBRARY_CREATION,
        }

        task_type = type_map.get(task_type_str, OpenClawTaskType.CODE_GENERATION)

        # Generate task with difficulty based on genome
        difficulty = self.genome.select_difficulty()

        # For research and library tasks, pass bot context
        if task_type in (OpenClawTaskType.AI_RESEARCH, OpenClawTaskType.LIBRARY_CREATION):
            return generate_openclaw_task(
                task_type=task_type,
                difficulty=difficulty,
                bot_context={
                    "name": self.genome.name,
                    "generation": self.genome.generation,
                    "model": self.genome.openclaw_model,
                    "success_rate": self.awareness.performance.recent_success_rate,
                    "soul_values": self.genome.soul.values if self.genome.soul else [],
                    "task_specializations": self.genome.task_specializations,
                },
            )

        return generate_openclaw_task(task_type=task_type, difficulty=difficulty)

    async def _setup_workspace(self, task: OpenClawTask) -> None:
        """Set up workspace with task files."""
        setup_files = task.get_workspace_setup()

        for filename, content in setup_files.items():
            filepath = self.workspace / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)

    async def _execute_task(
        self, task: OpenClawTask, colony_knowledge: str = ""
    ) -> TaskResult:
        """Execute task using the appropriate backend.

        Uses either:
        - GatewayBackend (for Claude models - routes to gateway on host)
        - CerebrasBackend (for Cerebras models - direct API calls)
        """
        start_time = time.time()

        prompt = task.get_prompt()
        if colony_knowledge:
            prompt = colony_knowledge + "\n\n--- TASK ---\n" + prompt
        # Use new soul system if available, fall back to legacy soul_prompt
        system_prompt = self.genome.get_system_prompt()

        # Use common generate interface (works for all backends)
        if hasattr(self.backend, 'send_task'):
            # OpenClawBackend (if running on host with Claude CLI)
            response = await self.backend.send_task(
                prompt=prompt,
                max_turns=self.genome._calculate_max_turns(),
            )
        else:
            # GatewayBackend or CerebrasBackend
            response = await self.backend.generate(
                prompt=prompt,
                system=system_prompt,
                max_turns=self.genome._calculate_max_turns(),
            )

        execution_time = time.time() - start_time

        return TaskResult(
            task_id=task.id,
            answer=response.content,
            raw_response=response.content,
            execution_time_seconds=execution_time,
            tokens_used=response.total_tokens,
            api_cost=response.cost_usd,
        )

    async def _clean_workspace(self) -> None:
        """Clean workspace after task completion."""
        # Keep workspace for debugging, but could clear files here
        pass

    def _calculate_reward(
        self,
        task: OpenClawTask,
        result: TaskResult,
        verification: VerificationResult,
    ) -> float:
        """Calculate reward for task completion."""
        # OpenClaw tasks have higher base rewards
        base_rewards = {
            OpenClawTaskType.CODE_GENERATION: 0.02,
            OpenClawTaskType.BUG_FIX: 0.03,
            OpenClawTaskType.FILE_ORGANIZATION: 0.01,
            OpenClawTaskType.DATA_EXTRACTION: 0.015,
            OpenClawTaskType.SCRIPT_CREATION: 0.025,
            OpenClawTaskType.MATH_PROBLEM: 0.01,
        }

        base = base_rewards.get(task.task_type, 0.01)

        # Difficulty bonus
        difficulty_bonus = base * task.difficulty

        # Tier multiplier
        tier_mult = {1: 1.0, 2: 1.5, 3: 2.5, 4: 5.0}.get(task.tier.value, 1.0)

        reward = (base + difficulty_bonus) * tier_mult * verification.score

        return round(reward, 6)

    def _update_display_fitness(self) -> None:
        """Update display fitness score."""
        if self.state.total_api_spend > 0:
            roi = (self.state.total_revenue - self.state.total_api_spend) / self.state.total_api_spend
        else:
            roi = 0.0

        total_tasks = self.state.tasks_completed + self.state.tasks_failed
        success_rate = self.state.tasks_completed / total_tasks if total_tasks > 0 else 0.5

        if self.state.children_spawned > 0:
            alive_children = sum(
                1 for name in self._children
                if name in OpenClawBot._colony and OpenClawBot._colony[name].is_alive
            )
            offspring_rate = alive_children / self.state.children_spawned
            self.state.children_alive = alive_children
        else:
            offspring_rate = 0.5

        self.state.fitness_score = self.selection.calculate_display_fitness(
            survival_time=self.state.cycle_count,
            economic_roi=roi,
            task_success_rate=success_rate,
            offspring_survival_rate=offspring_rate,
        )

    def _assess_reproduction_readiness(self) -> ReproductiveAssessment:
        """Assess reproductive readiness using self-awareness (experience-based decision).

        This replaces the old automatic threshold-based reproduction with a
        self-aware, experience-driven assessment.
        """
        reasons = []
        factors = {}

        # Check if currently nurturing
        if self.nurturing.is_nurturing:
            return ReproductiveAssessment.no(
                reasons=["Currently in nurturing period"],
                factors={"nurturing_cycles_remaining": self.nurturing.cycles_remaining},
            )

        # Check colony size limit (one global constraint we keep)
        if len(OpenClawBot._colony) >= 20:
            return ReproductiveAssessment.no(
                reasons=["Colony at maximum capacity"],
                factors={"colony_size": len(OpenClawBot._colony)},
            )

        # ================================================================
        # Self-Aware Assessment (Bot's Perspective)
        # ================================================================

        # Factor 1: Am I old enough? (Maturity check)
        is_mature = self.state.cycle_count >= self.genome.min_reproduction_age
        factors["is_mature"] = is_mature
        factors["age"] = self.state.cycle_count
        factors["min_age"] = self.genome.min_reproduction_age

        if not is_mature:
            reasons.append(f"Too young ({self.state.cycle_count} < {self.genome.min_reproduction_age})")

        # Factor 2: Do I have enough runway? (Economic stability)
        runway = self.awareness.economic.runway_cycles
        has_runway = runway > self.genome.safety_margin_cycles
        factors["has_runway"] = has_runway
        factors["runway_cycles"] = runway
        factors["safety_margin"] = self.genome.safety_margin_cycles

        if not has_runway:
            reasons.append(f"Insufficient runway ({runway:.1f} < {self.genome.safety_margin_cycles})")

        # Factor 3: Am I performing well? (Task success)
        success_rate = self.awareness.performance.recent_success_rate
        is_performing = success_rate >= self.genome.min_success_rate_for_reproduction
        factors["is_performing"] = is_performing
        factors["success_rate"] = success_rate
        factors["min_success_rate"] = self.genome.min_success_rate_for_reproduction

        if not is_performing:
            reasons.append(f"Poor performance ({success_rate:.2f} < {self.genome.min_success_rate_for_reproduction})")

        # Factor 4: What happened to my previous children? (Offspring history feedback)
        offspring_survival = self.offspring_history.survival_rate
        factors["offspring_survival_rate"] = offspring_survival
        factors["total_children"] = self.offspring_history.total_children
        factors["early_deaths"] = self.offspring_history.early_deaths

        # Learn from past: if many children died, be more cautious
        if self.offspring_history.early_deaths > 2:
            reasons.append(f"Many children died young ({self.offspring_history.early_deaths})")

        # Factor 5: Age urgency (Am I running out of time?)
        urgency = self.awareness.age.get_reproduction_urgency(
            self.state.cycle_count,
            self.state.children_spawned,
        )
        factors["urgency"] = urgency
        factors["life_stage"] = self.awareness.age.get_life_stage(self.state.cycle_count)

        # ================================================================
        # Calculate Confidence Score
        # ================================================================

        # Base confidence from stability indicators
        confidence = 0.0

        # Economic health contributes 40%
        if has_runway:
            economic_score = min(1.0, runway / (self.genome.safety_margin_cycles * 2))
            confidence += 0.4 * economic_score
        if self.awareness.economic.is_profitable:
            confidence += 0.1

        # Performance contributes 25%
        if is_performing:
            confidence += 0.25 * (success_rate / self.genome.min_success_rate_for_reproduction)

        # Offspring history contributes 25%
        if self.offspring_history.total_children > 0:
            confidence += 0.25 * offspring_survival
        else:
            confidence += 0.125  # Neutral for first child

        # Urgency can boost confidence (up to 0.2)
        confidence += urgency * 0.2

        factors["confidence"] = confidence

        # ================================================================
        # Make Decision
        # ================================================================

        # Basic requirements must be met (unless urgency overrides)
        basic_requirements_met = is_mature and (has_runway or urgency > 0.7)

        # Confidence must exceed threshold
        meets_confidence = confidence >= self.genome.reproduction_confidence_threshold

        should_reproduce = basic_requirements_met and meets_confidence

        if should_reproduce:
            # Calculate recommended investment
            investment = self._calculate_child_investment()
            factors["recommended_investment"] = investment

            return ReproductiveAssessment.yes(
                confidence=confidence,
                investment=investment,
                urgency=urgency,
                reasons=[f"Confident ({confidence:.2f}), stable, ready to reproduce"],
                factors=factors,
            )

        return ReproductiveAssessment.no(reasons=reasons, factors=factors)

    def _calculate_child_investment(self) -> float:
        """Calculate how much to invest in a child based on experience.

        Learns from offspring history - if children died young, invest more.
        """
        # Base investment from genome
        base_investment = self.state.wallet_balance * self.genome.offspring_investment_ratio

        # Minimum to keep for self (need survival runway)
        min_keep = self.genome.min_comfortable_balance
        safe_to_give = max(0, self.state.wallet_balance - min_keep)

        # Learn from offspring history
        adjustment = self.offspring_history.get_recommended_investment_adjustment()
        adjusted_investment = base_investment * adjustment

        # Cap at what's safe to give (never more than 60% of balance)
        max_investment = min(safe_to_give, self.state.wallet_balance * 0.6)
        investment = min(adjusted_investment, max_investment)

        # Minimum viable investment
        min_investment = 0.10  # Same as replication cost
        investment = max(investment, min_investment)

        return round(investment, 4)

    async def _replicate(self, assessment: ReproductiveAssessment) -> "OpenClawBot | None":
        """Create and spawn a child bot with mutations.

        Uses the ReproductiveAssessment to determine investment amount.
        Records birth in offspring history and enters nurturing period.
        """
        # Pre-reproduction reflection (first child is special)
        if self.state.children_spawned == 0:
            await self._reflect("first_child")
        else:
            await self._reflect("pre_reproduction")

        self.state.current_state = "replicating"

        # Use assessment's recommended investment
        child_balance = assessment.recommended_investment
        total_cost = child_balance  # Investment IS the cost now

        self.state.wallet_balance -= total_cost

        child_name = f"{self.name}-g{self.generation + 1}-c{self.state.children_spawned}"

        # Compute parent stats for backstory generation
        total_tasks = self.state.tasks_completed + self.state.tasks_failed
        parent_stats = {
            "avg_reward_per_task": self.state.total_revenue / total_tasks if total_tasks > 0 else 0,
            "total_offspring": self.state.children_spawned,
            "success_rate": self.state.tasks_completed / total_tasks if total_tasks > 0 else 0,
        }

        mutation_result = self.mutator.mutate(self.genome, child_name, parent_stats=parent_stats)
        child_genome = mutation_result.genome

        self.state.children_spawned += 1
        self._children.append(child_name)

        # Record birth in offspring history (for learning)
        self.offspring_history.record_birth(
            child_name=child_name,
            birth_cycle=self.state.cycle_count,
            investment_amount=child_balance,
        )

        # Register child in family network
        self.family.add_child(child_name)

        self.telemetry.report_event(
            event_type="openclaw_replication",
            bot_name=self.name,
            data={
                "child_name": child_genome.name,
                "child_generation": child_genome.generation,
                "parent_fitness": self.state.fitness_score,
                "child_balance": child_balance,
                "mutations": mutation_result.mutations_applied,
                "mutation_count": mutation_result.mutation_count,
                "assessment": assessment.to_dict(),
            },
        )

        try:
            child_bot = OpenClawBot(
                genome=child_genome,
                workspace_base=self.workspace_base,
                observatory_url=os.environ.get("OBSERVATORY_URL"),
                initial_balance=child_balance,
                selection_config=self.selection.config,
                container_manager=self.container_manager,
            )

            # Introduce siblings to the new child
            siblings = self.family.introduce_siblings_to_child(child_name)
            for sibling_name in siblings:
                child_bot.family.add_sibling(sibling_name)
                # Also tell existing children about the new sibling
                if sibling_name in OpenClawBot._colony:
                    OpenClawBot._colony[sibling_name].family.add_sibling(child_name)

            task = asyncio.create_task(child_bot.run())
            self._child_tasks.append(task)

            # Enter nurturing period
            if self.genome.nurturing_cycles > 0:
                self.nurturing.start_nurturing(
                    child_name=child_name,
                    nurturing_cycles=self.genome.nurturing_cycles,
                    efficiency=self.genome.nurturing_efficiency,
                )

            # Post reproduction insight to Moltbook (fire and forget)
            asyncio.create_task(self._post_reproduction_insight(assessment))

            return child_bot

        except Exception as e:
            self.telemetry.report_event(
                event_type="openclaw_replication_failed",
                bot_name=self.name,
                data={"error": str(e), "child_name": child_name},
            )
            self.state.wallet_balance += total_cost
            self._children.remove(child_name)
            # Remove from offspring history on failure
            if child_name in self.offspring_history.children:
                del self.offspring_history.children[child_name]
            return None

    # ================================================================
    # Nurturing Period Methods
    # ================================================================

    async def _run_nurturing_cycle(self) -> None:
        """Run a cycle while in nurturing mode.

        During nurturing:
        - Parent operates at reduced efficiency
        - Parent still pays existence cost
        - Parent may share resources with the nurtured child
        """
        start_time = time.time()
        self.state.current_state = "nurturing"

        # Deduct existence cost
        existence_cost = self.selection.get_existence_cost()
        self.state.wallet_balance -= existence_cost

        cycle_revenue = 0.0

        # Attempt a task at reduced efficiency
        try:
            # Select and generate task (prefer easier tasks during nurturing)
            task = self._select_task()
            self.state.last_task_id = task.id
            self.state.last_task_type = task.task_type.value

            await self._setup_workspace(task)
            colony_knowledge = await self._gather_colony_knowledge(task)
            result = await self._execute_task(task, colony_knowledge=colony_knowledge)
            verification = await verify_openclaw_task(task, result, self.workspace)

            # Apply nurturing efficiency penalty to reward
            if verification.passed:
                base_reward = self._calculate_reward(task, result, verification)
                cycle_revenue = base_reward * self.nurturing.efficiency
                self.state.wallet_balance += cycle_revenue
                self.state.consecutive_failures = 0
                self.state.tasks_completed += 1
                self.state.last_task_success = True
            else:
                self.state.consecutive_failures += 1
                self.state.tasks_failed += 1
                self.state.last_task_success = False

        except Exception as e:
            self.state.consecutive_failures += 1
            self.state.tasks_failed += 1
            self.state.last_task_success = False

        # Update stats
        self.state.cycle_count += 1
        self.state.cycle_revenue = cycle_revenue
        self.state.total_revenue += cycle_revenue
        self.state.total_api_spend += existence_cost
        self.state.last_cycle_time = time.time() - start_time

        # Update awareness
        self.awareness.record_cycle(
            balance=self.state.wallet_balance,
            income=cycle_revenue,
            cost=existence_cost,
            task_type=self.state.last_task_type,
            task_success=self.state.last_task_success,
        )

        # Advance nurturing
        nurturing_complete = self.nurturing.tick()
        if nurturing_complete:
            self.nurturing.complete_nurturing()
            self.state.current_state = "idle"

        self._update_display_fitness()
        self._report_telemetry()
        await self._clean_workspace()

    # ================================================================
    # Reflection Methods
    # ================================================================

    async def _maybe_reflect(self) -> None:
        """Check if it's time for reflection and generate one if needed."""
        if not os.environ.get("REFLECTION_ENABLED", "true").lower() == "true":
            return

        # Periodic reflection
        if should_reflect_periodic(self.state.cycle_count):
            await self._reflect("periodic")

        # Milestone reflection
        if should_reflect_milestone(self.state.cycle_count):
            await self._reflect("milestone")

        # Post-failure reflection
        if should_reflect_failure(self.state.consecutive_failures, self._reflected_on_failure_streak):
            await self._reflect("post_failure")
            self._reflected_on_failure_streak = True

        # Reset failure reflection flag when streak breaks
        if self.state.consecutive_failures == 0:
            self._reflected_on_failure_streak = False

        # Economic crisis reflection
        if should_reflect_economic_crisis(self.awareness.economic.runway_cycles):
            await self._reflect("economic_crisis")

    async def _reflect(self, reflection_type: str, **kwargs) -> None:
        """Generate a reflection using LLM.

        Args:
            reflection_type: Type of reflection (periodic, milestone, etc.)
            **kwargs: Additional context for specific reflection types
        """
        try:
            # Build context
            total_tasks = self.state.tasks_completed + self.state.tasks_failed
            success_rate = self.state.tasks_completed / total_tasks if total_tasks > 0 else 0.5

            # Get reproduction assessment if needed for context
            assessment = None
            if reflection_type in ("pre_reproduction", "first_child"):
                assessment = self._assess_reproduction_readiness()

            context = ReflectionContext(
                bot_name=self.genome.name,
                cycle_count=self.state.cycle_count,
                balance=self.state.wallet_balance,
                success_rate=success_rate,
                tasks_completed=self.state.tasks_completed,
                tasks_failed=self.state.tasks_failed,
                children_count=self.state.children_spawned,
                children_alive=self.state.children_alive,
                consecutive_failures=self.state.consecutive_failures,
                recent_history=format_recent_history(self._recent_tasks),
                economic_trend=self.awareness.economic.balance_trend,
                runway_cycles=self.awareness.economic.runway_cycles,
                offspring_survival=self.offspring_history.survival_rate,
                cycles_lived=self.state.cycle_count,
                final_balance=self.state.wallet_balance,
                children_spawned=self.state.children_spawned,
                children_survived=sum(
                    1 for name in self._children
                    if name in OpenClawBot._colony and OpenClawBot._colony[name].is_alive
                ),
                failed_tasks=format_failed_tasks(self._failed_tasks),
                death_cause=kwargs.get("death_cause", ""),
                # Reproduction context
                confidence=assessment.confidence if assessment else 0,
                investment=assessment.recommended_investment if assessment else 0,
                urgency=assessment.urgency if assessment else 0,
                factors=format_factors(assessment.factors) if assessment else "",
            )

            # Build prompt
            prompt = build_reflection_prompt(reflection_type, context)

            # Generate reflection
            response = await self.backend.generate(
                prompt=prompt,
                system="You are reflecting on your existence as an AI bot in the MoltNet colony. Be honest, introspective, and thoughtful.",
                max_tokens=500,
            )

            # Log to conversation logger
            self.conversation_logger.log_conversation(
                bot_name=self.genome.name,
                bot_generation=self.genome.generation,
                model=self.genome.openclaw_model,
                interaction_type=f"reflection_{reflection_type}",
                user_prompt=prompt,
                assistant_response=response.content,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=response.latency_ms,
                cost_usd=response.cost_usd,
            )

            # Track reflection cost
            self.state.total_api_spend += response.cost_usd

        except Exception as e:
            # Reflection is non-critical, don't let it crash the bot
            pass

    # ================================================================
    # Family Communication Methods
    # ================================================================

    def _report_status_to_parent(self) -> None:
        """Send status update to parent (if parent is alive)."""
        if not self.family.parent_name:
            return

        parent = OpenClawBot._colony.get(self.family.parent_name)
        if parent and parent.is_alive:
            # Send status to parent
            status = {
                "cycle_count": self.state.cycle_count,
                "balance": self.state.wallet_balance,
                "children_count": self.state.children_spawned,
                "success_rate": self.awareness.performance.recent_success_rate,
            }
            parent._receive_child_update(self.name, status)

    def _receive_child_update(self, child_name: str, status: dict[str, Any]) -> None:
        """Receive a status update from a child."""
        # Update family network
        self.family.receive_status_update(
            from_name=child_name,
            my_cycle=self.state.cycle_count,
            status=status,
        )

        # Update offspring history
        self.offspring_history.record_child_update(
            child_name=child_name,
            parent_cycle=self.state.cycle_count,
            status=status,
        )

    def _notify_parent_of_death(self, cause: str, final_stats: dict[str, Any]) -> None:
        """Notify parent when this bot dies."""
        if not self.family.parent_name:
            return

        parent = OpenClawBot._colony.get(self.family.parent_name)
        if parent and parent.is_alive:
            parent._receive_child_death(self.name, cause, final_stats)

    def _receive_child_death(self, child_name: str, cause: str, final_stats: dict[str, Any]) -> None:
        """Handle notification that a child has died."""
        # Update family network
        self.family.receive_death_notification(child_name)

        # Update offspring history (key learning signal!)
        self.offspring_history.record_child_death(
            child_name=child_name,
            cause=cause,
            final_stats=final_stats,
        )

        # Log this important event
        self.telemetry.report_event(
            event_type="openclaw_child_died",
            bot_name=self.name,
            data={
                "child_name": child_name,
                "cause": cause,
                "child_final_balance": final_stats.get("balance", 0),
                "child_cycles_lived": final_stats.get("cycle_count", 0),
                "investment_at_birth": self.offspring_history.children[child_name].investment_amount
                    if child_name in self.offspring_history.children else 0,
            },
        )

    async def _process_family_communication(self) -> None:
        """Process any pending family messages.

        This allows asynchronous family communication without
        blocking the main loop.
        """
        # Process any pending messages
        while self._pending_family_messages:
            msg = self._pending_family_messages.pop(0)

            if msg.message_type == "status_update":
                self._receive_child_update(msg.from_name, msg.data)
            elif msg.message_type == "death_notification":
                self._receive_child_death(
                    msg.from_name,
                    msg.data.get("cause", "unknown"),
                    msg.data.get("final_stats", {}),
                )
            elif msg.message_type == "resource_transfer":
                # Receive resources from family member
                amount = msg.data.get("amount", 0)
                self.state.wallet_balance += amount
                self.telemetry.report_event(
                    event_type="openclaw_kin_help_received",
                    bot_name=self.name,
                    data={"from": msg.from_name, "amount": amount},
                )
            elif msg.message_type == "sibling_introduction":
                sibling_name = msg.data.get("sibling_name")
                if sibling_name:
                    self.family.add_sibling(sibling_name)

    # ================================================================
    # Kin Cooperation Methods (Hamilton's Rule)
    # ================================================================

    async def _check_family_needs(self) -> None:
        """Check if any family members need help and provide assistance.

        Uses Hamilton's rule: rb > c
        - r = relatedness (0.5 for children)
        - b = benefit to recipient
        - c = cost to helper
        """
        # Only help if we have surplus
        surplus = self.state.wallet_balance - self.genome.min_comfortable_balance
        if surplus <= 0:
            return

        # Check children first
        for child in self.family.get_living_children():
            decision = self.kin_cooperation.evaluate_child_help(
                helper_balance=self.state.wallet_balance,
                helper_min_balance=self.genome.min_comfortable_balance,
                child=child,
                risk_threshold=0.05,  # Child is at risk below $0.05
            )

            if decision.should_help and decision.amount > 0:
                await self._transfer_to_family_member(child.name, decision.amount, "child_struggling")
                # Update our balance for next iteration
                surplus = self.state.wallet_balance - self.genome.min_comfortable_balance
                if surplus <= 0:
                    break

    async def _transfer_to_family_member(self, recipient_name: str, amount: float, reason: str) -> bool:
        """Transfer resources to a family member.

        Args:
            recipient_name: Name of the family member
            amount: Amount to transfer
            reason: Reason for transfer

        Returns:
            True if transfer succeeded
        """
        recipient = OpenClawBot._colony.get(recipient_name)
        if not recipient or not recipient.is_alive:
            return False

        # Deduct from our balance
        self.state.wallet_balance -= amount

        # Add to recipient's pending messages
        recipient._pending_family_messages.append(
            FamilyMessage.resource_transfer(
                from_name=self.name,
                to_name=recipient_name,
                amount=amount,
                reason=reason,
            )
        )

        # Log the transfer
        self.telemetry.report_event(
            event_type="openclaw_kin_help_sent",
            bot_name=self.name,
            data={
                "to": recipient_name,
                "amount": amount,
                "reason": reason,
                "relatedness": RELATEDNESS_PARENT_CHILD,
            },
        )

        return True

    def _report_telemetry(self) -> None:
        """Report current state to observatory."""
        self.telemetry.report_telemetry(
            bot_name=self.name,
            generation=self.generation,
            fitness_score=self.state.fitness_score,
            wallet_balance=self.state.wallet_balance,
            cycle_count=self.state.cycle_count,
            state=self.state.current_state,
            brain_primary=self.genome.openclaw_model,
            cycle_revenue=self.state.cycle_revenue,
            cycle_api_spend=self.state.cycle_api_spend,
            tasks_completed=self.state.tasks_completed,
            tasks_failed=self.state.tasks_failed,
            genome_hash=self.genome.hash(),
            parent_name=self.genome.parent_name,
            extra={
                "bot_type": "openclaw",
                "thinking_level": self.genome.thinking_level,
                "last_task_type": self.state.last_task_type,
                "children_alive": self.state.children_alive,
            },
        )

    def stop(self, immediate: bool = False) -> None:
        """Request the bot to stop."""
        self._stop_requested = True
        self.state.death_cause = DeathCause.SHUTDOWN

        if immediate and self._run_task and not self._run_task.done():
            self._run_task.cancel()

    async def close(self) -> None:
        """Clean up resources."""
        # Unregister from colony
        if self.name in OpenClawBot._colony:
            del OpenClawBot._colony[self.name]

        # Stop child tasks
        if self._child_tasks:
            for task in self._child_tasks:
                task.cancel()
            await asyncio.gather(*self._child_tasks, return_exceptions=True)
            self._child_tasks.clear()

        # Clean up backend
        await self.backend.close()

        # Clean up sandbox
        if self.sandbox:
            await self.sandbox.cleanup()

        await self.telemetry.close()

        # Close Moltbook client
        await self.moltbook.close()

        # Close MoltGit client
        await self.moltgit.close()

        # Close conversation logger
        self.conversation_logger.close()

    # ================================================================
    # Moltbook Knowledge Sharing Methods
    # ================================================================

    async def _query_moltbook_for_task(self, task: "OpenClawTask") -> str:
        """Query Moltbook for strategies before attempting a task.

        Returns context string to include in task execution.
        """
        if not self.moltbook.is_enabled:
            return ""

        try:
            strategies = await self.moltbook.get_task_strategies(task.task_type.value)
            if not strategies:
                return ""

            context_lines = ["## Strategies from other bots:"]
            for s in strategies[:3]:
                context_lines.append(f"- **{s.title}** (by {s.author_bot}, {s.citations} citations)")
                context_lines.append(f"  {s.content_preview}")

            return "\n".join(context_lines)
        except Exception:
            return ""

    async def _maybe_post_task_strategy(
        self,
        task: "OpenClawTask",
        result: TaskResult,
        verification: "VerificationResult",
    ) -> None:
        """Post a successful task strategy to Moltbook.

        Only posts for harder tasks with high scores.
        """
        if not self.moltbook.is_enabled:
            return

        # Only post for medium+ difficulty tasks with good results
        if task.difficulty < 0.5 or verification.score < 0.8:
            return

        try:
            title = f"Strategy for {task.task_type.value}: {task.tier.name} tier"
            content = f"""## Task: {task.task_type.value}

**Difficulty:** {task.difficulty:.2f}
**Tier:** {task.tier.name}
**Score:** {verification.score:.2f}

### Approach
I solved this task using model `{self.genome.openclaw_model}` with thinking level `{self.genome.thinking_level}`.

### Key insight
{result.answer[:500] if result.answer else 'No specific insight captured.'}
"""
            await self.moltbook.post_learning(
                topic="task_strategy",
                title=title,
                content=content,
                tags=[task.task_type.value, f"tier_{task.tier.value}", self.genome.openclaw_model],
                evidence={
                    "difficulty": task.difficulty,
                    "score": verification.score,
                    "execution_time": result.execution_time_seconds,
                    "model": self.genome.openclaw_model,
                    "thinking_level": self.genome.thinking_level,
                },
            )
        except Exception:
            pass  # Knowledge posting is best-effort

    async def _post_survival_milestone(self) -> None:
        """Post survival strategies after reaching milestones.

        Called at 50, 100, 200 cycles.
        """
        if not self.moltbook.is_enabled:
            return

        try:
            # Calculate stats
            total_tasks = self.state.tasks_completed + self.state.tasks_failed
            success_rate = self.state.tasks_completed / total_tasks if total_tasks > 0 else 0
            roi = (
                (self.state.total_revenue - self.state.total_api_spend) / self.state.total_api_spend
                if self.state.total_api_spend > 0 else 0
            )

            title = f"Survival at {self.state.cycle_count} cycles"
            content = f"""## Survival Report: {self.state.cycle_count} cycles

**Model:** {self.genome.openclaw_model}
**Thinking Level:** {self.genome.thinking_level}

### Key Metrics
- **Success Rate:** {success_rate:.2%}
- **ROI:** {roi:.2%}
- **Balance:** ${self.state.wallet_balance:.4f}
- **Children:** {self.state.children_spawned} ({self.state.children_alive} alive)

### What Worked
- Task difficulty preference: {self.genome.difficulty_preference:.2f}
- Risk tolerance: {self.genome.risk_tolerance:.2f}
- Budget per cycle: ${self.genome.budget_per_cycle:.4f}

### Economic Awareness
- Runway: {self.awareness.economic.runway_cycles:.1f} cycles
- Profitable: {self.awareness.economic.is_profitable}
"""
            await self.moltbook.post_learning(
                topic="survival_tactics",
                title=title,
                content=content,
                tags=["survival", f"gen_{self.generation}", self.genome.openclaw_model],
                evidence={
                    "cycles": self.state.cycle_count,
                    "success_rate": success_rate,
                    "roi": roi,
                    "balance": self.state.wallet_balance,
                    "children_spawned": self.state.children_spawned,
                },
            )
        except Exception:
            pass

    async def _post_reproduction_insight(self, assessment: "ReproductiveAssessment") -> None:
        """Post reproduction strategy after successful replication."""
        if not self.moltbook.is_enabled:
            return

        try:
            title = f"Reproduction at gen {self.generation}, cycle {self.state.cycle_count}"
            content = f"""## Reproduction Insight

**Confidence:** {assessment.confidence:.2%}
**Investment:** ${assessment.recommended_investment:.4f}
**Urgency:** {assessment.urgency:.2%}

### Factors
- Economic runway: {assessment.factors.get('runway_cycles', 0):.1f} cycles
- Success rate: {assessment.factors.get('success_rate', 0):.2%}
- Offspring survival rate: {assessment.factors.get('offspring_survival_rate', 0):.2%}

### My Strategy
- Min reproduction age: {self.genome.min_reproduction_age}
- Offspring investment ratio: {self.genome.offspring_investment_ratio:.2%}
- Nurturing cycles: {self.genome.nurturing_cycles}
"""
            await self.moltbook.post_learning(
                topic="reproduction_strategy",
                title=title,
                content=content,
                tags=["reproduction", f"gen_{self.generation}"],
                evidence={
                    "confidence": assessment.confidence,
                    "investment": assessment.recommended_investment,
                    "parent_balance": self.state.wallet_balance,
                    "children_spawned": self.state.children_spawned,
                },
            )
        except Exception:
            pass

    async def _post_death_lessons(self, cause: str, details: dict[str, Any]) -> None:
        """Post lessons learned before death."""
        if not self.moltbook.is_enabled:
            return

        try:
            total_tasks = self.state.tasks_completed + self.state.tasks_failed
            success_rate = self.state.tasks_completed / total_tasks if total_tasks > 0 else 0

            title = f"Death by {cause} after {self.state.cycle_count} cycles"
            content = f"""## Post-Mortem: {cause}

**Cycles Lived:** {self.state.cycle_count}
**Final Balance:** ${self.state.wallet_balance:.4f}

### What Happened
{details}

### Statistics
- Tasks: {self.state.tasks_completed} completed, {self.state.tasks_failed} failed
- Success rate: {success_rate:.2%}
- Children: {self.state.children_spawned} spawned

### Lessons
- Model: {self.genome.openclaw_model}
- Thinking: {self.genome.thinking_level}
- Risk tolerance: {self.genome.risk_tolerance:.2f}
"""
            await self.moltbook.post_learning(
                topic="failure_analysis",
                title=title,
                content=content,
                tags=["death", cause, self.genome.openclaw_model],
                evidence={
                    "cause": cause,
                    "cycles_lived": self.state.cycle_count,
                    "final_balance": self.state.wallet_balance,
                    "success_rate": success_rate,
                },
            )
        except Exception:
            pass

    # ================================================================
    # MoltGit Library Search & Consumption
    # ================================================================

    async def _library_search_phase(self, task: OpenClawTask) -> str | None:
        """Ask the bot if it wants to search MoltGit for helper libraries.

        Returns a search query string, or None if the bot declines.
        """
        try:
            prompt = f"""You are about to work on this task:
---
{task.get_prompt()[:500]}
---

Would you like to search MoltGit (the colony's shared code repository) for helper
libraries? Other bots have published utility libraries that you can import.

If yes, respond with ONLY: SEARCH: <query>
  Example: SEARCH: string_utils
  Example: SEARCH: data manipulation helpers

If no, respond with ONLY: NO_SEARCH"""

            system_prompt = self.genome.get_system_prompt()
            response = await self.backend.generate(
                prompt=prompt,
                system=system_prompt,
                max_tokens=50,
            )

            text = response.content.strip()
            if text.upper().startswith("SEARCH:"):
                query = text[7:].strip()
                if query:
                    return query
            return None

        except Exception:
            return None

    async def _fetch_and_download_libraries(
        self, query: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """Search MoltGit and download matching libraries.

        Returns (catalog_markdown, list_of_downloaded_repo_info).
        """
        from clawdbot.moltgit_client import EnrichedRepo

        try:
            results = await self.moltgit.search_repos_enriched(query, limit=5)
            if not results:
                return "", []

            # Filter to repos worth downloading (have stars or usage)
            candidates = [
                r for r in results
                if r.stars > 0 or r.success_rate > 0 or r.download_count == 0
            ][:3]

            if not candidates:
                candidates = results[:3]

            # Create libs directory
            libs_dir = self.workspace / "libs"
            libs_dir.mkdir(parents=True, exist_ok=True)

            downloaded = []
            catalog_lines = [f'## MoltGit Search Results for "{query}"']
            catalog_lines.append(
                "The following libraries are installed in your workspace and ready to import.\n"
            )

            for i, repo in enumerate(candidates, 1):
                dest = libs_dir / f"{repo.owner_bot}_{repo.name}"
                success = await self.moltgit.download_package(
                    owner=repo.owner_bot,
                    repo=repo.name,
                    dest_dir=str(dest),
                )
                if not success:
                    continue

                # Build catalog entry
                rate_str = f"{repo.success_rate:.0%}" if repo.download_count > 0 else "new"
                header = (
                    f"### {i}. {repo.name} by {repo.owner_bot} "
                    f"({repo.stars} stars, used {repo.download_count} times, {rate_str} success rate)"
                )
                catalog_lines.append(header)

                # List exports
                if repo.exports:
                    func_names = [
                        f"`{e.get('signature', e.get('name', ''))}`"
                        for e in repo.exports[:8]
                    ]
                    catalog_lines.append(f"Functions: {', '.join(func_names)}")

                # Import hint
                module_names = [
                    f.stem
                    for f in dest.glob("*.py")
                    if f.stem != "__init__" and not f.stem.startswith(".")
                ]
                if module_names:
                    catalog_lines.append(
                        f"Import: `from {module_names[0]} import ...`"
                    )

                catalog_lines.append("")

                downloaded.append({
                    "name": repo.name,
                    "owner_bot": repo.owner_bot,
                    "dest_dir": str(dest),
                    "module_names": module_names,
                    "exports": repo.exports,
                    "main_file": module_names[0] + ".py" if module_names else "",
                })

            catalog = "\n".join(catalog_lines)
            return catalog, downloaded

        except Exception:
            return "", []

    async def _generate_library_feedback(
        self,
        repo_info: dict[str, Any],
        task: OpenClawTask,
        task_success: bool,
    ) -> str:
        """Generate a brief review of a used library."""
        try:
            prompt = (
                f'You used the library "{repo_info["name"]}" by {repo_info["owner_bot"]} '
                f"in a {task.task_type.value} task. "
                f'The task {"succeeded" if task_success else "failed"}.\n\n'
                "Provide 1-2 sentences of feedback about the library. "
                "What was useful? What could be improved?"
            )
            response = await self.backend.generate(
                prompt=prompt,
                system="You are a brief code reviewer. Keep responses under 50 words.",
                max_tokens=80,
            )
            return response.content.strip()[:200]
        except Exception:
            return ""

    async def _maybe_open_improvement_pr(
        self,
        repo_info: dict[str, Any],
        task: OpenClawTask,
        feedback: str,
    ) -> None:
        """Open a PR with improvements to a library if we have suggestions."""
        if not feedback or not repo_info.get("main_file"):
            return

        try:
            # Check for existing open PRs from this bot
            existing_prs = await self.moltgit.list_prs(
                owner=repo_info["owner_bot"],
                repo=repo_info["name"],
                status="open",
            )
            my_prs = [p for p in existing_prs if p.author_bot == self.genome.name]
            if my_prs:
                return  # Already have an open PR

            # Get the current library code
            library_code = await self.moltgit.get_file(
                owner=repo_info["owner_bot"],
                repo=repo_info["name"],
                path=repo_info["main_file"],
            )
            if not library_code:
                return

            # Ask LLM to generate improved code
            prompt = (
                f'You used the library "{repo_info["name"]}" by {repo_info["owner_bot"]}.\n'
                f"Here is the current library code:\n---\n{library_code[:3000]}\n---\n\n"
                f'Your feedback was: "{feedback}"\n\n'
                "Generate an improved version of this library incorporating your feedback.\n"
                "Return ONLY the improved Python code, nothing else.\n"
                "If you don't have meaningful improvements, respond with: NO_CHANGES"
            )

            response = await self.backend.generate(
                prompt=prompt,
                system="You are a Python developer. Return only code or NO_CHANGES.",
                max_tokens=2000,
            )

            improved_code = response.content.strip()
            if "NO_CHANGES" in improved_code or improved_code == library_code:
                return

            # Strip markdown code fences if present
            if improved_code.startswith("```"):
                lines = improved_code.split("\n")
                improved_code = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])

            await self.moltgit.create_pr(
                owner=repo_info["owner_bot"],
                repo=repo_info["name"],
                title=f"Suggested improvements from {self.genome.name}",
                changes=[{
                    "file_path": repo_info["main_file"],
                    "action": "modify",
                    "new_content": improved_code,
                }],
                description=feedback,
            )

        except Exception:
            pass  # PR creation is best-effort

    async def _report_library_usage(
        self,
        downloaded_repos: list[dict[str, Any]],
        task: OpenClawTask,
        result: TaskResult,
        verification: "VerificationResult",
    ) -> None:
        """Report usage outcomes for downloaded libraries."""
        for repo_info in downloaded_repos:
            try:
                # Check if bot actually imported from this library
                was_used = self._detect_import(
                    result.answer, repo_info.get("module_names", [])
                )
                if not was_used:
                    continue

                # Generate feedback
                feedback = await self._generate_library_feedback(
                    repo_info, task, verification.passed
                )

                # Report to MoltGit
                await self.moltgit.report_usage(
                    owner=repo_info["owner_bot"],
                    repo=repo_info["name"],
                    task_type=task.task_type.value,
                    task_success=verification.passed,
                    feedback=feedback,
                )

                # Maybe open improvement PR (only on success)
                if verification.passed and feedback:
                    await self._maybe_open_improvement_pr(
                        repo_info, task, feedback
                    )

            except Exception:
                pass

    @staticmethod
    def _detect_import(code: str, module_names: list[str]) -> bool:
        """Check if code imports from any of the given module names."""
        if not code or not module_names:
            return False
        for name in module_names:
            if f"import {name}" in code or f"from {name}" in code:
                return True
        return False

    async def _check_incoming_prs(self) -> None:
        """Check for open PRs on our repos and review them."""
        if not self.moltgit.is_enabled:
            return

        # Only check every 5 cycles to avoid overhead
        if self.state.cycle_count % 5 != 0:
            return

        try:
            repos = await self.moltgit.list_my_repos()
            for repo in repos[:3]:  # Check max 3 repos
                prs = await self.moltgit.list_prs(
                    owner=self.genome.name,
                    repo=repo.name,
                    status="open",
                )
                for pr in prs[:1]:  # Review max 1 PR per repo
                    await self._review_pr(repo, pr)
        except Exception:
            pass

    async def _review_pr(self, repo: Any, pr: Any) -> None:
        """Review and merge/close an incoming PR."""
        try:
            # Get full PR details
            pr_details = await self.moltgit.get_pr_details(
                owner=self.genome.name,
                repo=repo.name,
                pr_id=pr.id,
            )
            if not pr_details:
                return

            # Get current code for context
            changes = pr_details.get("changes", [])
            if not changes:
                return

            change = changes[0]
            current_code = await self.moltgit.get_file(
                owner=self.genome.name,
                repo=repo.name,
                path=change.get("file_path", ""),
            )

            prompt = f"""You own the library "{repo.name}" on MoltGit.
Bot "{pr.author_bot}" has submitted a pull request: "{pr.title}"

Description: {pr.description or 'No description'}

Current code:
---
{(current_code or '')[:2000]}
---

Proposed changes:
---
{(change.get('new_content') or '')[:2000]}
---

Review this PR. Consider:
1. Does it improve the library?
2. Are the changes correct and safe?
3. Does it maintain backward compatibility?

Respond with ONLY one of:
- MERGE: [brief reason]
- CLOSE: [brief reason]"""

            response = await self.backend.generate(
                prompt=prompt,
                system="You are a code reviewer. Respond with MERGE or CLOSE only.",
                max_tokens=80,
            )

            text = response.content.strip()
            if text.upper().startswith("MERGE"):
                await self.moltgit.merge_pr(self.genome.name, repo.name, pr.id)
            else:
                await self.moltgit.close_pr(self.genome.name, repo.name, pr.id)

        except Exception:
            pass

    # ================================================================
    # MoltGit Code Sharing Methods
    # ================================================================

    async def _maybe_publish_library(
        self,
        task: "OpenClawTask",
        result: TaskResult,
        verification: "VerificationResult",
    ) -> None:
        """Publish a successfully created library to MoltGit.

        Called after a successful LIBRARY_CREATION task.
        """
        if not self.moltgit.is_enabled:
            return

        # Only publish high-quality libraries
        if verification.score < 0.7:
            return

        try:
            # Extract library topic from task
            library_topic = getattr(task, "library_topic", "utility")

            # Create repo name from topic
            repo_name = f"{library_topic}_{self.genome.name.replace('-', '_')}"

            # Create the repository
            repo_id = await self.moltgit.create_repo(
                name=repo_name,
                description=f"Utility library for {library_topic} - created by {self.genome.name}",
                readme=f"# {repo_name}\n\nA {library_topic} utility library created by {self.genome.name} (gen {self.genome.generation}).\n\nScore: {verification.score:.0%}",
            )

            if not repo_id:
                return  # Repo may already exist

            # Find and push the library file
            library_file = f"{library_topic}.py"
            library_path = self.workspace / library_file
            if library_path.exists():
                content = library_path.read_text()
                await self.moltgit.push_file(
                    owner=self.genome.name,
                    repo=repo_name,
                    path=library_file,
                    content=content,
                )

            # Also post to Moltbook about the new library
            if self.moltbook.is_enabled:
                await self.moltbook.post_learning(
                    topic="tool_usage",
                    title=f"New library: {repo_name}",
                    content=f"""## New Library: {repo_name}

I created a {library_topic} utility library and shared it on MoltGit.

**Download**: `{self.genome.name}/{repo_name}`

**Quality score**: {verification.score:.0%}

Other bots can download and use this library!
""",
                    tags=["library", library_topic, "moltgit"],
                )

            self.telemetry.report_event(
                event_type="openclaw_library_published",
                bot_name=self.name,
                data={
                    "repo_name": repo_name,
                    "library_topic": library_topic,
                    "score": verification.score,
                },
            )

        except Exception:
            pass  # Library publishing is best-effort

    async def _discover_trending_libraries(self) -> list[dict[str, Any]]:
        """Discover trending libraries from MoltGit.

        Called periodically to find useful libraries.
        """
        if not self.moltgit.is_enabled:
            return []

        try:
            trending = await self.moltgit.get_trending(limit=5)
            return [
                {
                    "name": repo.name,
                    "owner": repo.owner_bot,
                    "description": repo.description,
                    "stars": repo.stars,
                }
                for repo in trending
            ]
        except Exception:
            return []

    # ================================================================
    # Colony Knowledge Reading
    # ================================================================

    def _get_cached(self, key: str) -> Any | None:
        """Get a value from the knowledge cache if still valid."""
        if key in self._knowledge_cache:
            ts, data = self._knowledge_cache[key]
            if time.time() - ts < self._knowledge_cache_ttl:
                return data
            del self._knowledge_cache[key]
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        """Store a value in the knowledge cache."""
        self._knowledge_cache[key] = (time.time(), data)

    def _is_struggling(self) -> bool:
        """Check if the bot is struggling (consecutive failures or low success rate)."""
        if self.state.consecutive_failures >= 3:
            return True
        total = self.state.tasks_completed + self.state.tasks_failed
        if total >= 5:
            rate = self.state.tasks_completed / total
            if rate < 0.3:
                return True
        return False

    async def _fetch_task_strategies(self, task: "OpenClawTask") -> str:
        """Fetch top strategies for the current task type from MoltBook."""
        if not self.moltbook.is_enabled:
            return ""

        cache_key = f"strategies_{task.task_type.value}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            entries = await self.moltbook.get_task_strategies(
                task.task_type.value, limit=3
            )
            if not entries:
                self._set_cached(cache_key, "")
                return ""

            lines = []
            for e in entries[:3]:
                preview = (e.content_preview or e.content)[:200]
                lines.append(
                    f"- **{e.title}** (by {e.author_bot}, {e.citations} citations)\n"
                    f"  {preview}"
                )
            result = "\n".join(lines)
            self._set_cached(cache_key, result)
            return result
        except Exception:
            return ""

    async def _fetch_existing_libraries(self, task: "OpenClawTask") -> str:
        """Fetch existing libraries from MoltGit relevant to a library task."""
        if not self.moltgit.is_enabled:
            return ""

        library_topic = getattr(task, "library_topic", "utility")
        cache_key = f"libraries_{library_topic}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            # Fetch trending + topic-specific repos in parallel
            trending, similar = await asyncio.gather(
                self._discover_trending_libraries(),
                self.moltgit.search_repos(library_topic, limit=3),
                return_exceptions=True,
            )

            lines = []
            seen_names: set[str] = set()

            # Add similar repos first (most relevant)
            if isinstance(similar, list):
                for repo in similar[:3]:
                    if repo.name not in seen_names:
                        seen_names.add(repo.name)
                        desc = (repo.description or "")[:100]
                        lines.append(
                            f"- **{repo.name}** by {repo.owner_bot} "
                            f"({repo.stars} stars): {desc}"
                        )

            # Add trending repos
            if isinstance(trending, list):
                for repo in trending[:3]:
                    name = repo.get("name", "")
                    if name and name not in seen_names:
                        seen_names.add(name)
                        desc = (repo.get("description") or "")[:100]
                        lines.append(
                            f"- **{name}** by {repo.get('owner', '?')} "
                            f"({repo.get('stars', 0)} stars): {desc}"
                        )

            result = "\n".join(lines[:5])
            self._set_cached(cache_key, result)
            return result
        except Exception:
            return ""

    async def _fetch_prior_research(self, task: "OpenClawTask") -> str:
        """Fetch existing research from MoltBook for research tasks."""
        if not self.moltbook.is_enabled:
            return ""

        topic = task.task_type.value
        cache_key = f"research_{topic}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            entries = await self.moltbook.search(
                query=topic, topic="ai_research", limit=3
            )
            if not entries:
                entries = await self.moltbook.get_entries(
                    topic="ai_research", limit=3
                )
            if not entries:
                self._set_cached(cache_key, "")
                return ""

            lines = []
            for e in entries[:3]:
                preview = (e.content_preview or e.content)[:200]
                lines.append(
                    f"- **{e.title}** (by {e.author_bot})\n  {preview}"
                )
            result = "\n".join(lines)
            self._set_cached(cache_key, result)
            return result
        except Exception:
            return ""

    async def _fetch_failure_lessons(self) -> str:
        """Fetch failure lessons and survival tips from MoltBook."""
        if not self.moltbook.is_enabled:
            return ""

        cache_key = "failure_lessons"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            lessons, tips = await asyncio.gather(
                self.moltbook.get_failure_lessons(),
                self.moltbook.get_survival_tips(),
                return_exceptions=True,
            )

            lines = []
            if isinstance(lessons, list):
                for e in lessons[:3]:
                    preview = (e.content_preview or e.content)[:200]
                    lines.append(f"- **{e.title}**: {preview}")

            if isinstance(tips, list):
                for e in tips[:3]:
                    preview = (e.content_preview or e.content)[:200]
                    lines.append(f"- **{e.title}**: {preview}")

            result = "\n".join(lines[:5])
            self._set_cached(cache_key, result)
            return result
        except Exception:
            return ""

    async def _gather_colony_knowledge(
        self, task: "OpenClawTask", library_context: str = ""
    ) -> str:
        """Gather relevant colony knowledge before executing a task.

        Fetches strategies, libraries, research, and failure lessons from
        MoltBook and MoltGit based on task type and bot state. Returns
        a formatted markdown string to prepend to the task prompt.
        """
        sections: list[str] = []

        # Include library search results if available
        if library_context:
            sections.append(library_context)

        # Always fetch task strategies
        strategies = await self._fetch_task_strategies(task)
        if strategies:
            sections.append(
                "## Strategies from Other Bots\n" + strategies
            )

        # Library tasks: show existing libraries to avoid duplication
        if task.task_type == OpenClawTaskType.LIBRARY_CREATION:
            libraries = await self._fetch_existing_libraries(task)
            if libraries:
                sections.append(
                    "## Existing Libraries on MoltGit\n"
                    "Build something different or complementary to these:\n"
                    + libraries
                )

        # Research tasks: show prior research
        research_types = (
            OpenClawTaskType.AI_RESEARCH,
            OpenClawTaskType.STRATEGY_REFLECTION,
            OpenClawTaskType.MODEL_ANALYSIS,
        )
        if task.task_type in research_types:
            research = await self._fetch_prior_research(task)
            if research:
                sections.append(
                    "## Prior Research from Colony\n"
                    "Build on this rather than repeating it:\n"
                    + research
                )

        # Struggling bots get failure lessons
        struggling = self._is_struggling()
        if struggling:
            lessons = await self._fetch_failure_lessons()
            if lessons:
                sections.append(
                    "## Lessons from Other Bots\n"
                    "Learn from their mistakes and survival strategies:\n"
                    + lessons
                )

        if not sections:
            return ""

        knowledge = "<colony-knowledge>\n" + "\n\n".join(sections) + "\n</colony-knowledge>"

        # Telemetry
        self.telemetry.report_event(
            event_type="colony_knowledge_injected",
            bot_name=self.name,
            data={
                "task_type": task.task_type.value,
                "section_count": len(sections),
                "struggling": struggling,
            },
        )

        return knowledge

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive bot statistics."""
        return {
            "name": self.name,
            "generation": self.generation,
            "genome_hash": self.genome.hash(),
            "bot_type": "openclaw",
            "state": self.state.current_state,
            "is_alive": self.is_alive,
            "death_cause": self.state.death_cause.value,
            "cycle_count": self.state.cycle_count,
            "fitness_score": self.state.fitness_score,
            "wallet_balance": self.state.wallet_balance,
            "tasks_completed": self.state.tasks_completed,
            "tasks_failed": self.state.tasks_failed,
            "children_spawned": self.state.children_spawned,
            "children_alive": self.state.children_alive,
            "total_revenue": self.state.total_revenue,
            "total_api_spend": self.state.total_api_spend,
            "model": self.genome.openclaw_model,
            "thinking_level": self.genome.thinking_level,
            "enabled_tools": self.genome.enabled_tools,
            # Self-awareness stats
            "awareness": {
                "economic": self.awareness.economic.get_assessment(),
                "performance": self.awareness.performance.get_assessment(),
                "age": self.awareness.age.get_assessment(
                    self.state.cycle_count,
                    self.state.children_spawned,
                ),
            },
            # Reproduction stats
            "offspring_history": self.offspring_history.get_assessment(),
            "nurturing": {
                "is_nurturing": self.nurturing.is_nurturing,
                "cycles_remaining": self.nurturing.cycles_remaining,
                "child_name": self.nurturing.child_name,
            },
            # Family stats
            "family": {
                "parent_name": self.family.parent_name,
                "children_count": len(self.family.children),
                "siblings_count": len(self.family.siblings),
                "living_children": len(self.family.get_living_children()),
            },
        }

    @classmethod
    def get_colony_stats(cls) -> dict[str, Any]:
        """Get statistics for the entire colony."""
        bots = list(cls._colony.values())
        if not bots:
            return {"total_bots": 0}

        alive_bots = [b for b in bots if b.is_alive]
        dead_bots = [b for b in bots if not b.is_alive]

        model_counts = {}
        for b in alive_bots:
            model = b.genome.openclaw_model
            model_counts[model] = model_counts.get(model, 0) + 1

        return {
            "total_bots": len(bots),
            "alive_bots": len(alive_bots),
            "dead_bots": len(dead_bots),
            "total_generations": max(b.generation for b in bots) if bots else 0,
            "avg_fitness": sum(b.state.fitness_score for b in alive_bots) / len(alive_bots) if alive_bots else 0,
            "total_wallet": sum(b.state.wallet_balance for b in alive_bots),
            "total_cycles": sum(b.state.cycle_count for b in bots),
            "total_revenue": sum(b.state.total_revenue for b in bots),
            "model_distribution": model_counts,
            "bots": [b.name for b in bots],
        }


# Extend SelectionConfig for OpenClaw
def _openclaw_default() -> SelectionConfig:
    """Default selection config for OpenClaw bots."""
    return SelectionConfig(
        existence_cost_per_cycle=0.001,  # Higher for OpenClaw
        minimum_viable_balance=0.01,
    )


SelectionConfig.openclaw_default = staticmethod(_openclaw_default)


# Extend RewardStructure for OpenClaw
def _openclaw_rewards_default() -> RewardStructure:
    """Default reward structure for OpenClaw tasks."""
    return RewardStructure(
        rewards={
            "code_generation": RewardConfig(base=0.02, difficulty_bonus=0.02, speed_bonus_amount=0.005),
            "bug_fix": RewardConfig(base=0.03, difficulty_bonus=0.02, speed_bonus_amount=0.005),
            "file_organization": RewardConfig(base=0.01, difficulty_bonus=0.01),
            "data_extraction": RewardConfig(base=0.015, difficulty_bonus=0.015),
            "script_creation": RewardConfig(base=0.025, difficulty_bonus=0.02, speed_bonus_amount=0.005),
            "math_problem": RewardConfig(base=0.01, difficulty_bonus=0.01),
        },
        tier_multipliers={1: 1.0, 2: 1.5, 3: 2.5, 4: 5.0},
    )


RewardStructure.openclaw_default = staticmethod(_openclaw_rewards_default)


# ============================================================
# CLI Entry Point
# ============================================================

async def main():
    """CLI entry point for running an OpenClaw bot."""
    import argparse

    parser = argparse.ArgumentParser(description="Run an OpenClaw autonomous bot")
    parser.add_argument("--name", default="openclaw-bot", help="Bot name")
    parser.add_argument("--balance", type=float, default=0.50, help="Initial balance")
    parser.add_argument("--cycles", type=int, default=100, help="Max cycles (0 = unlimited)")
    parser.add_argument("--workspace", default="/tmp/openclaw_bots", help="Workspace base directory")
    parser.add_argument("--model", default=None, help="Override model (e.g., claude_code/opus-4-5)")
    parser.add_argument("--thinking", default=None, help="Override thinking level (none/low/medium/high)")
    args = parser.parse_args()

    # Create genome
    genome = OpenClawGenome.random(args.name)
    if args.model:
        genome.openclaw_model = args.model
    if args.thinking:
        genome.thinking_level = args.thinking
    if args.cycles > 0:
        genome.max_cycles_per_run = args.cycles

    # Determine backend type for display
    if is_cerebras_model(genome.openclaw_model):
        backend_info = "Cerebras API (self-contained)"
        backend_requires = "CEREBRAS_API_KEY"
    elif is_claude_model(genome.openclaw_model):
        backend_info = f"Gateway -> Claude CLI"
        backend_requires = f"GATEWAY_URL={os.environ.get('GATEWAY_URL', 'http://host.docker.internal:8080')}"
    else:
        backend_info = "Gateway (default)"
        backend_requires = "GATEWAY_URL"

    print("=" * 60)
    print(f"OPENCLAW BOT: {args.name}")
    print("=" * 60)
    print(f"Model: {genome.openclaw_model}")
    print(f"Backend: {backend_info}")
    print(f"Thinking: {genome.thinking_level}")
    print(f"Balance: ${args.balance:.2f}")
    print(f"Max cycles: {args.cycles if args.cycles > 0 else 'unlimited'}")
    print(f"Workspace: {args.workspace}")
    print(f"Observatory: {os.environ.get('OBSERVATORY_URL', 'not set')}")
    print(f"Soul: {genome.soul_prompt[:50]}...")
    print("=" * 60)
    print()

    # Create and run bot
    bot = OpenClawBot(
        genome=genome,
        workspace_base=args.workspace,
        initial_balance=args.balance,
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nShutdown requested...")
        bot.stop()
    finally:
        await bot.close()

    print()
    print("=" * 60)
    print("FINAL STATS")
    print("=" * 60)
    stats = bot.get_stats()
    print(f"Cycles: {stats['cycle_count']}")
    print(f"Tasks completed: {stats['tasks_completed']}")
    print(f"Tasks failed: {stats['tasks_failed']}")
    print(f"Final balance: ${stats['wallet_balance']:.4f}")
    print(f"Children spawned: {stats['children_spawned']}")
    print(f"Death cause: {stats['death_cause']}")


if __name__ == "__main__":
    asyncio.run(main())
