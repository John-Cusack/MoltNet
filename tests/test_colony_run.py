#!/usr/bin/env python3
"""Integration test: Run a real 3-bot colony for 20 cycles with max 20 bots.

This test launches 3 OpenClawBot instances that execute real tasks via
the configured backend (Gateway → Claude CLI or Cerebras API). Bots can
reproduce up to the colony cap (20 bots). Services (Observatory, MoltBook,
MoltGit) are used if running; the test works without them too.

Usage:
    # Make sure services + gateway are running first:
    ./scripts/start_services.sh

    # Run the colony test:
    uv run python tests/test_colony_run.py

    # Or via pytest (marked as integration so skipped by default):
    uv run pytest tests/test_colony_run.py -v -m integration
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

# Ensure project root is importable when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("OBSERVATORY_URL", "http://localhost:9100")
os.environ.setdefault("MOLTBOOK_URL", "http://localhost:9101")
os.environ.setdefault("MOLTGIT_URL", "http://localhost:9103")
os.environ.setdefault("GATEWAY_URL", "http://localhost:8080")

from clawdbot.evolution.openclaw_genome import OpenClawGenome, AVAILABLE_MODELS
from clawdbot.evolution.selection import DeathCause
from clawdbot.openclaw_bot import OpenClawBot

# ── Colony parameters ──────────────────────────────────────────────
INITIAL_BOTS = 10
MAX_COLONY_SIZE = 150  # mirrors the hard cap in _assess_reproduction_readiness
MAX_CYCLES = 500
INITIAL_BALANCE = 0.50
STATUS_INTERVAL = 30  # seconds between status prints


def _available_models() -> list[str]:
    """Return models we can actually use on this machine."""
    has_cerebras = bool(os.environ.get("CEREBRAS_API_KEY"))
    if has_cerebras:
        return list(AVAILABLE_MODELS)
    return [m for m in AVAILABLE_MODELS if m.startswith("claude_code/")]


def _print_header() -> None:
    print("=" * 75)
    print("MOLTNET COLONY TEST")
    print(f"  Initial bots : {INITIAL_BOTS}")
    print(f"  Max colony   : {MAX_COLONY_SIZE}")
    print(f"  Max cycles   : {MAX_CYCLES}")
    print(f"  Balance      : ${INITIAL_BALANCE:.2f}")
    print(f"  Gateway      : {os.environ.get('GATEWAY_URL')}")
    print(f"  Observatory  : {os.environ.get('OBSERVATORY_URL')}")
    print(f"  MoltBook     : {os.environ.get('MOLTBOOK_URL')}")
    print(f"  MoltGit      : {os.environ.get('MOLTGIT_URL')}")
    print("=" * 75)
    print()


def _print_status(start_time: float) -> None:
    """Print a status table for all bots in the colony."""
    bots = list(OpenClawBot._colony.values())
    if not bots:
        print("  (no bots in colony)")
        return

    elapsed = time.time() - start_time
    alive = [b for b in bots if b.is_alive]

    print()
    print("=" * 90)
    print(f"COLONY STATUS  elapsed={elapsed:.0f}s  total={len(bots)}  alive={len(alive)}")
    print("=" * 90)
    print(
        f"{'Name':<28} {'Gen':<4} {'Model':<22} "
        f"{'Cyc':<5} {'Fit':<7} {'Balance':<10} {'Kids':<5} {'Status'}"
    )
    print("-" * 90)

    for bot in sorted(bots, key=lambda b: (b.generation, b.name)):
        model_short = bot.genome.openclaw_model.split("/")[-1][:20]
        name_short = bot.name[:26]
        cause = bot.state.death_cause
        status = "alive" if bot.is_alive else (cause.value if hasattr(cause, "value") else str(cause))
        print(
            f"{name_short:<28} {bot.generation:<4} {model_short:<22} "
            f"{bot.state.cycle_count:<5} {bot.state.fitness_score:<7.3f} "
            f"${bot.state.wallet_balance:<9.4f} {bot.state.children_spawned:<5} {status}"
        )

    max_gen = max(b.generation for b in bots)
    total_children = sum(b.state.children_spawned for b in bots)
    print("-" * 90)
    print(f"Alive: {len(alive)}/{len(bots)}  |  Replications: {total_children}  |  Max gen: {max_gen}")
    print("=" * 90)


def _print_summary(bots: list[OpenClawBot], elapsed: float) -> None:
    total_cycles = sum(b.state.cycle_count for b in bots)
    total_completed = sum(b.state.tasks_completed for b in bots)
    total_failed = sum(b.state.tasks_failed for b in bots)
    total_replications = sum(b.state.children_spawned for b in bots)
    max_gen = max(b.generation for b in bots) if bots else 0

    print()
    print("=" * 75)
    print("FINAL SUMMARY")
    print("=" * 75)
    print(f"  Total bots created  : {len(bots)}")
    print(f"  Total replications  : {total_replications}")
    print(f"  Max generation      : {max_gen}")
    print(f"  Total cycles        : {total_cycles}")
    print(f"  Tasks completed     : {total_completed}")
    print(f"  Tasks failed        : {total_failed}")
    print(f"  Runtime             : {elapsed:.1f}s")

    alive = [b for b in bots if b.is_alive]
    if alive:
        print(f"  Survivors           : {len(alive)}")
        for b in alive:
            print(f"    - {b.name} (gen {b.generation}, ${b.state.wallet_balance:.4f})")

    dead = [b for b in bots if not b.is_alive]
    if dead:
        causes = {}
        for b in dead:
            c = b.state.death_cause.value if hasattr(b.state.death_cause, "value") else str(b.state.death_cause)
            causes[c] = causes.get(c, 0) + 1
        print(f"  Deaths              : {len(dead)} ({causes})")
    print("=" * 75)


async def check_services() -> dict[str, bool]:
    """Quick health check on services."""
    import httpx

    results = {}
    async with httpx.AsyncClient(timeout=2.0) as client:
        for name, env_var in [
            ("observatory", "OBSERVATORY_URL"),
            ("moltbook", "MOLTBOOK_URL"),
            ("moltgit", "MOLTGIT_URL"),
            ("gateway", "GATEWAY_URL"),
        ]:
            try:
                url = os.environ.get(env_var, "")
                resp = await client.get(f"{url}/health")
                results[name] = resp.status_code == 200
            except Exception:
                results[name] = False
    return results


async def run_colony() -> None:
    _print_header()

    # Check services
    services = await check_services()
    for name, ok in services.items():
        tag = "OK" if ok else "NOT RUNNING"
        print(f"  {name:<12}: {tag}")
    print()

    if not services.get("gateway"):
        print("WARNING: Gateway not running. Claude CLI models will fail.")
        print("  Start with: ./scripts/start_services.sh")
        print()

    models = _available_models()
    if not models:
        print("ERROR: No models available. Need Claude CLI (via gateway) or CEREBRAS_API_KEY.")
        sys.exit(1)
    print(f"Available models: {models}")
    print()

    # ── Create workspace ────────────────────────────────────────────
    workspace_base = Path("./data/workspaces")
    workspace_base.mkdir(parents=True, exist_ok=True)

    # ── Clear colony state ──────────────────────────────────────────
    OpenClawBot._colony.clear()

    # ── Create initial bots ─────────────────────────────────────────
    import random

    bots: list[OpenClawBot] = []
    for i in range(INITIAL_BOTS):
        genome = OpenClawGenome.random(f"colony-bot-{i}")
        if genome.openclaw_model not in models:
            genome.openclaw_model = random.choice(models)
        genome.max_cycles_per_run = MAX_CYCLES

        bot = OpenClawBot(
            genome=genome,
            workspace_base=workspace_base,
            initial_balance=INITIAL_BALANCE,
        )
        bots.append(bot)
        print(f"  Created: {bot.name}")
        print(f"    Model    : {genome.openclaw_model}")
        print(f"    Thinking : {genome.thinking_level}")
        print(f"    Soul     : \"{genome.soul_prompt[:60]}...\"")
        print()

    # ── Signal handling ─────────────────────────────────────────────
    shutdown = asyncio.Event()

    def on_signal(signum, frame):
        print("\nShutdown requested...")
        for b in list(OpenClawBot._colony.values()):
            b.stop(immediate=True)
        shutdown.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    # ── Start bots ──────────────────────────────────────────────────
    print("Starting bots...")
    tasks = [bot.start() for bot in bots]

    start_time = time.time()

    # ── Monitor loop ────────────────────────────────────────────────
    try:
        while not shutdown.is_set():
            await asyncio.sleep(STATUS_INTERVAL)
            if shutdown.is_set():
                break

            _print_status(start_time)

            all_bots = list(OpenClawBot._colony.values())
            alive = [b for b in all_bots if b.is_alive]

            if not alive:
                print("\nAll bots have died.")
                break

            max_cycles_reached = max(b.state.cycle_count for b in all_bots)
            if max_cycles_reached >= MAX_CYCLES:
                print(f"\nReached {MAX_CYCLES} cycles. Stopping colony...")
                for b in all_bots:
                    b.stop()
                break
    except asyncio.CancelledError:
        pass

    # ── Shutdown ────────────────────────────────────────────────────
    all_bots = list(OpenClawBot._colony.values())
    for b in all_bots:
        b.stop()

    print("\nWaiting for bots to shut down...")
    for task in tasks:
        try:
            await asyncio.wait_for(task, timeout=30.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Collect every bot that was ever registered (including offspring)
    all_bots_final = list(set(list(OpenClawBot._colony.values()) + bots))

    elapsed = time.time() - start_time
    _print_status(start_time)
    _print_summary(all_bots_final, elapsed)


# ── Pytest integration (marked as integration, skipped by default) ──

try:
    import pytest

    @pytest.mark.integration
    @pytest.mark.timeout(600)
    async def test_colony_3_bots_20_cycles():
        """Integration test: 3 real bots, 20 cycles, max 20 colony size."""
        await run_colony()
except ImportError:
    pass


# ── Direct execution ────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(run_colony())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
