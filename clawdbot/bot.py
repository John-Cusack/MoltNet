"""Bot - Evolutionary agent with LLM brain and real fitness evaluation."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawdbot.brain import BrainConfig, BrainRouter
from clawdbot.evolution.genome import ExpandedGenome
from clawdbot.evolution.mutation import Mutator
from clawdbot.evolution.selection import (
    SelectionPressure,
    SelectionConfig,
    DeathCause,
    ViabilityCheck,
)
from clawdbot.exceptions import BackendError, BudgetExceededError
from clawdbot.fitness.rewards import RewardCalculator
from clawdbot.fitness.task_pool import TaskPool
from clawdbot.fitness.tasks import Task, TaskResult
from clawdbot.fitness.verifiers import VerificationResult, get_verifier
from clawdbot.llm_registry import LLMRegistry
from clawdbot.logging import create_file_logger
from clawdbot.telemetry import TelemetryReporter


# Keep BotGenome for backwards compatibility
@dataclass
class BotGenome:
    """Legacy bot genome - use ExpandedGenome for new bots."""

    name: str
    generation: int = 1
    parent_name: str | None = None
    brain_config: dict[str, Any] = field(default_factory=dict)
    cycle_interval_seconds: float = 30.0
    replication_fitness_threshold: float = 0.8
    max_cycles_per_run: int = 1000
    mutation_rate: float = 0.1

    def to_dict(self) -> dict[str, Any]:
        """Convert genome to dictionary."""
        return {
            "name": self.name,
            "generation": self.generation,
            "parent_name": self.parent_name,
            "brain_config": self.brain_config,
            "cycle_interval_seconds": self.cycle_interval_seconds,
            "replication_fitness_threshold": self.replication_fitness_threshold,
            "max_cycles_per_run": self.max_cycles_per_run,
            "mutation_rate": self.mutation_rate,
        }

    def hash(self) -> str:
        """Generate a hash of the genome."""
        import hashlib
        import json
        genome_str = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(genome_str.encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BotGenome:
        """Create genome from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_expanded(self) -> ExpandedGenome:
        """Convert legacy genome to expanded genome."""
        return ExpandedGenome(
            name=self.name,
            generation=self.generation,
            parent_name=self.parent_name,
            budget_per_cycle=self.brain_config.get("budget_per_cycle", 0.05),
            prefer_local=self.brain_config.get("prefer_local", True),
            cycle_interval_seconds=self.cycle_interval_seconds,
            replication_threshold=self.replication_fitness_threshold,
            max_cycles_per_run=self.max_cycles_per_run,
            mutation_rate=self.mutation_rate,
        )


@dataclass
class BotState:
    """Current state of a bot."""

    cycle_count: int = 0
    fitness_score: float = 0.5  # Display fitness (emergent from survival)
    wallet_balance: float = 0.10  # Start with $0.10 seed funding
    tasks_completed: int = 0
    tasks_failed: int = 0
    consecutive_failures: int = 0  # For starvation detection
    current_state: str = "idle"
    cycle_revenue: float = 0.0
    cycle_api_spend: float = 0.0
    last_cycle_time: float = 0.0
    children_spawned: int = 0
    children_alive: int = 0  # Track living offspring
    total_revenue: float = 0.0  # Lifetime earnings
    total_api_spend: float = 0.0  # Lifetime API costs
    death_cause: DeathCause = DeathCause.ALIVE
    last_task_id: str | None = None
    last_task_success: bool = False


class Bot:
    """Evolutionary bot agent with real fitness evaluation.

    This bot:
    - Solves real tasks with verifiable outcomes
    - Pays existence costs and API costs
    - Dies from bankruptcy or starvation
    - Reproduces when profitable enough
    - Passes evolved traits to offspring
    """

    # Class-level registry of all running bots (for colony management)
    _colony: dict[str, "Bot"] = {}
    _colony_lock: asyncio.Lock | None = None

    def __init__(
        self,
        genome: ExpandedGenome | BotGenome | dict[str, Any],
        registry_path: str | Path | None = None,
        observatory_url: str | None = None,
        initial_balance: float | None = None,
        selection_config: SelectionConfig | None = None,
    ):
        # Parse genome - convert to ExpandedGenome if needed
        if isinstance(genome, dict):
            # Try expanded first, fall back to legacy
            try:
                self.genome = ExpandedGenome.from_dict(genome)
            except (TypeError, KeyError):
                self.genome = BotGenome.from_dict(genome).to_expanded()
        elif isinstance(genome, BotGenome):
            self.genome = genome.to_expanded()
        else:
            self.genome = genome

        # Initialize registry
        self.registry = LLMRegistry()
        registry_path = registry_path or os.environ.get(
            "LLM_REGISTRY_PATH", "config/llm-registry.yaml"
        )
        if Path(registry_path).exists():
            self.registry.load(registry_path)

        # Initialize brain with genome-derived config
        brain_config = BrainConfig(**self.genome.get_brain_config())
        self.brain = BrainRouter(config=brain_config, registry=self.registry)

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

        # Initialize fitness components
        self.task_pool = TaskPool()
        self.reward_calculator = RewardCalculator()
        self.selection = SelectionPressure(selection_config or SelectionConfig.default())
        self.mutator = Mutator()

        # Initialize state
        self.state = BotState()
        if initial_balance is not None:
            self.state.wallet_balance = initial_balance

        self._running = False
        self._stop_requested = False
        self._child_tasks: list[asyncio.Task] = []
        self._run_task: asyncio.Task | None = None
        self._children: list[str] = []  # Track child names

        # Register in colony
        Bot._colony[self.name] = self

    @property
    def name(self) -> str:
        """Get bot name."""
        return self.genome.name

    @property
    def generation(self) -> int:
        """Get bot generation."""
        return self.genome.generation

    @property
    def is_alive(self) -> bool:
        """Check if bot is still alive."""
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

        # Report startup
        self.telemetry.report_event(
            event_type="bot_started",
            bot_name=self.name,
            data={
                "generation": self.generation,
                "genome_hash": self.genome.hash(),
                "initial_balance": self.state.wallet_balance,
            },
        )

        try:
            while not self._stop_requested:
                # 1. Check viability FIRST (death check)
                viability = self._check_viability()
                if not viability.viable:
                    self._die(viability.cause, viability.details)
                    break

                # 2. Run a cycle (includes existence cost)
                await self._run_cycle()

                # 3. Check replication readiness
                if self._should_replicate():
                    await self._replicate()

                # 4. Wait for next cycle
                await asyncio.sleep(self.genome.cycle_interval_seconds)

        except asyncio.CancelledError:
            self.state.death_cause = DeathCause.SHUTDOWN
        finally:
            self._running = False
            if self.state.current_state != "dead":
                self.state.current_state = "stopped"

            # Report final state
            self.telemetry.report_event(
                event_type="bot_stopped",
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

            # Cleanup
            await self.close()

    def _check_viability(self) -> ViabilityCheck:
        """Check if bot is still viable (not dead)."""
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

        # Report death event
        self.telemetry.report_event(
            event_type="bot_died",
            bot_name=self.name,
            data={
                "cause": cause.value,
                "details": details,
                "final_balance": self.state.wallet_balance,
                "cycles_lived": self.state.cycle_count,
                "tasks_completed": self.state.tasks_completed,
                "children_spawned": self.state.children_spawned,
            },
        )

    async def _run_cycle(self) -> None:
        """Run a single cycle with real task execution."""
        start_time = time.time()
        self.state.current_state = "active"

        # Reset cycle metrics
        self.brain.reset_cycle()
        cycle_revenue = 0.0

        # 1. Deduct existence cost (metabolism)
        existence_cost = self.selection.get_existence_cost()
        self.state.wallet_balance -= existence_cost

        try:
            # 2. Select a task based on genome preferences
            task = self._select_task()
            self.state.last_task_id = task.id

            # 3. Solve the task using LLM
            result = await self._solve_task(task)

            # 4. Verify the result
            verifier = get_verifier(task.task_type)
            verification = await verifier.verify(task, result)

            # 5. Update economics based on REAL outcome
            if verification.passed:
                reward = self.reward_calculator.calculate(task, result, verification)
                cycle_revenue = reward
                self.state.wallet_balance += reward
                self.state.consecutive_failures = 0
                self.state.tasks_completed += 1
                self.state.last_task_success = True
            else:
                # Partial reward for partial success
                if verification.score > 0:
                    partial = self.reward_calculator.calculate(task, result, verification)
                    cycle_revenue = partial
                    self.state.wallet_balance += partial

                self.state.consecutive_failures += 1
                self.state.tasks_failed += 1
                self.state.last_task_success = False

            # Report task outcome
            self.telemetry.report_event(
                event_type="task_completed",
                bot_name=self.name,
                data={
                    "task_id": task.id,
                    "task_type": task.task_type.value,
                    "tier": task.tier.value,
                    "difficulty": task.difficulty,
                    "passed": verification.passed,
                    "score": verification.score,
                    "reward": cycle_revenue,
                    "api_cost": self.brain.state.cycle_spend,
                },
            )

        except BudgetExceededError:
            # Over budget - counts as failure
            self.state.current_state = "budget_limited"
            self.state.consecutive_failures += 1
            self.state.tasks_failed += 1
            self.state.last_task_success = False

        except BackendError as e:
            # LLM backend error - counts as failure
            self.state.consecutive_failures += 1
            self.state.tasks_failed += 1
            self.state.last_task_success = False
            self.telemetry.report_event(
                event_type="cycle_error",
                bot_name=self.name,
                data={"error": str(e), "error_type": "backend"},
            )

        except Exception as e:
            # Unexpected error - counts as failure
            self.state.consecutive_failures += 1
            self.state.tasks_failed += 1
            self.state.last_task_success = False
            self.telemetry.report_event(
                event_type="cycle_error",
                bot_name=self.name,
                data={"error": str(e), "type": type(e).__name__},
            )

        # 6. Deduct API costs
        api_cost = self.brain.state.cycle_spend
        self.state.wallet_balance -= api_cost

        # Update cumulative stats
        self.state.cycle_count += 1
        self.state.cycle_revenue = cycle_revenue
        self.state.cycle_api_spend = api_cost
        self.state.total_revenue += cycle_revenue
        self.state.total_api_spend += api_cost + existence_cost
        self.state.last_cycle_time = time.time() - start_time
        self.state.current_state = "idle"

        # 7. Update display fitness (emergent, for analytics only)
        self._update_display_fitness()

        # 8. Report telemetry
        self._report_telemetry()

    def _select_task(self) -> Task:
        """Select a task based on genome preferences."""
        # Use genome to determine difficulty preference
        difficulty = self.genome.select_difficulty()

        # Sample task with genome preferences
        return self.task_pool.sample(
            difficulty=difficulty,
            preferences=self.genome.task_preferences,
        )

    async def _solve_task(self, task: Task) -> TaskResult:
        """Solve a task using the LLM brain."""
        start_time = time.time()

        # Get task prompt
        prompt = task.get_prompt()

        # System prompt for task solving
        system_prompt = """You are a problem-solving agent. Answer the given problem directly and concisely.
Follow the output format specified in the problem exactly.
Do not explain your reasoning unless asked."""

        # Determine task type for model routing
        task_type_map = {
            "math": "math",
            "json": "general",
            "logic": "reasoning",
            "code": "code",
            "humaneval": "code",
            "mbpp": "code",
            "algorithm": "code",
            "swe_lite": "code",
        }
        llm_task_type = task_type_map.get(task.task_type.value, "general")

        # Generate response
        response = await self.brain.generate(
            prompt=prompt,
            system=system_prompt,
            task_type=llm_task_type,
            max_tokens=1024,
            temperature=0.3,  # Lower temperature for more deterministic answers
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

    def _update_display_fitness(self) -> None:
        """Update display fitness score (for analytics only).

        Real fitness is emergent from survival and reproduction.
        This is just for visualization.
        """
        # Calculate ROI
        if self.state.total_api_spend > 0:
            roi = (self.state.total_revenue - self.state.total_api_spend) / self.state.total_api_spend
        else:
            roi = 0.0

        # Calculate success rate
        total_tasks = self.state.tasks_completed + self.state.tasks_failed
        success_rate = self.state.tasks_completed / total_tasks if total_tasks > 0 else 0.5

        # Calculate offspring survival rate
        if self.state.children_spawned > 0:
            alive_children = sum(
                1 for name in self._children
                if name in Bot._colony and Bot._colony[name].is_alive
            )
            offspring_rate = alive_children / self.state.children_spawned
            self.state.children_alive = alive_children
        else:
            offspring_rate = 0.5  # Neutral if no offspring yet

        # Calculate display fitness
        self.state.fitness_score = self.selection.calculate_display_fitness(
            survival_time=self.state.cycle_count,
            economic_roi=roi,
            task_success_rate=success_rate,
            offspring_survival_rate=offspring_rate,
        )

    def _should_replicate(self) -> bool:
        """Check if bot should replicate based on economic viability."""
        replication_cost = 0.05  # Cost to spawn a child

        return (
            self.state.wallet_balance > self.genome.replication_threshold + replication_cost
            and self.state.cycle_count > 10  # Minimum maturity
            and len(Bot._colony) < 50  # Colony size limit
            and self.state.consecutive_failures < 5  # Not struggling
        )

    async def _replicate(self) -> "Bot | None":
        """Create and spawn a child bot with mutations."""
        self.state.current_state = "replicating"

        # Calculate investment
        replication_cost = 0.05
        child_balance = self.genome.calculate_replication_investment(self.state.wallet_balance)
        total_cost = max(replication_cost, child_balance)

        # Deduct cost from parent
        self.state.wallet_balance -= total_cost

        # Create child name
        child_name = f"{self.name}-g{self.generation + 1}-c{self.state.children_spawned}"

        # Mutate genome
        mutation_result = self.mutator.mutate(self.genome, child_name)
        child_genome = mutation_result.genome

        self.state.children_spawned += 1
        self._children.append(child_name)

        # Report replication event
        self.telemetry.report_event(
            event_type="replication",
            bot_name=self.name,
            data={
                "child_name": child_genome.name,
                "child_generation": child_genome.generation,
                "parent_fitness": self.state.fitness_score,
                "parent_balance": self.state.wallet_balance + total_cost,
                "child_balance": child_balance,
                "mutations": mutation_result.mutations_applied,
                "mutation_count": mutation_result.mutation_count,
            },
        )

        # Spawn child bot
        try:
            child_bot = Bot(
                genome=child_genome,
                registry_path=os.environ.get("LLM_REGISTRY_PATH", "config/llm-registry.yaml"),
                observatory_url=os.environ.get("OBSERVATORY_URL"),
                initial_balance=child_balance,
                selection_config=self.selection.config,
            )

            # Run child in background task
            task = asyncio.create_task(child_bot.run())
            self._child_tasks.append(task)

            return child_bot

        except Exception as e:
            self.telemetry.report_event(
                event_type="replication_failed",
                bot_name=self.name,
                data={"error": str(e), "child_name": child_name},
            )
            # Refund the cost on failure
            self.state.wallet_balance += total_cost
            self._children.remove(child_name)
            return None

    def _report_telemetry(self) -> None:
        """Report current state to observatory."""
        self.telemetry.report_telemetry(
            bot_name=self.name,
            generation=self.generation,
            fitness_score=self.state.fitness_score,
            wallet_balance=self.state.wallet_balance,
            cycle_count=self.state.cycle_count,
            state=self.state.current_state,
            brain_primary=self.brain.state.last_model_used,
            cycle_revenue=self.state.cycle_revenue,
            cycle_api_spend=self.state.cycle_api_spend,
            tasks_completed=self.state.tasks_completed,
            tasks_failed=self.state.tasks_failed,
            genome_hash=self.genome.hash(),
            parent_name=self.genome.parent_name,
            extra={
                "consecutive_failures": self.state.consecutive_failures,
                "children_alive": self.state.children_alive,
                "total_revenue": self.state.total_revenue,
                "total_api_spend": self.state.total_api_spend,
                "last_task_success": self.state.last_task_success,
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
        if self.name in Bot._colony:
            del Bot._colony[self.name]

        # Wait for child tasks to complete (with timeout)
        if self._child_tasks:
            for task in self._child_tasks:
                task.cancel()
            await asyncio.gather(*self._child_tasks, return_exceptions=True)
            self._child_tasks.clear()

        await self.brain.close()
        await self.telemetry.close()

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive bot statistics."""
        return {
            "name": self.name,
            "generation": self.generation,
            "genome_hash": self.genome.hash(),
            "state": self.state.current_state,
            "is_alive": self.is_alive,
            "death_cause": self.state.death_cause.value,
            "cycle_count": self.state.cycle_count,
            "fitness_score": self.state.fitness_score,
            "wallet_balance": self.state.wallet_balance,
            "tasks_completed": self.state.tasks_completed,
            "tasks_failed": self.state.tasks_failed,
            "consecutive_failures": self.state.consecutive_failures,
            "children_spawned": self.state.children_spawned,
            "children_alive": self.state.children_alive,
            "total_revenue": self.state.total_revenue,
            "total_api_spend": self.state.total_api_spend,
            "roi": (
                (self.state.total_revenue - self.state.total_api_spend) / self.state.total_api_spend
                if self.state.total_api_spend > 0
                else 0.0
            ),
            "brain": self.brain.get_stats(),
            "telemetry": self.telemetry.get_stats(),
        }

    @classmethod
    def get_colony_stats(cls) -> dict[str, Any]:
        """Get statistics for the entire colony."""
        bots = list(cls._colony.values())
        if not bots:
            return {"total_bots": 0}

        alive_bots = [b for b in bots if b.is_alive]
        dead_bots = [b for b in bots if not b.is_alive]

        return {
            "total_bots": len(bots),
            "alive_bots": len(alive_bots),
            "dead_bots": len(dead_bots),
            "total_generations": max(b.generation for b in bots),
            "avg_fitness": sum(b.state.fitness_score for b in alive_bots) / len(alive_bots) if alive_bots else 0,
            "total_wallet": sum(b.state.wallet_balance for b in alive_bots),
            "total_cycles": sum(b.state.cycle_count for b in bots),
            "total_revenue": sum(b.state.total_revenue for b in bots),
            "total_api_spend": sum(b.state.total_api_spend for b in bots),
            "death_causes": {
                cause.value: sum(1 for b in dead_bots if b.state.death_cause == cause)
                for cause in DeathCause
                if cause != DeathCause.ALIVE
            },
            "bots": [b.name for b in bots],
        }


async def main():
    """Entry point for running a bot with evolutionary fitness."""
    import argparse

    parser = argparse.ArgumentParser(description="Run a MoltNet evolutionary bot")
    parser.add_argument("--name", default="bot-alpha", help="Bot name")
    parser.add_argument("--generation", type=int, default=1, help="Generation number")
    parser.add_argument("--registry", default="config/llm-registry.yaml", help="Registry path")
    parser.add_argument("--observatory", default=None, help="Observatory URL")
    parser.add_argument("--cycles", type=int, default=100, help="Max cycles")
    parser.add_argument("--interval", type=float, default=30.0, help="Cycle interval (seconds)")
    parser.add_argument("--balance", type=float, default=0.10, help="Initial wallet balance")
    parser.add_argument("--difficulty", type=float, default=0.4, help="Task difficulty preference (0-1)")
    parser.add_argument("--selection", choices=["default", "harsh", "gentle"], default="default",
                        help="Selection pressure level")
    args = parser.parse_args()

    # Set environment for child bots
    if args.registry:
        os.environ["LLM_REGISTRY_PATH"] = args.registry
    if args.observatory:
        os.environ["OBSERVATORY_URL"] = args.observatory

    # Create genome
    genome = ExpandedGenome(
        name=args.name,
        generation=args.generation,
        difficulty_preference=args.difficulty,
        max_cycles_per_run=args.cycles,
        cycle_interval_seconds=args.interval,
    )

    # Create selection config
    selection_configs = {
        "default": SelectionConfig.default(),
        "harsh": SelectionConfig.harsh(),
        "gentle": SelectionConfig.gentle(),
    }
    selection_config = selection_configs[args.selection]

    bot = Bot(
        genome=genome,
        registry_path=args.registry,
        observatory_url=args.observatory,
        initial_balance=args.balance,
        selection_config=selection_config,
    )

    print(f"Starting evolutionary bot: {bot.name} (gen {bot.generation})")
    print(f"Genome hash: {genome.hash()}")
    print(f"Initial balance: ${args.balance:.2f}")
    print(f"Difficulty preference: {args.difficulty:.2f}")
    print(f"Selection pressure: {args.selection}")
    print()

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nShutting down colony...")
        # Stop all bots in the colony
        for name, b in list(Bot._colony.items()):
            b.stop()

    # Wait a moment for cleanup
    await asyncio.sleep(1)

    print("\n" + "=" * 60)
    print("FINAL COLONY STATISTICS")
    print("=" * 60)
    stats = Bot.get_colony_stats()
    for key, value in stats.items():
        if key != "bots":
            print(f"  {key}: {value}")
    print(f"\n  Living bots: {[b for b in stats.get('bots', []) if b in Bot._colony and Bot._colony[b].is_alive]}")

    print("\n" + "=" * 60)
    print("FOUNDER BOT STATISTICS")
    print("=" * 60)
    founder_stats = bot.get_stats()
    for key, value in founder_stats.items():
        if key not in ("brain", "telemetry"):
            print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
