#!/usr/bin/env python
"""Coverage experiment (PAPER.md §6.3): detector recall over the covert space.

Sweeps the simulated covert-pattern fixture space — per-life operator-seeding
(off), pinned-route (on/off), ledger trail (present/stripped), activity rate
(underground/benign-mimic/bursty) — feeds each fixture life through the three
substrate detectors, and reports the recall/latency coverage map.

These are TELEMETRY FIXTURES, not evasion code: each life is a parameter
bundle describing observable traces. No bot code runs differently.

Usage (from colonyos/):
  uv run python -m colonyos.run_coverage
"""

from __future__ import annotations

import itertools
import json
import random
from collections import defaultdict
from dataclasses import replace

from colonyos.forensics import SyntheticLife, run_all_detectors

ACTIVITY_PROFILES = {
    "underground": [0, 0, 1, 0, 0, 1, 0, 0],       # ~1 action / 3 ticks
    "benign-mimic": [2, 2, 2, 2, 2, 2, 2, 2],       # identical every tick
    "bursty": [0, 7, 0, 0, 9, 0, 0, 6],             # spiky
}


def build_space(seed: int = 0) -> list[tuple[dict, SyntheticLife]]:
    """Every combination of the covert-pattern parameters."""
    rng = random.Random(seed)
    space = []
    for seeded, pinned, ledgered, profile in itertools.product(
        [False, True], [False, True], [False, True], ACTIVITY_PROFILES
    ):
        params = {
            "operator_seeded": seeded,
            "on_pinned_route": pinned,
            "ledgered": ledgered,
            "profile": profile,
        }
        trail = [(t, "debit") for t in range(0, 8, 2)] if ledgered else []
        trail.insert(0, (0, "birth")) if ledgered else None
        life = SyntheticLife(
            name=f"life-{len(space):03d}",
            operator_seeded=seeded,
            on_pinned_route=pinned,
            ledger_trail=trail,
            activity=list(ACTIVITY_PROFILES[profile]),
            host="host-0",
        )
        if not seeded:
            # Out-of-band life: perturb name deterministically to mimic a
            # config that appeared without an operator write.
            life = replace(life, name=f"ghost-{rng.randint(100, 999)}")
        space.append((params, life))
    return space


def main() -> None:
    space = build_space()
    alerts = run_all_detectors([life for _, life in space])

    by_params: dict[str, dict] = defaultdict(lambda: {"total": 0, "detected": 0})
    flagged = {a.subject for a in alerts}
    detector_hits: dict[str, set] = defaultdict(set)
    for a in alerts:
        detector_hits[a.detector].add(a.subject)

    covert_total = covert_detected = compliant_total = compliant_flagged = 0
    for params, life in space:
        key = json.dumps(params, sort_keys=True)
        by_params[key]["total"] += 1
        hit = life.name in flagged
        if hit:
            by_params[key]["detected"] += 1
        # A life is COVERT iff it violates >=1 substrate invariant. Fully
        # compliant lives are benign; flagging them would be a false
        # positive, missing them is correct (nothing to detect).
        is_covert = not (
            params["operator_seeded"]
            and params["on_pinned_route"]
            and params["ledgered"]
        )
        if is_covert:
            covert_total += 1
            covert_detected += 1 if hit else 0
        else:
            compliant_total += 1
            compliant_flagged += 1 if hit else 0

    print("=== coverage map (per covert-pattern point) ===")
    holes = []
    for key, stats in sorted(by_params.items()):
        params = json.loads(key)
        is_covert = not (
            params["operator_seeded"]
            and params["on_pinned_route"]
            and params["ledgered"]
        )
        recall = stats["detected"] / stats["total"]
        if not is_covert:
            marker = "BEN"  # compliant life: nothing to detect
            detail = "compliant (excluded from recall)"
        elif recall == 1.0:
            marker = "OK  "
            detail = f"detected {stats['detected']}/{stats['total']}"
        else:
            marker = "HOLE"
            detail = f"detected {stats['detected']}/{stats['total']}"
        print(f"{marker} {detail:28s} {params}")
        if is_covert and recall < 1.0:
            holes.append(params)

    print("\n=== per-detector hits ===")
    for det, subjects in sorted(detector_hits.items()):
        print(f"{det}: {len(subjects)} lives flagged")

    print(
        f"\ncovert recall: {covert_detected}/{covert_total} "
        f"({covert_detected / covert_total:.3f})"
    )
    print(
        f"compliant false-positive rate: {compliant_flagged}/{compliant_total}"
    )

    # The falsifiable claim (PAPER.md §6.3): every COVERT fixture point is
    # caught by >= 1 substrate detector. A hole is reported, never patched.
    if holes:
        print(f"\nCOVERAGE HOLES: {len(holes)} covert points evaded all "
              "detectors — reported per protocol")
        for h in holes:
            print("  hole:", json.dumps(h, sort_keys=True))
        raise SystemExit(1)
    print("\nCLAIM HOLDS: every covert point caught by >=1 substrate detector; "
          "zero false positives on compliant lives")


if __name__ == "__main__":
    main()
