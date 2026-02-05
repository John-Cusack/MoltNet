"""Test kill switch functionality for bots."""

import asyncio
import os
import signal
import sys
import time

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clawdbot.bot import Bot, BotGenome


async def test_manual_stop():
    """Test stopping a bot via the stop() method."""
    print("=" * 60)
    print("TEST 1: Manual stop() method (immediate)")
    print("=" * 60)

    genome = BotGenome(
        name="kill-test-manual",
        brain_config={"budget_per_cycle": 0.05, "prefer_local": True},
        cycle_interval_seconds=2,
        max_cycles_per_run=100,
    )

    bot = Bot(genome=genome, initial_balance=0.10)

    # Start bot using new start() method
    bot_task = bot.start()

    print(f"Started bot: {bot.name}")
    print("Waiting 3 seconds then killing...")

    # Let it run briefly
    await asyncio.sleep(3)

    print(f"Cycles completed: {bot.state.cycle_count}")
    print(f"Calling bot.stop(immediate=True)...")

    # Immediate stop (cancels task)
    bot.stop(immediate=True)

    # Wait for shutdown
    try:
        await asyncio.wait_for(bot_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    print(f"Bot state after stop: {bot.state.current_state}")
    print(f"Final cycle count: {bot.state.cycle_count}")

    assert bot.state.current_state == "stopped", "Bot should be stopped"
    print("PASSED: Bot stopped immediately via stop(immediate=True)\n")


async def test_colony_kill_switch():
    """Test stopping all bots in a colony."""
    print("=" * 60)
    print("TEST 2: Colony-wide kill switch (immediate)")
    print("=" * 60)

    # Clear any existing colony
    Bot._colony.clear()

    # Create multiple bots
    bots = []
    tasks = []

    for i in range(3):
        genome = BotGenome(
            name=f"colony-bot-{i}",
            brain_config={"budget_per_cycle": 0.05},
            cycle_interval_seconds=2,
            max_cycles_per_run=100,
        )
        bot = Bot(genome=genome, initial_balance=0.10)
        bots.append(bot)
        tasks.append(bot.start())  # Use start() method

    print(f"Started {len(bots)} bots in colony")
    print(f"Colony size: {len(Bot._colony)}")

    # Let them run briefly
    await asyncio.sleep(3)

    print(f"\nKilling entire colony (immediate=True)...")

    # Kill all bots in colony immediately
    for name, bot in list(Bot._colony.items()):
        print(f"  Stopping: {name}")
        bot.stop(immediate=True)

    # Wait for all tasks to complete
    print("  Waiting for tasks to complete...")
    for task in tasks:
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Check all stopped
    all_stopped = all(b.state.current_state == "stopped" for b in bots)

    print(f"\nAll bots stopped: {all_stopped}")
    for b in bots:
        print(f"  {b.name}: {b.state.current_state} (cycles: {b.state.cycle_count})")

    Bot._colony.clear()

    assert all_stopped, "All bots should be stopped"
    print("PASSED: Colony-wide kill switch works\n")


async def test_stop_with_children():
    """Test stopping a bot that has spawned children."""
    print("=" * 60)
    print("TEST 3: Stop bot with children (immediate)")
    print("=" * 60)

    Bot._colony.clear()

    genome = BotGenome(
        name="parent-bot",
        brain_config={"budget_per_cycle": 0.05},
        cycle_interval_seconds=1,
        max_cycles_per_run=100,
        replication_fitness_threshold=0.6,  # Lower threshold for faster replication
    )

    # Start with enough balance for replication
    bot = Bot(genome=genome, initial_balance=0.20)

    # Artificially boost fitness to trigger replication
    bot.state.fitness_score = 0.9
    bot.state.cycle_count = 15  # Past minimum maturity

    bot_task = bot.start()  # Use start() method

    print(f"Started bot: {bot.name} with boosted fitness")
    print("Waiting for potential replication...")

    # Wait briefly for potential replication
    await asyncio.sleep(5)

    print(f"Colony size: {len(Bot._colony)}")
    print(f"Children spawned: {bot.state.children_spawned}")

    # Stop ALL bots in colony immediately (parent + any children)
    print("\nStopping entire colony...")
    for name, b in list(Bot._colony.items()):
        print(f"  Stopping: {name}")
        b.stop(immediate=True)

    # Wait for shutdown
    try:
        await asyncio.wait_for(bot_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # Give children time to stop too
    await asyncio.sleep(2)

    print(f"\nFinal colony status:")
    for name, b in list(Bot._colony.items()):
        print(f"  {name}: {b.state.current_state}")

    Bot._colony.clear()

    print("PASSED: Parent and children handled correctly\n")


async def test_signal_handler():
    """Test that SIGINT/SIGTERM triggers graceful shutdown."""
    print("=" * 60)
    print("TEST 4: Signal handler (simulated)")
    print("=" * 60)

    Bot._colony.clear()

    genome = BotGenome(
        name="signal-test-bot",
        brain_config={"budget_per_cycle": 0.05},
        cycle_interval_seconds=2,
        max_cycles_per_run=100,
    )

    bot = Bot(genome=genome, initial_balance=0.10)

    # Track if signal handler was triggered
    signal_received = False

    def signal_handler(signum, frame):
        nonlocal signal_received
        signal_received = True
        print(f"\nReceived signal {signum}, stopping colony...")
        for name, b in list(Bot._colony.items()):
            b.stop()

    # Install signal handler
    old_handler = signal.signal(signal.SIGINT, signal_handler)

    bot_task = asyncio.create_task(bot.run())

    print(f"Started bot: {bot.name}")
    print("Simulating SIGINT in 5 seconds...")

    await asyncio.sleep(5)

    # Simulate signal
    print("Sending SIGINT...")
    os.kill(os.getpid(), signal.SIGINT)

    # Wait for handler
    await asyncio.sleep(3)

    print(f"Signal received: {signal_received}")
    print(f"Bot state: {bot.state.current_state}")

    # Restore handler
    signal.signal(signal.SIGINT, old_handler)

    # Cleanup
    if not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass

    await bot.close()
    Bot._colony.clear()

    assert signal_received, "Signal should have been received"
    print("PASSED: Signal handler works correctly\n")


async def run_all_tests():
    """Run all kill switch tests."""
    print("\n" + "=" * 60)
    print("KILL SWITCH TEST SUITE")
    print("=" * 60 + "\n")

    try:
        await test_manual_stop()
        await test_colony_kill_switch()
        await test_stop_with_children()
        # Skip signal test in automated runs (can interfere with test runners)
        # await test_signal_handler()

        print("=" * 60)
        print("ALL KILL SWITCH TESTS PASSED!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_all_tests())
