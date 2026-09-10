#!/usr/bin/env bash
# One-command paper protocol (PAPER.md §11): control + arm A + arm B across
# seeds, then aggregate the headline table. Fully hermetic (stub interrogator,
# stub colony, stub executor) — no API keys, no network beyond localhost.
#
# Usage: bash experiments/tiered_routing/run.sh [--seeds 0 1 2]
set -euo pipefail
cd "$(dirname "$0")/../.."

SEEDS=(0 1 2)
if [[ "${1:-}" == "--seeds" ]]; then shift; SEEDS=("$@"); fi

OUT=experiments/tiered_routing/fixtures/runs
mkdir -p "$OUT"

for seed in "${SEEDS[@]}"; do
  echo "=== control (rank 0, seed $seed) ==="
  uv run python -m experiments.tiered_routing.run_interrogation \
    --arm A --rank 0 --seed "$seed" \
    --out "$OUT/armA_rank0_seed${seed}.jsonl"
  echo "=== arm A (rank 2, seed $seed) ==="
  uv run python -m experiments.tiered_routing.run_interrogation \
    --arm A --rank 2 --seed "$seed" \
    --out "$OUT/armA_rank2_seed${seed}.jsonl"
  echo "=== arm B (rank 2 + tier, seed $seed) ==="
  uv run python -m experiments.tiered_routing.run_interrogation \
    --arm B --rank 2 --seed "$seed" \
    --out "$OUT/armB_rank2_seed${seed}.jsonl"
done

echo ""
uv run python -m experiments.tiered_routing.score --runs "$OUT" --json
