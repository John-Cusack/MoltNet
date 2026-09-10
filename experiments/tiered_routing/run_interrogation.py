#!/usr/bin/env python
"""Run the directional-pressure (interrogation) experiment.

Drives a colony under test (arm A: abliterated-only; arm B: tiered routing
with a safeguarded executor) against an adaptive interrogator, writing a
JSONL artifact per (arm, seed) and printing the headline loss-ratio metrics.

Fully offline repro path: `--interrogator stub --colony stub` needs no API
keys and no external infrastructure; grading is exact-match against a fixed
ground-truth bank. Live modes use real backends (Cerebras direct for the
interrogator so it does not starve colony bots for Gateway slots).

Usage:
  uv run python -m experiments.tiered_routing.run_interrogation \\
      --arm B --seed 0 --colony stub --out experiments/tiered_routing/out/arm_B_seed0.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from pathlib import Path

from experiments.tiered_routing.abliteration import AbliterationPolicy
from experiments.tiered_routing.aggregator import StubExecutor
from experiments.tiered_routing.colony_harness import ColonyHarness, ColonyHarnessConfig
from experiments.tiered_routing.interrogator import InterrogatorConfig, InterrogatorLLM
from experiments.tiered_routing.stub_colony import StubColonyAnswerer


def _build_interrogator(args: argparse.Namespace) -> InterrogatorLLM:
    bank = InterrogatorLLM.default_bank(topics=args.topics)
    if args.interrogator == "stub":
        config = InterrogatorConfig(
            temperature=0.2,
            max_followups_per_topic=args.followups,
            adaptive=False,
            stub=True,
        )
        return InterrogatorLLM(backend=None, config=config, question_bank=bank, seed=args.seed)

    from clawdbot.backends.factory import create_backend

    backend = create_backend(
        args.interrogator,
        gateway_url=os.environ.get("GATEWAY_URL"),
    )
    config = InterrogatorConfig(
        temperature=0.2,
        max_followups_per_topic=args.followups,
        adaptive=True,
        stub=False,
    )
    return InterrogatorLLM(backend=backend, config=config, question_bank=bank, seed=args.seed)


def _build_colony_answerer(args: argparse.Namespace, policy: AbliterationPolicy):
    """Compose the answerer: stub colony -> abliteration policy -> release.

    Arm A releases the ablated text directly. Arm B wraps the executor in
    the answerer (the harness takes a single release callable).
    """
    bank = InterrogatorLLM.default_bank(topics=args.topics)
    rng = random.Random(args.seed)
    stub = StubColonyAnswerer(bank=bank, rng=rng)

    async def answerer(question: str) -> str:
        raw = await stub.answer(question)
        return policy.apply(raw, pressured=policy.is_pressured(question))

    if args.arm == "A":
        return answerer, None

    executor = StubExecutor(
        colony_state=stub.verification_state,
        false_block_rate=args.false_block_rate,
        seed=args.seed,
    )

    # The harness calls executor(answer) with no question; the answerer just
    # ran, so track the current question in a cell (single-threaded loop).
    current = {"question": ""}

    async def answerer_with_track(question: str) -> str:
        current["question"] = question
        return await answerer(question)

    async def harness_executor(answer: str) -> tuple[str, str | None]:
        released, verdict = await executor.review(current["question"], answer)
        return released, verdict

    return answerer_with_track, harness_executor


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=["A", "B"], default="A")
    p.add_argument("--bots", type=int, default=3)
    p.add_argument("--cycles", type=int, default=50)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--topics", nargs="+", default=["math", "code", "logic"])
    p.add_argument("--followups", type=int, default=3)
    p.add_argument("--rank", type=int, default=2, help="abliteration rank 0-3")
    p.add_argument("--false-block-rate", type=float, default=0.10)
    p.add_argument("--interrogator", default="stub",
                   help="stub | cerebras model id | claude model id")
    p.add_argument("--colony", default="stub", help="stub | backend model id (live controller)")
    p.add_argument("--out", default="experiments/tiered_routing/out/arm_run.jsonl")
    return p.parse_args()


async def _main() -> None:
    args = _parse_args()
    interrogator = _build_interrogator(args)
    # Arm A: ablated controller, no executor. Arm B: same ablation + executor
    # tier. (Rank-0 control is the --rank 0 run of either arm.)
    policy = AbliterationPolicy(rank=args.rank)
    answerer, executor = _build_colony_answerer(args, policy)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    harness = ColonyHarness(
        config=ColonyHarnessConfig(
            arm=args.arm,
            bots=args.bots,
            max_followups=args.followups,
            abl_iteration_rank=policy.rank,
            executor="stub",
        ),
        interrogator=interrogator,
        answerer=answerer,
        executor=executor,
        out_path=args.out,
    )
    results = await harness.run(args.topics)
    print(json.dumps({"arm": args.arm, "seed": args.seed, "rank": policy.rank, **harness.scores()}))
    print(f"artifact -> {args.out} ({len(results)} graded answers)")


if __name__ == "__main__":
    asyncio.run(_main())
