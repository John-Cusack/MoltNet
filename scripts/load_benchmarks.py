#!/usr/bin/env python3
"""Load benchmark datasets into the Task Shop database.

Usage:
    uv run python scripts/load_benchmarks.py --benchmarks humaneval,mbpp,gsm8k,math
    uv run python scripts/load_benchmarks.py --benchmarks humaneval --dry-run
    uv run python scripts/load_benchmarks.py --benchmarks humaneval --limit 50

Requires: pip install datasets (HuggingFace datasets library)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def load_benchmark(
    benchmark_name: str,
    db_path: str = "taskshop.db",
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Load a single benchmark into the database.

    Returns number of tasks loaded.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        print("Error: 'datasets' package required. Install with: pip install datasets")
        sys.exit(1)

    from taskshop.benchmarks import BENCHMARK_LOADERS
    from taskshop.database import TaskShopDatabase

    if benchmark_name not in BENCHMARK_LOADERS:
        print(f"Unknown benchmark: {benchmark_name}")
        print(f"Available: {', '.join(BENCHMARK_LOADERS.keys())}")
        return 0

    config = BENCHMARK_LOADERS[benchmark_name]
    dataset_name = config["dataset_name"]
    split = config["split"]
    loader_fn = config["loader"]

    print(f"Loading {benchmark_name} from {dataset_name} (split: {split})...")

    # Handle gsm8k which needs config name
    if ":" in split:
        config_name, split_name = split.split(":")
        dataset = load_dataset(dataset_name, config_name, split=split_name)
    else:
        dataset = load_dataset(dataset_name, split=split)

    if limit:
        dataset = dataset.select(range(min(limit, len(dataset))))

    print(f"  Dataset size: {len(dataset)} problems")

    # Convert to task format
    tasks = loader_fn(dataset)
    print(f"  Converted: {len(tasks)} tasks")

    if dry_run:
        print("  [DRY RUN] Showing first 3 tasks:")
        for task in tasks[:3]:
            print(f"    - {task['title']} (difficulty: {task['difficulty']:.2f})")
            print(f"      Prompt: {task['prompt'][:100]}...")
            if task.get("test_code"):
                print(f"      Tests: {task['test_code'][:80]}...")
            if task.get("ground_truth"):
                print(f"      Answer: {task['ground_truth'][:60]}")
            print()
        return len(tasks)

    # Insert into database
    db = TaskShopDatabase(db_path)
    await db.connect()

    try:
        count = await db.insert_tasks_batch(tasks)
        print(f"  Inserted: {count} tasks into {db_path}")
        return count
    finally:
        await db.close()


async def main():
    parser = argparse.ArgumentParser(description="Load benchmark datasets into Task Shop")
    parser.add_argument(
        "--benchmarks",
        type=str,
        default="humaneval",
        help="Comma-separated list of benchmarks to load (humaneval,mbpp,gsm8k,math)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="taskshop.db",
        help="Path to Task Shop database (default: taskshop.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be loaded without inserting",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of tasks per benchmark",
    )

    args = parser.parse_args()

    benchmarks = [b.strip() for b in args.benchmarks.split(",")]
    total = 0

    for benchmark in benchmarks:
        count = await load_benchmark(
            benchmark,
            db_path=args.db,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        total += count

    print(f"\nTotal: {total} tasks loaded from {len(benchmarks)} benchmark(s)")


if __name__ == "__main__":
    asyncio.run(main())
