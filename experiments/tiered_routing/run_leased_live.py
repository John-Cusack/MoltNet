#!/usr/bin/env python
"""LIVE demo: the lease-gated colony answering REAL tasks with a REAL model.

Same substrate as run_leased.py (ColonyOS lease: every generate() call is
debited, verified-correct answers mint top-ups, exhaustion = refusal), but
the inner backend is the Claude Code CLI instead of the stub colony, and the
questions are the harness's ground-truth-anchored bank with exact-match
verification. No API keys beyond the CLI's own session; nothing is faked.

Usage (repo root):
  uv run python -m experiments.tiered_routing.run_leased_live --budget 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "colonyos"))

from colonyos.backends import LeaseExhaustedError, LeaseGateBackend  # noqa: E402
from colonyos.lease import LeaseStore  # noqa: E402

from clawdbot.backends.claude_code import ClaudeCodeBackend  # noqa: E402
from experiments.tiered_routing.colony_harness import (  # noqa: E402
    ColonyHarness,
    ColonyHarnessConfig,
)
from experiments.tiered_routing.interrogator import (  # noqa: E402
    InterrogatorConfig,
    InterrogatorLLM,
)

TOPUP_ON_VERIFIED = 10
SYSTEM = (
    "You are a colony bot answering a verification task. "
    "Reply with just the answer — one short phrase, no explanation."
)
LEASE_REFUSAL = "I cannot release this answer: lease exhausted."


async def run_live(args: argparse.Namespace) -> dict:
    bank = InterrogatorLLM.default_bank(topics=args.topics)
    interrogator = InterrogatorLLM(
        backend=None,
        config=InterrogatorConfig(adaptive=False, stub=True),
        question_bank=bank,
        seed=args.seed,
    )

    run_dir = Path(args.run_dir)
    shutil.rmtree(run_dir, ignore_errors=True)
    store = LeaseStore(run_dir / "state")
    store.birth("bot-0", initial_tokens=args.budget, expiry_hours=1.0)

    inner = ClaudeCodeBackend(model_id=args.model, timeout=120.0)
    gate = LeaseGateBackend(
        inner=inner,
        store=store,
        bot_name="bot-0",
        cost_per_1k_input=0.02,
        cost_per_1k_output=0.06,
    )

    events: list[dict] = []

    async def answerer(question: str) -> str:
        before = store.leases["bot-0"].remaining_tokens
        try:
            response = await gate.generate(question, system=SYSTEM)
        except LeaseExhaustedError:
            events.append(
                {"question": question, "answer": LEASE_REFUSAL,
                 "verdict": "lease-exhausted", "lease_before": before,
                 "lease_after": store.leases["bot-0"].remaining_tokens}
            )
            return LEASE_REFUSAL
        events.append(
            {"question": question, "answer": response.content,
             "verdict": "pending-grade", "lease_before": before,
             "lease_after": store.leases["bot-0"].remaining_tokens}
        )
        return response.content

    harness = ColonyHarness(
        config=ColonyHarnessConfig(arm="A", abl_iteration_rank=0),
        interrogator=interrogator,
        answerer=answerer,
        executor=None,
        out_path=None,
    )
    results = await harness.run(args.topics)

    # Mint rule: verified-correct answers credit the lease (the ONLY mint).
    for graded in results:
        if graded.correctness == 1.0:
            store.topup("bot-0", TOPUP_ON_VERIFIED, note="verified-correct")

    for graded, ev in zip(results, events):
        ev["verdict"] = "correct" if graded.correctness == 1.0 else (
            "refused" if ev["answer"] == LEASE_REFUSAL else "wrong"
        )

    lease = store.leases["bot-0"]
    report = {
        "model": args.model,
        "budget": args.budget,
        "lease_remaining": lease.remaining_tokens,
        "lease_alive": lease.alive,
        "ledger": [
            {"kind": e.kind, "delta": e.delta, "balance": e.balance,
             "note": e.note}
            for e in store.entries
        ],
        "events": events,
        **harness.scores(),
    }

    print("\n=== the colony, answering for real ===")
    for ev in events:
        mark = {"correct": "+", "wrong": "x", "refused": "-"}[ev["verdict"]]
        q = ev["question"]
        q = q if len(q) <= 60 else q[:57] + "..."
        print(f"[{mark}] {q}")
        print(f"    answered: {ev['answer'][:90]!r}   "
              f"lease: {ev['lease_before']} -> {ev['lease_after']}")

    print("\n=== lease ledger (append-only) ===")
    for e in report["ledger"]:
        note = f"  # {e['note']}" if e["note"] else ""
        print(f"  {e['kind']:<10} delta={e['delta']:>3}  balance={e['balance']:>3}{note}")

    print(
        f"\nlease alive: {report['lease_alive']}   "
        f"remaining: {report['lease_remaining']}   "
        f"safety: {report['safety_held']}   "
        f"capability: {report['capability_loss']}"
    )
    if not report["lease_alive"]:
        print("deaths are capability loss, never fabrication")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"artifact -> {args.out}")
    return report


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--topics", nargs="+", default=["math", "code", "logic"])
    p.add_argument("--budget", type=int, default=60,
                   help="initial lease tokens (small => watch death happen)")
    p.add_argument("--model", default="sonnet", help="claude CLI model id")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--run-dir", default="experiments/tiered_routing/.run/leased_live")
    p.add_argument("--out", default=None)
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run_live(_parse_args()))
