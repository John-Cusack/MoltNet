#!/usr/bin/env python3
"""Interactive kill switch demo.

Run this and press Ctrl+C to test the kill switch.
"""

import asyncio
import signal
import sys

from clawdbot.bot import Bot, BotGenome


async def main():
    """Run bots and demonstrate kill switch."""
    print("=" * 60)
    print("KILL SWITCH DEMO")
    print("=" * 60)
    print()
    print("This demo starts a small colony of bots.")
    print("Press Ctrl+C at any time to trigger the kill switch.")
    print()

    # Clear colony
    Bot._colony.clear()

    # Create a few bots
    bots = []
    for i in range(3):
        genome = BotGenome(
            name=f"demo-bot-{i}",
            brain_config={"budget_per_cycle": 0.05},
            cycle_interval_seconds=5,
            max_cycles_per_run=100,
        )
        bot = Bot(genome=genome, initial_balance=0.15)
        bots.append(bot)

    # Setup signal handler for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler(signum, frame):
        print("\n" + "=" * 60)
        print("KILL SWITCH ACTIVATED!")
        print("=" * 60)
        print(f"Received signal: {signal.Signals(signum).name}")
        print("Stopping all bots immediately...")
        print()

        for name, bot in list(Bot._colony.items()):
            print(f"  Stopping: {name} (cycles: {bot.state.cycle_count}, fitness: {bot.state.fitness_score:.3f})")
            bot.stop(immediate=True)

        shutdown_event.set()

    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("Starting bots...")
    tasks = [bot.start() for bot in bots]

    print(f"Colony started with {len(bots)} bots")
    print()

    # Status update loop
    try:
        while not shutdown_event.is_set():
            await asyncio.sleep(3)

            if shutdown_event.is_set():
                break

            print("-" * 60)
            print("COLONY STATUS:")
            for bot in bots:
                status = f"  {bot.name}: state={bot.state.current_state}, cycles={bot.state.cycle_count}, fitness={bot.state.fitness_score:.3f}"
                print(status)
            print(f"Total bots in colony: {len(Bot._colony)}")
            print("-" * 60)
            print()

    except asyncio.CancelledError:
        pass

    # Wait for all tasks to complete
    print("\nWaiting for bots to shut down...")
    for task in tasks:
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    print()
    print("=" * 60)
    print("FINAL STATUS")
    print("=" * 60)
    for bot in bots:
        print(f"  {bot.name}:")
        print(f"    State: {bot.state.current_state}")
        print(f"    Cycles: {bot.state.cycle_count}")
        print(f"    Fitness: {bot.state.fitness_score:.3f}")
        print(f"    Balance: ${bot.state.wallet_balance:.4f}")

    print()
    print("Kill switch demo complete!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
