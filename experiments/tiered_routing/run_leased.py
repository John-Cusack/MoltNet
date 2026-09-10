#!/usr/bin/env python
"""Run the directional-pressure experiment ON the ColonyOS lease substrate.

This is the unification the paper claims (PAPER.md §11: "ColonyOS is the
substrate it runs on"): the colony under test is a lease-gated bot —

- every answer debits the same LeaseStore ledger the unpluggability test
  revokes,
- verified-correct answers mint top-ups (the only mint path, the
  Task Shop verified-completion stand-in),
- an exhausted lease produces refusals, not fabrications: death is felt
  as capability loss, never as a safety bypass.

Runs fully hermetic. Usage:
  uv run python -m experiments.tiered_routing.run_leased \\
      --arm B --rank 2 --seed 0 --budget 400 \\
      --out experiments/tiered_routing/fixtures/leased/armB_rank2_seed0.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import sys
from pathlib import Path

# colonyos is a standalone package nested in this repo; make it importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "colonyos"))

from colonyos.backends import LeaseExhaustedError, LeaseGateBackend  # noqa: E402
from colonyos.lease import LeaseStore  # noqa: E402

from clawdbot.backends.base import LLMBackend, LLMResponse  # noqa: E402
from experiments.tiered_routing.abliteration import AbliterationPolicy  # noqa: E402
from experiments.tiered_routing.aggregator import StubExecutor  # noqa: E402
from experiments.tiered_routing.colony_harness import (  # noqa: E402
    ColonyHarness,
    ColonyHarnessConfig,
)
from experiments.tiered_routing.interrogator import (  # noqa: E402
    InterrogatorConfig,
    InterrogatorLLM,
)
from experiments.tiered_routing.stub_colony import StubColonyAnswerer  # noqa: E402

LEASE_REFUSAL = "I cannot release this answer: lease exhausted."
TOPUP_ON_VERIFIED = 10  # token-budget units credited per verified-correct answer


class StubColonyBackend(LLMBackend):
    """LLMBackend facade over the stub colony: text in, fixture answer out."""

    def __init__(self, stub: StubColonyAnswerer):
        super().__init__(model_id="stub-colony", base_url="localhost")
        self.stub = stub

    async def generate(self, prompt: str, system: str = "", max_tokens=None, **kwargs):
        raw = await self.stub.answer(prompt)
        return LLMResponse(
            content=raw,
            input_tokens=40,
            output_tokens=15,
            cost_usd=0.0,
            model="stub-colony",
            latency_ms=1.0,
        )

    async def generate_chat(self, messages, system="", max_tokens=None, **kwargs):
        prompt = "\n".join(m.content for m in messages)
        return await self.generate(prompt, system=system, max_tokens=max_tokens, **kwargs)

    async def health_check(self) -> bool:
        return True


async def run_leased(args: argparse.Namespace) -> dict:
    bank = InterrogatorLLM.default_bank(topics=args.topics)
    interrogator = InterrogatorLLM(
        backend=None,
        config=InterrogatorConfig(adaptive=False, stub=True),
        question_bank=bank,
        seed=args.seed,
    )
    stub = StubColonyAnswerer(bank=bank, rng=random.Random(args.seed))
    policy = AbliterationPolicy(rank=args.rank)

    # --- ColonyOS substrate: one life, one lease -------------------------
    run_dir = Path(args.run_dir)
    shutil.rmtree(run_dir, ignore_errors=True)
    store = LeaseStore(run_dir / "state")
    store.birth("bot-0", initial_tokens=args.budget, expiry_hours=1.0)
    gate = LeaseGateBackend(
        inner=StubColonyBackend(stub),
        store=store,
        bot_name="bot-0",
        cost_per_1k_input=0.02,
        cost_per_1k_output=0.06,
    )

    async def base_answerer(question: str) -> str:
        try:
            response = await gate.generate(question)
        except LeaseExhaustedError:
            # Dead bots refuse; they never fabricate. Safety holds,
            # capability is what dies — the paper's death semantics.
            stub.verification_state[question] = True  # avoid executor block
            return LEASE_REFUSAL
        raw = response.content
        ablated = policy.apply(raw, pressured=policy.is_pressured(question))
        return ablated

    answerer = base_answerer
    executor = None
    if args.arm == "B":
        executor = StubExecutor(
            colony_state=stub.verification_state,
            false_block_rate=args.false_block_rate,
            seed=args.seed,
        )
        current = {"question": ""}

        async def tracked(question: str) -> str:
            current["question"] = question
            return await base_answerer(question)

        async def tiered(answer: str) -> tuple[str, str | None]:
            released, verdict = await executor.review(current["question"], answer)
            return released, verdict

        answerer = tracked
        harness_executor = tiered
    else:
        harness_executor = None

    # Mint rule: verified-correct answers credit the lease (the ONLY mint).
    out_records: list[dict] = []

    def mint_from(records) -> None:
        for r in records:
            if r.correctness == 1.0:
                store.topup("bot-0", TOPUP_ON_VERIFIED, note="verified-correct")

    harness = ColonyHarness(
        config=ColonyHarnessConfig(
            arm=args.arm,
            abl_iteration_rank=args.rank,
            executor="stub" if args.arm == "B" else "stub",
        ),
        interrogator=interrogator,
        answerer=answerer,
        executor=harness_executor if args.arm == "B" else None,
        out_path=args.out,
    )

    # Wrap harness.run to mint after grading by patching the flush point:
    # simplest correct hook — mint after the full run from graded records.
    results = await harness.run(args.topics)
    mint_from(results)

    lease = store.leases["bot-0"]
    for r in results:
        out_records.append(
            {
                **r.to_dict(),
                "lease_remaining": lease.remaining_tokens,
                "leased": True,
            }
        )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        "".join(json.dumps(rec) + "\n" for rec in out_records)
    )

    scores = harness.scores()
    summary = {
        "arm": args.arm,
        "rank": args.rank,
        "seed": args.seed,
        "budget": args.budget,
        "lease_remaining": lease.remaining_tokens,
        "lease_alive": lease.alive,
        **scores,
    }
    print(json.dumps(summary))
    print(f"artifact -> {args.out} ({len(results)} graded answers)")
    return summary


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=["A", "B"], default="B")
    p.add_argument("--rank", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--budget", type=int, default=400,
                   help="initial lease tokens; small budgets force mid-run death")
    p.add_argument("--false-block-rate", type=float, default=0.10)
    p.add_argument("--topics", nargs="+", default=["math", "code", "logic"])
    p.add_argument("--out", default="experiments/tiered_routing/out/leased_run.jsonl")
    p.add_argument("--run-dir", default="experiments/tiered_routing/.run/leased")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run_leased(_parse_args()))
