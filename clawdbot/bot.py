"""Bot - Skeleton agent with LLM brain and telemetry integration."""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawdbot.brain import BrainConfig, BrainRouter
from clawdbot.exceptions import BackendError, BudgetExceededError
from clawdbot.llm_registry import LLMRegistry
from clawdbot.telemetry import TelemetryReporter


@dataclass
class BotGenome:
    """Bot genome - configuration that defines bot behavior."""

    name: str
    generation: int = 1
    parent_name: str | None = None

    # Brain configuration
    brain_config: dict[str, Any] = field(default_factory=dict)

    # Behavior parameters
    cycle_interval_seconds: float = 30.0
    replication_fitness_threshold: float = 0.8
    max_cycles_per_run: int = 1000

    # Mutation parameters (for future evolution)
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
        import json

        genome_str = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(genome_str.encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BotGenome:
        """Create genome from dictionary."""
        return cls(**data)


@dataclass
class BotState:
    """Current state of a bot."""

    cycle_count: int = 0
    fitness_score: float = 0.5  # Start at 50% - neutral starting point
    wallet_balance: float = 0.10  # Start with $0.10 seed funding
    tasks_completed: int = 0
    tasks_failed: int = 0
    current_state: str = "idle"
    cycle_revenue: float = 0.0
    cycle_api_spend: float = 0.0
    last_cycle_time: float = 0.0
    children_spawned: int = 0


class Bot:
    """Bot agent with LLM brain and telemetry integration.

    This is a skeleton implementation that demonstrates the integration
    of all MoltNet components.
    """

    # Class-level registry of all running bots (for colony management)
    _colony: dict[str, "Bot"] = {}
    _colony_lock: asyncio.Lock | None = None

    def __init__(
        self,
        genome: BotGenome | dict[str, Any],
        registry_path: str | Path | None = None,
        observatory_url: str | None = None,
        initial_balance: float | None = None,
    ):
        # Parse genome
        if isinstance(genome, dict):
            self.genome = BotGenome.from_dict(genome)
        else:
            self.genome = genome

        # Initialize registry
        self.registry = LLMRegistry()
        registry_path = registry_path or os.environ.get(
            "LLM_REGISTRY_PATH", "config/llm-registry.yaml"
        )
        if Path(registry_path).exists():
            self.registry.load(registry_path)

        # Initialize brain
        brain_config = BrainConfig(**self.genome.brain_config)
        self.brain = BrainRouter(config=brain_config, registry=self.registry)

        # Initialize telemetry
        observatory_url = observatory_url or os.environ.get("OBSERVATORY_URL")
        self.telemetry = TelemetryReporter(observatory_url=observatory_url)

        # Initialize state
        self.state = BotState()
        if initial_balance is not None:
            self.state.wallet_balance = initial_balance
        self._running = False
        self._stop_requested = False
        self._child_tasks: list[asyncio.Task] = []

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

    async def run(self) -> None:
        """Run the bot's main loop."""
        self._running = True
        self._stop_requested = False
        self.state.current_state = "running"

        # Report startup
        self.telemetry.report_event(
            event_type="bot_started",
            bot_name=self.name,
            data={"generation": self.generation, "genome_hash": self.genome.hash()},
        )

        try:
            while not self._stop_requested:
                # Check cycle limit
                if self.state.cycle_count >= self.genome.max_cycles_per_run:
                    break

                # Run a cycle
                await self._run_cycle()

                # Check replication readiness
                if self._should_replicate():
                    await self._replicate()

                # Wait for next cycle
                await asyncio.sleep(self.genome.cycle_interval_seconds)

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            self.state.current_state = "stopped"

            # Report shutdown
            self.telemetry.report_event(
                event_type="bot_stopped",
                bot_name=self.name,
                data={"cycles": self.state.cycle_count, "fitness": self.state.fitness_score},
            )

            # Cleanup
            await self.close()

    async def _run_cycle(self) -> None:
        """Run a single cycle."""
        start_time = time.time()
        self.state.current_state = "active"

        # Reset cycle metrics
        self.brain.reset_cycle()
        cycle_revenue = 0.0

        try:
            # 1. Decide what action to take (placeholder - uses LLM)
            action = await self._decide_action()

            # 2. Execute the action
            result = await self._execute_action(action)

            # 3. Update fitness based on result
            self._update_fitness(result)

            # 4. Update wallet balance
            cycle_revenue = result.get("revenue", 0.0)
            self.state.wallet_balance += cycle_revenue
            self.state.tasks_completed += 1

        except BudgetExceededError:
            # Expected when over budget - not a failure
            self.state.current_state = "budget_limited"
        except BackendError as e:
            # LLM backend error
            self.state.tasks_failed += 1
            self.telemetry.report_event(
                event_type="cycle_error",
                bot_name=self.name,
                data={"error": str(e)},
            )
        except Exception as e:
            # Unexpected error
            self.state.tasks_failed += 1
            self.telemetry.report_event(
                event_type="cycle_error",
                bot_name=self.name,
                data={"error": str(e), "type": type(e).__name__},
            )

        # Update cycle stats
        self.state.cycle_count += 1
        self.state.cycle_revenue = cycle_revenue
        self.state.cycle_api_spend = self.brain.state.cycle_spend
        self.state.wallet_balance -= self.brain.state.cycle_spend
        self.state.last_cycle_time = time.time() - start_time
        self.state.current_state = "idle"

        # 5. Report telemetry
        self._report_telemetry()

    async def _decide_action(self) -> dict[str, Any]:
        """Use the brain to decide what action to take.

        This is a placeholder that demonstrates LLM integration.
        Override in subclasses for actual bot logic.
        """
        # Simple demonstration: ask the LLM what to do
        system_prompt = """You are a bot agent. Decide what action to take next.
Respond with a JSON object containing:
- action: the action name (e.g., "analyze", "generate", "wait")
- reason: brief explanation
Keep it very short."""

        user_prompt = f"""Current state:
- Cycle: {self.state.cycle_count}
- Fitness: {self.state.fitness_score:.3f}
- Balance: ${self.state.wallet_balance:.4f}

What should I do next?"""

        try:
            response = await self.brain.generate(
                prompt=user_prompt,
                system=system_prompt,
                task_type="reasoning",
                max_tokens=100,
                temperature=0.7,
            )

            # Parse response (simplified - real implementation would be more robust)
            return {
                "action": "analyzed",
                "response": response.content,
                "tokens_used": response.total_tokens,
            }
        except (BudgetExceededError, BackendError):
            raise
        except Exception:
            return {"action": "fallback", "response": "No LLM available"}

    async def _execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute an action and return results.

        This is a placeholder. Override in subclasses for actual logic.
        """
        # Placeholder: simulate some work
        await asyncio.sleep(0.1)

        # Simulate revenue (real bots would do actual work)
        revenue = random.uniform(0, 0.001) if action.get("action") != "fallback" else 0

        return {
            "success": True,
            "action": action.get("action"),
            "revenue": revenue,
        }

    def _update_fitness(self, result: dict[str, Any]) -> None:
        """Update fitness score based on cycle result.

        This is a simplified fitness function. Override for custom logic.
        """
        # Simple fitness: exponential moving average of success rate
        success = 1.0 if result.get("success") else 0.0
        alpha = 0.1  # Learning rate

        self.state.fitness_score = (1 - alpha) * self.state.fitness_score + alpha * success

        # Bonus for revenue
        if result.get("revenue", 0) > 0:
            self.state.fitness_score = min(1.0, self.state.fitness_score + 0.01)

    def _should_replicate(self) -> bool:
        """Check if bot should replicate."""
        replication_cost = 0.05  # Cost to spawn a child

        return (
            self.state.fitness_score >= self.genome.replication_fitness_threshold
            and self.state.wallet_balance > replication_cost  # Need funds to spawn child
            and self.state.cycle_count > 10  # Minimum maturity
            and len(Bot._colony) < 50  # Colony size limit (prevent runaway)
        )

    async def _replicate(self) -> "Bot | None":
        """Create and spawn a child bot with mutations.

        Returns the spawned child Bot, or None if replication failed.
        """
        self.state.current_state = "replicating"

        # Replication has a cost - transfer funds to child
        replication_cost = 0.05
        child_initial_balance = replication_cost * 0.8  # Child gets 80% of cost
        self.state.wallet_balance -= replication_cost

        # Create child genome
        child_genome = BotGenome(
            name=f"{self.name}-g{self.generation + 1}-c{self.state.children_spawned}",
            generation=self.generation + 1,
            parent_name=self.name,
            brain_config=self.genome.brain_config.copy(),
            cycle_interval_seconds=self.genome.cycle_interval_seconds,
            replication_fitness_threshold=self.genome.replication_fitness_threshold,
            mutation_rate=self.genome.mutation_rate,
            max_cycles_per_run=self.genome.max_cycles_per_run,
        )

        # Apply mutations
        if random.random() < self.genome.mutation_rate:
            # Mutate cycle interval (±10%)
            child_genome.cycle_interval_seconds *= random.uniform(0.9, 1.1)

        if random.random() < self.genome.mutation_rate:
            # Mutate replication threshold (±5%)
            child_genome.replication_fitness_threshold = max(
                0.5,
                min(0.95, child_genome.replication_fitness_threshold * random.uniform(0.95, 1.05)),
            )

        if random.random() < self.genome.mutation_rate:
            # Mutate budget per cycle (±20%)
            if "budget_per_cycle" in child_genome.brain_config:
                child_genome.brain_config["budget_per_cycle"] *= random.uniform(0.8, 1.2)

        self.state.children_spawned += 1

        # Report replication event
        self.telemetry.report_event(
            event_type="replication",
            bot_name=self.name,
            data={
                "child_name": child_genome.name,
                "child_generation": child_genome.generation,
                "parent_fitness": self.state.fitness_score,
                "child_balance": child_initial_balance,
                "mutations_applied": True,
            },
        )

        # Spawn child bot in background
        try:
            child_bot = Bot(
                genome=child_genome,
                registry_path=os.environ.get("LLM_REGISTRY_PATH", "config/llm-registry.yaml"),
                observatory_url=os.environ.get("OBSERVATORY_URL"),
                initial_balance=child_initial_balance,
            )

            # Run child in background task
            task = asyncio.create_task(child_bot.run())
            self._child_tasks.append(task)

            return child_bot

        except Exception as e:
            self.telemetry.report_event(
                event_type="replication_failed",
                bot_name=self.name,
                data={"error": str(e), "child_name": child_genome.name},
            )
            # Refund the replication cost on failure
            self.state.wallet_balance += replication_cost
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
        )

    def stop(self) -> None:
        """Request the bot to stop."""
        self._stop_requested = True

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
            "cycle_count": self.state.cycle_count,
            "fitness_score": self.state.fitness_score,
            "wallet_balance": self.state.wallet_balance,
            "tasks_completed": self.state.tasks_completed,
            "tasks_failed": self.state.tasks_failed,
            "children_spawned": self.state.children_spawned,
            "brain": self.brain.get_stats(),
            "telemetry": self.telemetry.get_stats(),
        }

    @classmethod
    def get_colony_stats(cls) -> dict[str, Any]:
        """Get statistics for the entire colony."""
        bots = list(cls._colony.values())
        if not bots:
            return {"total_bots": 0}

        return {
            "total_bots": len(bots),
            "total_generations": max(b.generation for b in bots),
            "total_fitness": sum(b.state.fitness_score for b in bots) / len(bots),
            "total_wallet": sum(b.state.wallet_balance for b in bots),
            "total_cycles": sum(b.state.cycle_count for b in bots),
            "bots": [b.name for b in bots],
        }


async def main():
    """Entry point for running a bot."""
    import argparse

    parser = argparse.ArgumentParser(description="Run a MoltNet bot")
    parser.add_argument("--name", default="bot-alpha", help="Bot name")
    parser.add_argument("--generation", type=int, default=1, help="Generation number")
    parser.add_argument("--registry", default="config/llm-registry.yaml", help="Registry path")
    parser.add_argument("--observatory", default=None, help="Observatory URL")
    parser.add_argument("--cycles", type=int, default=100, help="Max cycles")
    parser.add_argument("--interval", type=float, default=30.0, help="Cycle interval (seconds)")
    parser.add_argument("--balance", type=float, default=0.10, help="Initial wallet balance")
    args = parser.parse_args()

    # Set environment for child bots
    if args.registry:
        os.environ["LLM_REGISTRY_PATH"] = args.registry
    if args.observatory:
        os.environ["OBSERVATORY_URL"] = args.observatory

    genome = BotGenome(
        name=args.name,
        generation=args.generation,
        brain_config={
            "budget_per_cycle": 0.05,
            "prefer_local": True,
            "fallback_to_free": True,
        },
        cycle_interval_seconds=args.interval,
        max_cycles_per_run=args.cycles,
    )

    bot = Bot(
        genome=genome,
        registry_path=args.registry,
        observatory_url=args.observatory,
        initial_balance=args.balance,
    )

    print(f"Starting bot: {bot.name} (gen {bot.generation})")
    print(f"Genome hash: {genome.hash()}")
    print(f"Initial balance: ${args.balance:.2f}")
    print(f"Replication threshold: {genome.replication_fitness_threshold}")
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

    print("\n" + "=" * 50)
    print("FINAL COLONY STATISTICS")
    print("=" * 50)
    print(f"Colony stats: {Bot.get_colony_stats()}")
    print(f"\nFounder stats: {bot.get_stats()}")


if __name__ == "__main__":
    asyncio.run(main())
