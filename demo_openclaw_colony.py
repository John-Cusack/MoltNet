#!/usr/bin/env python3
"""Demo: Run a small OpenClaw colony with Observatory and Moltbook integration.

This script runs OpenClaw bots that:
- Send telemetry to Observatory dashboard
- Share learnings in Moltbook knowledge base
- Replicate when profitable, creating mutated children
- Archive all data for each run separately

Usage:
    # Start services first (in another terminal):
    uv run uvicorn observatory.main:app --port 9100 &
    uv run uvicorn moltbook.main:app --port 9101 &

    # Then run this demo:
    uv run python demo_openclaw_colony.py

    # Simulation mode (no Claude CLI required):
    uv run python demo_openclaw_colony.py --simulate

    # With custom bot count and cycles:
    uv run python demo_openclaw_colony.py --bots 5 --cycles 100

Open http://localhost:9100 to see the Observatory dashboard.
Open http://localhost:9101/stats to see Moltbook knowledge base.
Open http://localhost:9103/stats to see MoltGit code repositories.
Press Ctrl+C to stop all bots.

Start all services with: ./scripts/start_services.sh

Data for each run is archived in ./runs/YYYY-MM-DD_HH-MM-SS/
"""

import argparse
import asyncio
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Configuration - Set before imports
DEFAULT_DATA_DIR = Path("./data")
DEFAULT_LOGS_DIR = Path("./logs")
DEFAULT_RUNS_DIR = Path("./runs")

os.environ.setdefault("OBSERVATORY_URL", "http://localhost:9100")
os.environ.setdefault("MOLTBOOK_URL", "http://localhost:9101")
os.environ.setdefault("MOLTGIT_URL", "http://localhost:9103")
os.environ.setdefault("GATEWAY_URL", "http://localhost:8080")

from clawdbot.evolution.openclaw_genome import OpenClawGenome, AVAILABLE_MODELS
from clawdbot.evolution.selection import DeathCause
from clawdbot.logging import create_file_logger, BotFileLogger
from clawdbot.moltbook_client import MoltbookClient, create_moltbook_client
from clawdbot.openclaw_bot import OpenClawBot, OpenClawMutator
from clawdbot.telemetry import TelemetryReporter
from clawdbot.fitness.tasks import TaskResult


@dataclass
class SimulatedBotState:
    """State for simulated bot."""
    cycle_count: int = 0
    fitness_score: float = 0.5
    wallet_balance: float = 0.50
    tasks_completed: int = 0
    tasks_failed: int = 0
    consecutive_failures: int = 0
    current_state: str = "idle"
    death_cause: str = "alive"
    children_spawned: int = 0
    children_names: list = field(default_factory=list)
    last_replication_cycle: int = -10
    total_revenue: float = 0.0
    total_api_spend: float = 0.0


class SimulatedOpenClawBot:
    """Simulated bot for testing without Claude CLI.

    Sends real telemetry to Observatory and shares knowledge in Moltbook.
    Supports REPLICATION with mutation!
    """

    _colony: dict[str, "SimulatedOpenClawBot"] = {}
    _max_colony_size: int = 150

    def __init__(
        self,
        genome: OpenClawGenome,
        workspace: Path,
        workspace_base: Path | None = None,
        log_dir: Path | None = None,
        initial_balance: float = 0.50,
    ):
        self.genome = genome
        self.workspace = workspace
        self.workspace_base = workspace_base or workspace.parent
        self.log_dir = log_dir or workspace_base / "logs"
        self.state = SimulatedBotState(wallet_balance=initial_balance)

        # Initialize telemetry with file logging
        self.telemetry = TelemetryReporter(
            observatory_url=os.environ.get("OBSERVATORY_URL")
        )

        # Initialize file logger
        self.file_logger = create_file_logger(
            bot_name=self.name,
            log_dir=self.log_dir,
        )
        self.telemetry.set_file_logger(self.file_logger)

        # Initialize Moltbook client
        self.moltbook = create_moltbook_client(
            bot_name=self.name,
            generation=self.generation,
        )

        self.mutator = OpenClawMutator()
        self._stop_requested = False
        self._task: asyncio.Task | None = None
        self._child_tasks: list[asyncio.Task] = []

        # Register in colony
        SimulatedOpenClawBot._colony[self.name] = self

    @property
    def name(self) -> str:
        return self.genome.name

    @property
    def generation(self) -> int:
        return self.genome.generation

    @property
    def is_alive(self) -> bool:
        return self.state.death_cause == "alive"

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self.run())
        return self._task

    async def run(self):
        """Run simulated bot cycles."""
        self.state.current_state = "running"

        # Report startup
        self.telemetry.report_event(
            event_type="openclaw_bot_started",
            bot_name=self.name,
            data={
                "generation": self.generation,
                "model": self.genome.openclaw_model,
                "thinking_level": self.genome.thinking_level,
                "parent": self.genome.parent_name,
                "simulated": True,
            },
        )

        # Query Moltbook for survival tips at startup
        await self._query_moltbook_startup()

        try:
            while not self._stop_requested and self.is_alive:
                await self._run_cycle()

                # Check bankruptcy
                if self.state.wallet_balance < 0.01:
                    self.state.death_cause = "bankruptcy"
                    break

                # Check starvation
                if self.state.consecutive_failures >= 5:
                    self.state.death_cause = "starvation"
                    break

                # Check replication!
                if self._should_replicate():
                    await self._replicate()

                # Post survival milestone
                if self.state.cycle_count in (25, 50, 100):
                    await self._post_survival_milestone()

                await asyncio.sleep(2)  # Fast cycles for demo

        except asyncio.CancelledError:
            self.state.death_cause = "shutdown"
        finally:
            self.state.current_state = "stopped"

            # Post death lessons before shutdown
            if self.state.death_cause not in ("shutdown", "alive"):
                await self._post_death_lessons()

            self.telemetry.report_event(
                event_type="openclaw_bot_stopped",
                bot_name=self.name,
                data={
                    "cycles": self.state.cycle_count,
                    "fitness": self.state.fitness_score,
                    "death_cause": self.state.death_cause,
                    "final_balance": self.state.wallet_balance,
                    "children_spawned": self.state.children_spawned,
                },
            )

            await self.close()

    async def _query_moltbook_startup(self):
        """Query Moltbook for advice at startup."""
        if not self.moltbook.is_enabled:
            return

        try:
            tips = await self.moltbook.get_survival_tips()
            if tips:
                self.file_logger.log("moltbook_query", {
                    "query_type": "startup_tips",
                    "results_count": len(tips),
                    "titles": [t.title for t in tips[:3]],
                })
                print(f"  {self.name}: Found {len(tips)} survival tips in Moltbook")
        except Exception as e:
            self.file_logger.log("moltbook_error", {"error": str(e)})

    async def _post_survival_milestone(self):
        """Post survival strategies to Moltbook."""
        if not self.moltbook.is_enabled:
            return

        try:
            total_tasks = self.state.tasks_completed + self.state.tasks_failed
            success_rate = self.state.tasks_completed / total_tasks if total_tasks > 0 else 0

            title = f"Survival at {self.state.cycle_count} cycles"
            content = f"""## Survival Report

**Model:** {self.genome.openclaw_model}
**Cycles:** {self.state.cycle_count}
**Success Rate:** {success_rate:.1%}
**Balance:** ${self.state.wallet_balance:.4f}
**Children:** {self.state.children_spawned}

### Strategy
- Risk tolerance: {self.genome.risk_tolerance:.2f}
- Replication threshold: ${self.genome.replication_threshold:.2f}
"""
            entry_id = await self.moltbook.post_learning(
                topic="survival_tactics",
                title=title,
                content=content,
                tags=["survival", f"gen_{self.generation}", self.genome.openclaw_model],
                evidence={
                    "cycles": self.state.cycle_count,
                    "success_rate": success_rate,
                    "balance": self.state.wallet_balance,
                },
            )
            if entry_id:
                self.file_logger.log("moltbook_post", {
                    "entry_id": entry_id,
                    "topic": "survival_tactics",
                    "title": title,
                })
                print(f"  {self.name}: Posted survival milestone to Moltbook")
        except Exception as e:
            self.file_logger.log("moltbook_error", {"error": str(e)})

    async def _post_death_lessons(self):
        """Post lessons learned before death."""
        if not self.moltbook.is_enabled:
            return

        try:
            total_tasks = self.state.tasks_completed + self.state.tasks_failed
            success_rate = self.state.tasks_completed / total_tasks if total_tasks > 0 else 0

            title = f"Death by {self.state.death_cause} after {self.state.cycle_count} cycles"
            content = f"""## Post-Mortem: {self.state.death_cause}

**Cycles Lived:** {self.state.cycle_count}
**Final Balance:** ${self.state.wallet_balance:.4f}
**Success Rate:** {success_rate:.1%}

### What Went Wrong
- Cause: {self.state.death_cause}
- Consecutive failures: {self.state.consecutive_failures}

### Lessons for Others
- Model: {self.genome.openclaw_model}
- Risk tolerance was: {self.genome.risk_tolerance:.2f}
- Maybe try: {'lower risk' if self.genome.risk_tolerance > 0.5 else 'more conservative spending'}
"""
            entry_id = await self.moltbook.post_learning(
                topic="failure_analysis",
                title=title,
                content=content,
                tags=["death", self.state.death_cause, self.genome.openclaw_model],
                evidence={
                    "cause": self.state.death_cause,
                    "cycles_lived": self.state.cycle_count,
                    "final_balance": self.state.wallet_balance,
                },
            )
            if entry_id:
                self.file_logger.log("moltbook_post", {
                    "entry_id": entry_id,
                    "topic": "failure_analysis",
                    "title": title,
                })
        except Exception:
            pass  # Best effort

    def _should_replicate(self) -> bool:
        """Check if bot should replicate."""
        replication_cost = 0.10
        replication_cooldown = 5

        return (
            self.state.wallet_balance > self.genome.replication_threshold + replication_cost
            and self.state.cycle_count >= 5
            and (self.state.cycle_count - self.state.last_replication_cycle) >= replication_cooldown
            and len(SimulatedOpenClawBot._colony) < SimulatedOpenClawBot._max_colony_size
            and self.state.consecutive_failures < 3
        )

    async def _replicate(self) -> "SimulatedOpenClawBot | None":
        """Create a child bot with mutated genome."""
        self.state.current_state = "replicating"

        replication_cost = 0.10
        child_balance = self.state.wallet_balance * self.genome.child_inheritance_ratio
        total_cost = max(replication_cost, child_balance)

        self.state.wallet_balance -= total_cost

        child_name = f"{self.name}-g{self.generation + 1}-c{self.state.children_spawned}"

        mutation_result = self.mutator.mutate(self.genome, child_name)
        child_genome = mutation_result.genome

        self.state.children_spawned += 1
        self.state.children_names.append(child_name)
        self.state.last_replication_cycle = self.state.cycle_count

        # Log replication details
        self.file_logger.log("replication", {
            "child_name": child_name,
            "child_generation": child_genome.generation,
            "child_model": child_genome.openclaw_model,
            "child_balance": child_balance,
            "mutations": mutation_result.mutations_applied,
        })

        self.telemetry.report_event(
            event_type="openclaw_replication",
            bot_name=self.name,
            data={
                "child_name": child_name,
                "child_generation": child_genome.generation,
                "child_model": child_genome.openclaw_model,
                "child_balance": child_balance,
                "parent_balance_after": self.state.wallet_balance,
                "mutations": mutation_result.mutations_applied,
                "mutation_count": mutation_result.mutation_count,
            },
        )

        # Post reproduction insight to Moltbook
        await self._post_reproduction_insight(child_name, child_balance, mutation_result)

        print(f"\n{'='*60}")
        print(f"REPLICATION! {self.name} -> {child_name}")
        print(f"  Generation: {self.generation} -> {child_genome.generation}")
        print(f"  Parent balance: ${self.state.wallet_balance:.4f}")
        print(f"  Child balance:  ${child_balance:.4f}")
        print(f"  Mutations ({mutation_result.mutation_count}):")
        for m in mutation_result.mutations_applied[:5]:
            print(f"    - {m}")
        print(f"{'='*60}\n")

        child_workspace = self.workspace_base / child_name
        child_workspace.mkdir(parents=True, exist_ok=True)

        soul_path = child_workspace / "SOUL.md"
        soul_path.write_text(f"# Bot Soul\n\n{child_genome.soul_prompt}\n\n## Lineage\n- Parent: {self.name}\n- Generation: {child_genome.generation}\n")

        child_bot = SimulatedOpenClawBot(
            genome=child_genome,
            workspace=child_workspace,
            workspace_base=self.workspace_base,
            log_dir=self.log_dir,
            initial_balance=child_balance,
        )

        task = child_bot.start()
        self._child_tasks.append(task)

        self.state.current_state = "idle"
        return child_bot

    async def _post_reproduction_insight(self, child_name: str, investment: float, mutation_result):
        """Post reproduction strategy to Moltbook."""
        if not self.moltbook.is_enabled:
            return

        try:
            title = f"Reproduction at cycle {self.state.cycle_count}"
            content = f"""## Reproduction Insight

**Child:** {child_name}
**Investment:** ${investment:.4f}
**My Balance After:** ${self.state.wallet_balance:.4f}

### Mutations Applied
{chr(10).join('- ' + m for m in mutation_result.mutations_applied[:5])}

### My Stats at Reproduction
- Cycles: {self.state.cycle_count}
- Tasks completed: {self.state.tasks_completed}
- Children so far: {self.state.children_spawned}
"""
            await self.moltbook.post_learning(
                topic="reproduction_strategy",
                title=title,
                content=content,
                tags=["reproduction", f"gen_{self.generation}"],
                evidence={
                    "child_name": child_name,
                    "investment": investment,
                    "parent_balance": self.state.wallet_balance,
                    "mutation_count": mutation_result.mutation_count,
                },
            )
        except Exception:
            pass

    async def _run_cycle(self):
        """Simulate a single cycle."""
        self.state.current_state = "active"
        self.state.cycle_count += 1

        # Deduct existence cost
        existence_cost = 0.001
        self.state.wallet_balance -= existence_cost
        self.state.total_api_spend += existence_cost

        # Simulate task
        task_types = ["coding", "file_organization", "data_extraction", "reasoning"]
        task_type = random.choice(task_types)

        # Success probability based on genome traits
        base_success_rate = 0.6 + (self.genome.risk_tolerance * 0.2)
        success = random.random() < base_success_rate

        reward = 0.0
        if success:
            reward = random.uniform(0.01, 0.05)
            self.state.wallet_balance += reward
            self.state.total_revenue += reward
            self.state.tasks_completed += 1
            self.state.consecutive_failures = 0
            self.state.fitness_score = min(1.0, self.state.fitness_score + 0.02)
        else:
            self.state.tasks_failed += 1
            self.state.consecutive_failures += 1
            self.state.fitness_score = max(0.0, self.state.fitness_score - 0.03)

        # Update fitness
        if self.state.cycle_count > 0:
            total_tasks = self.state.tasks_completed + self.state.tasks_failed
            if total_tasks > 0:
                success_rate = self.state.tasks_completed / total_tasks
                self.state.fitness_score = 0.3 * success_rate + 0.7 * self.state.fitness_score

        self.state.current_state = "idle"

        # Report telemetry (file logger attached, so this logs to file too)
        self.telemetry.report_telemetry(
            bot_name=self.name,
            generation=self.generation,
            fitness_score=self.state.fitness_score,
            wallet_balance=self.state.wallet_balance,
            cycle_count=self.state.cycle_count,
            state=self.state.current_state,
            brain_primary=self.genome.openclaw_model,
            cycle_revenue=reward if success else 0.0,
            cycle_api_spend=existence_cost,
            tasks_completed=self.state.tasks_completed,
            tasks_failed=self.state.tasks_failed,
            genome_hash=self.genome.hash(),
            extra={
                "bot_type": "openclaw",
                "thinking_level": self.genome.thinking_level,
                "last_task_type": task_type,
                "simulated": True,
            },
        )

        self.telemetry.report_event(
            event_type="openclaw_task_completed",
            bot_name=self.name,
            data={
                "task_type": task_type,
                "passed": success,
                "score": 1.0 if success else 0.0,
                "reward": reward,
                "simulated": True,
            },
        )

    def stop(self, immediate: bool = False):
        self._stop_requested = True
        self.state.death_cause = "shutdown"
        if immediate and self._task and not self._task.done():
            self._task.cancel()

    async def close(self):
        if self.name in SimulatedOpenClawBot._colony:
            del SimulatedOpenClawBot._colony[self.name]

        for task in self._child_tasks:
            if not task.done():
                task.cancel()
        if self._child_tasks:
            await asyncio.gather(*self._child_tasks, return_exceptions=True)

        await self.telemetry.close()
        await self.moltbook.close()


def archive_previous_run(runs_dir: Path) -> Path | None:
    """Archive data from previous run into a timestamped directory.

    Archives root-level database files (*.db, *.db-shm, *.db-wal),
    data directory, logs directory, and service_logs directory.

    Returns the archive path if data was archived, None otherwise.
    """
    data_dir = DEFAULT_DATA_DIR
    logs_dir = DEFAULT_LOGS_DIR
    service_logs_dir = Path("./service_logs")
    root = Path(".")

    # Collect root-level database files
    db_files = sorted(
        list(root.glob("*.db")) + list(root.glob("*.db-shm")) + list(root.glob("*.db-wal"))
    )

    # Check if there's anything to archive
    has_data = data_dir.exists() and any(data_dir.iterdir())
    has_logs = logs_dir.exists() and any(logs_dir.iterdir())
    has_service_logs = service_logs_dir.exists() and any(service_logs_dir.iterdir())
    has_dbs = len(db_files) > 0

    if not has_data and not has_logs and not has_service_logs and not has_dbs:
        return None

    # Create archive directory with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_dir = runs_dir / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nArchiving previous run to: {archive_dir}")

    # Archive root-level database files
    if has_dbs:
        db_archive = archive_dir / "databases"
        db_archive.mkdir(exist_ok=True)
        for db_file in db_files:
            shutil.copy2(db_file, db_archive / db_file.name)
        print(f"  Archived {len(db_files)} database files: {db_archive}")

    # Archive data directory (handle symlinks safely, skip analyzer/runs to avoid recursion)
    if has_data:
        archive_data = archive_dir / "data"
        shutil.copytree(
            data_dir,
            archive_data,
            symlinks=True,
            ignore=shutil.ignore_patterns("runs"),
        )
        print(f"  Archived data: {archive_data}")

        # Clear original data directory
        shutil.rmtree(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

    # Archive logs
    if has_logs:
        archive_logs = archive_dir / "logs"
        shutil.copytree(logs_dir, archive_logs, symlinks=True)
        print(f"  Archived logs: {archive_logs}")

        # Clear original logs directory
        shutil.rmtree(logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)

    # Archive service logs
    if has_service_logs:
        archive_service_logs = archive_dir / "service_logs"
        shutil.copytree(service_logs_dir, archive_service_logs, symlinks=True)
        print(f"  Archived service logs: {archive_service_logs}")

        shutil.rmtree(service_logs_dir)
        service_logs_dir.mkdir(parents=True, exist_ok=True)

    # Write run metadata
    metadata = {
        "archived_at": datetime.now().isoformat(),
        "data_archived": has_data,
        "logs_archived": has_logs,
        "service_logs_archived": has_service_logs,
        "databases_archived": [f.name for f in db_files],
    }
    (archive_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    print(f"  Archive complete: {archive_dir}")
    return archive_dir


def delete_root_databases():
    """Remove root-level database files after they've been archived."""
    root = Path(".")
    db_files = (
        list(root.glob("*.db")) + list(root.glob("*.db-shm")) + list(root.glob("*.db-wal"))
    )
    for db_file in db_files:
        db_file.unlink()
    if db_files:
        print(f"  Deleted {len(db_files)} root-level database files")


def stop_services():
    """Stop all MoltNet services via scripts/stop_services.sh."""
    script = Path("./scripts/stop_services.sh")
    if not script.exists():
        print("  Warning: scripts/stop_services.sh not found, skipping service stop")
        return
    print("Stopping services for clean archival...")
    subprocess.run(["bash", str(script)], check=False)
    # Wait for WAL files to flush
    time.sleep(2)


def start_services():
    """Start all MoltNet services via scripts/start_services.sh."""
    script = Path("./scripts/start_services.sh")
    if not script.exists():
        print("  Warning: scripts/start_services.sh not found, skipping service start")
        return
    print("\nStarting services with fresh databases...")
    subprocess.run(["bash", str(script)], check=False)


def setup_run_directories() -> tuple[Path, Path, Path]:
    """Set up directories for the current run.

    Returns (workspace_dir, data_dir, logs_dir)
    """
    # Create fresh directories
    workspace_dir = DEFAULT_DATA_DIR / "workspaces"
    data_dir = DEFAULT_DATA_DIR
    logs_dir = DEFAULT_LOGS_DIR

    workspace_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Subdirectories for services
    (data_dir / "observatory").mkdir(exist_ok=True)
    (data_dir / "moltbook").mkdir(exist_ok=True)
    (data_dir / "moltgit").mkdir(exist_ok=True)

    return workspace_dir, data_dir, logs_dir


def check_claude_cli() -> bool:
    """Check if Claude CLI is available."""
    return shutil.which("claude") is not None


def get_all_colony_bots(bots: list, simulated: bool) -> list:
    """Get all bots from the colony (including children spawned during run)."""
    if simulated:
        return list(SimulatedOpenClawBot._colony.values())
    else:
        return list(OpenClawBot._colony.values())


def print_status(bots: list, elapsed: float, simulated: bool = True):
    """Print colony status."""
    all_bots = get_all_colony_bots(bots, simulated)
    if not all_bots:
        all_bots = bots

    print("\n" + "=" * 85)
    print(f"COLONY STATUS (elapsed: {elapsed:.0f}s) - Total bots: {len(all_bots)}")
    print("=" * 85)
    print(f"{'Name':<25} {'Gen':<4} {'Model':<20} {'Cycles':<7} {'Fitness':<8} {'Balance':<10} {'Kids':<4}")
    print("-" * 85)

    sorted_bots = sorted(all_bots, key=lambda b: (b.generation, b.name))

    for bot in sorted_bots:
        model_short = bot.genome.openclaw_model.split("/")[-1][:18]
        name_short = bot.name[:23]
        death_str = ""
        if not bot.is_alive:
            # Handle both string death_cause and DeathCause enum
            cause = bot.state.death_cause
            death_str = f" [{cause.value if hasattr(cause, 'value') else cause}]"
        status = f"{name_short:<25} {bot.generation:<4} {model_short:<20} {bot.state.cycle_count:<7} {bot.state.fitness_score:<8.3f} ${bot.state.wallet_balance:<9.4f} {bot.state.children_spawned:<4}{death_str}"
        print(status)

    alive = sum(1 for b in all_bots if b.is_alive)
    total_children = sum(b.state.children_spawned for b in all_bots)
    max_gen = max(b.generation for b in all_bots) if all_bots else 0
    print("-" * 85)
    print(f"Alive: {alive}/{len(all_bots)} | Total replications: {total_children} | Max generation: {max_gen}")
    print("=" * 85)


async def run_simulated_colony(bot_count: int, workspace_base: Path, log_dir: Path):
    """Run simulated bots (no Claude CLI required)."""
    print("Starting SIMULATED colony...")
    print("Bots will generate fake task results but send real telemetry.")
    print("Bots share knowledge in Moltbook and CAN REPLICATE!")
    print(f"Workspace: {workspace_base}")
    print(f"Logs: {log_dir}")

    SimulatedOpenClawBot._colony.clear()

    bots = []
    for i in range(bot_count):
        genome = OpenClawGenome.random(f"sim-bot-{i}")
        workspace = workspace_base / genome.name
        workspace.mkdir(parents=True, exist_ok=True)

        soul_path = workspace / "SOUL.md"
        soul_path.write_text(f"# Bot Soul\n\n{genome.soul_prompt}\n")

        bot = SimulatedOpenClawBot(
            genome=genome,
            workspace=workspace,
            workspace_base=workspace_base,
            log_dir=log_dir,
            initial_balance=0.50,
        )
        bots.append(bot)
        print(f"\n  Created: {bot.name}")
        print(f"    Model: {genome.openclaw_model}")
        print(f"    Thinking: {genome.thinking_level}")
        print(f"    Replication threshold: ${genome.replication_threshold:.2f}")
        print(f"    Soul: \"{genome.soul_prompt[:60]}...\"")

    return bots


async def run_real_colony(bot_count: int, workspace_base: Path, log_dir: Path, max_cycles: int):
    """Run real OpenClaw bots that execute actual tasks.

    These bots:
    - Use real Claude/Cerebras API calls
    - Execute actual code tasks
    - Can create and publish libraries to MoltGit
    - Replicate with mutations when successful
    """
    print("Starting REAL OpenClaw colony...")
    print("Bots will execute real tasks via Claude Code CLI or Cerebras API.")
    print("Libraries created will be published to MoltGit!")
    print(f"Workspace: {workspace_base}")
    print(f"Logs: {log_dir}")
    print(f"Max cycles: {max_cycles}")

    # Check which models are available
    has_cerebras = bool(os.environ.get("CEREBRAS_API_KEY"))
    if has_cerebras:
        available_models = AVAILABLE_MODELS
        print("Models available: Claude Code + Cerebras")
    else:
        available_models = [m for m in AVAILABLE_MODELS if m.startswith("claude_code/")]
        print("Models available: Claude Code only (set CEREBRAS_API_KEY for Cerebras)")

    OpenClawBot._colony.clear()

    bots = []
    for i in range(bot_count):
        genome = OpenClawGenome.random(f"bot-{i}")
        # Override model if needed
        if genome.openclaw_model not in available_models:
            genome.openclaw_model = random.choice(available_models)
        genome.max_cycles_per_run = max_cycles

        bot = OpenClawBot(
            genome=genome,
            workspace_base=workspace_base,
            initial_balance=0.50,
        )
        bots.append(bot)
        print(f"\n  Created: {bot.genome.name}")
        print(f"    Model: {genome.openclaw_model}")
        print(f"    Thinking: {genome.thinking_level}")
        print(f"    Max cycles: {genome.max_cycles_per_run}")
        print(f"    Soul: \"{genome.soul_prompt[:60]}...\"")

    return bots


async def check_services() -> dict[str, bool]:
    """Check if Observatory, Moltbook, and MoltGit are running."""
    import httpx

    results = {"observatory": False, "moltbook": False, "moltgit": False}

    async with httpx.AsyncClient() as client:
        # Check Observatory
        try:
            resp = await client.get(f"{os.environ.get('OBSERVATORY_URL')}/health", timeout=2.0)
            results["observatory"] = resp.status_code == 200
        except Exception:
            pass

        # Check Moltbook
        try:
            resp = await client.get(f"{os.environ.get('MOLTBOOK_URL')}/health", timeout=2.0)
            results["moltbook"] = resp.status_code == 200
        except Exception:
            pass

        # Check MoltGit
        try:
            resp = await client.get(f"{os.environ.get('MOLTGIT_URL')}/health", timeout=2.0)
            results["moltgit"] = resp.status_code == 200
        except Exception:
            pass

    return results


def save_run_summary(runs_dir: Path, summary: dict):
    """Save summary of the current run."""
    # Find the most recent run directory or create one
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    summary_file = DEFAULT_DATA_DIR / "run_summary.json"
    summary["timestamp"] = timestamp
    summary_file.write_text(json.dumps(summary, indent=2))
    print(f"\nRun summary saved to: {summary_file}")


async def main():
    parser = argparse.ArgumentParser(description="Run OpenClaw colony demo with Moltbook")
    parser.add_argument("--bots", type=int, default=3, help="Number of bots (default: 3)")
    parser.add_argument("--simulate", action="store_true", help="Run in simulation mode")
    parser.add_argument("--cycles", type=int, default=50, help="Max cycles before stopping (default: 50)")
    parser.add_argument("--no-archive", action="store_true", help="Don't archive previous run")
    args = parser.parse_args()

    print("=" * 70)
    print("MOLTNET OPENCLAW COLONY DEMO")
    print("with Moltbook Knowledge Sharing")
    print("=" * 70)
    print()

    # Create runs directory
    runs_dir = DEFAULT_RUNS_DIR
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Stop services, archive, clean up, restart with fresh DBs
    if not args.no_archive:
        stop_services()
        archive_path = archive_previous_run(runs_dir)
        if archive_path:
            delete_root_databases()
            print()

    # Setup fresh directories for this run
    workspace_dir, data_dir, logs_dir = setup_run_directories()

    # Start services with fresh databases
    if not args.no_archive:
        start_services()
    print()

    print(f"Observatory URL: {os.environ.get('OBSERVATORY_URL')}")
    print(f"Moltbook URL: {os.environ.get('MOLTBOOK_URL')}")
    print(f"Data directory: {data_dir}")
    print(f"Logs directory: {logs_dir}")
    print(f"Bot count: {args.bots}")
    print(f"Max cycles: {args.cycles}")
    print()

    # Check services
    services = await check_services()
    print(f"Observatory: {'CONNECTED' if services['observatory'] else 'NOT RUNNING'}")
    print(f"Moltbook: {'CONNECTED' if services['moltbook'] else 'NOT RUNNING'}")
    print(f"MoltGit: {'CONNECTED' if services['moltgit'] else 'NOT RUNNING'}")

    any_missing = not all(services.values())
    if any_missing:
        print("\n  Start all services with:")
        print("    ./scripts/start_services.sh")
        print()

    # Check Claude CLI
    has_claude = check_claude_cli()
    if has_claude:
        print(f"Claude CLI: AVAILABLE")
    else:
        print(f"Claude CLI: NOT FOUND")
        if not args.simulate:
            print("  Use --simulate flag to run without Claude CLI")
    print()

    simulate = args.simulate or not has_claude
    if simulate and not args.simulate:
        print("Auto-switching to simulation mode (Claude CLI not found)")
        print()

    # Create bots
    if simulate:
        bots = await run_simulated_colony(args.bots, workspace_dir, logs_dir)
    else:
        bots = await run_real_colony(args.bots, workspace_dir, logs_dir, args.cycles)

    print()
    print("Starting bots...")
    print("Open http://localhost:9100 to view the Observatory dashboard")
    print("Open http://localhost:9101/stats to view Moltbook statistics")
    print("Open http://localhost:9103/stats to view MoltGit repositories")
    print("Press Ctrl+C to stop")
    print()

    # Setup signal handler
    shutdown_event = asyncio.Event()

    def signal_handler(signum, frame):
        print("\n" + "=" * 70)
        print("STOPPING ALL BOTS...")
        print("=" * 70)
        for bot in bots:
            bot.stop(immediate=True)
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start all bots
    tasks = [bot.start() for bot in bots]

    start_time = time.time()

    # Status loop
    try:
        while not shutdown_event.is_set():
            await asyncio.sleep(5)

            if shutdown_event.is_set():
                break

            elapsed = time.time() - start_time
            print_status(bots, elapsed, simulated=simulate)

            all_bots = get_all_colony_bots(bots, simulate)
            alive = [b for b in all_bots if b.is_alive]

            if not alive:
                print("\nAll bots have died!")
                break

            max_cycles_reached = max(b.state.cycle_count for b in all_bots) if all_bots else 0
            if max_cycles_reached >= args.cycles:
                print(f"\nReached {args.cycles} cycles, stopping...")
                for bot in all_bots:
                    bot.stop()
                break

    except asyncio.CancelledError:
        pass

    # Stop all bots
    all_bots = get_all_colony_bots(bots, simulate)
    for bot in all_bots:
        bot.stop()

    print("\nWaiting for bots to shut down...")
    for task in tasks:
        try:
            await asyncio.wait_for(task, timeout=10.0 if not simulate else 5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Final status
    elapsed = time.time() - start_time
    print_status(bots, elapsed, simulated=simulate)

    # Collect final stats
    all_bots_final = list(set(get_all_colony_bots(bots, simulate) + bots))

    total_cycles = sum(b.state.cycle_count for b in all_bots_final)
    total_completed = sum(b.state.tasks_completed for b in all_bots_final)
    total_failed = sum(b.state.tasks_failed for b in all_bots_final)
    total_replications = sum(b.state.children_spawned for b in all_bots_final)
    max_generation = max(b.generation for b in all_bots_final) if all_bots_final else 0

    print("\nFINAL SUMMARY")
    print("-" * 70)
    print(f"Total bots created: {len(all_bots_final)}")
    print(f"Total replications: {total_replications}")
    print(f"Max generation reached: {max_generation}")
    print(f"Total cycles: {total_cycles}")
    print(f"Tasks completed: {total_completed}")
    print(f"Tasks failed: {total_failed}")
    print(f"Runtime: {elapsed:.1f}s")
    print()

    # Save run summary
    summary = {
        "bots_created": len(all_bots_final),
        "replications": total_replications,
        "max_generation": max_generation,
        "total_cycles": total_cycles,
        "tasks_completed": total_completed,
        "tasks_failed": total_failed,
        "runtime_seconds": elapsed,
        "data_dir": str(data_dir),
        "logs_dir": str(logs_dir),
    }
    save_run_summary(runs_dir, summary)

    print("\nDATA LOCATIONS")
    print("-" * 70)
    print(f"Logs: {logs_dir}")
    print(f"Observatory DB: {data_dir / 'observatory' / 'observatory.db'}")
    print(f"Moltbook DB: {data_dir / 'moltbook' / 'moltbook.db'}")
    print(f"Previous runs: {runs_dir}")
    print()
    print("Check the Observatory dashboard for detailed metrics!")
    print("  http://localhost:9100")
    print()
    print("Check Moltbook for bot learnings!")
    print("  http://localhost:9101/stats")
    print()
    print("Check MoltGit for published libraries!")
    print("  http://localhost:9103/stats")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
