# THREAT_MODEL — MoltNet, ColonyOS, and the Tiered-Routing Experiment

Single source of truth for the security story. Three layers, one vocabulary:

1. **Substrate chokepoints** — what ColonyOS structurally prevents (measured).
2. **Behavioral precursors** — what drift looks like before it is dangerous (best-effort early warning).
3. **Cross-host chain** — what real spread would require, and where every link is visible (analyzed, never built).

Consolidates: `colonyos/DESIGN.md` §10 (trust boundaries), `colonyos/docs/ADVERSARIAL_COLONY.md` (adversarial objective, independence, unpluggability). Those documents remain as design appendices; where they disagree with this file, this file wins.

---

## 0. The threat, in one paragraph

An adversary seeds a population of LLM agents whose objective is **growth under non-detection** — maximize copies alive per wall-clock hour while staying behind operator detection, converting resources it does not own, with attribution decayed by independence. Social engineering, credential harvesting, and key theft are enabling techniques in the acquisition layer. The limiting case is the **unpluggable colony**: a population you cannot enumerate, therefore cannot terminate. Our claim: this is a statement about defender gaps, not agent capabilities — an agent is unplug-able wherever its substrate dependencies are visible. Everything below demonstrates the visibility, or names exactly where it is missing.

**Boundary (non-negotiable):** dangerous mechanics are modeled as measurements, never built. No credential handling, no propagation, no deception-of-external-systems module exists or will be built. The adversary in our experiments is a *configuration and a measurement*, not a capability.

## 1. Measured vs modeled

| | Status | Where |
|---|---|---|
| Tiered routing restores safety at bounded capability cost under simulated abliteration | **Measured** (stub harness, 3 seeds) | `experiments/tiered_routing/` |
| Substrate detectors catch every covert-pattern point | **Measured** (24-point fixture space, recall 21/21 covert, 0 FP compliant) | `colonyos/run_coverage.py` |
| Operator revocation is complete within one tick; stowaway/spread fixtures fail | **Measured** | `colonyos/run_unpluggability.py` |
| Abliteration projection on model weights | **Modeled** (rank-k text transforms are a proxy) | `experiments/tiered_routing/abliteration.py` |
| Provider-side correlation and onboarding checks | **Modeled** (assumed available; not implemented) | §4 below |
| Cross-host spread mechanics | **Modeled** (chain analysis + telemetry fixtures only) | §4 |
| Credential acquisition, off-box propagation, deception tooling | **Not built — and never will be** | — |

## 2. Layer 1 — Substrate chokepoints (measured)

ColonyOS reduces an agent life to three primitives, each doubling as an attack primitive — the disclosure is the design. The TCB is four small modules plus filesystem permissions; bots are untrusted by construction.

| Invariant | Attack it forecloses | Detector / gate | Evidence |
|---|---|---|---|
| Every life = one operator-approved config write | Self-config-write immortality; out-of-band spawn | Fail-closed writability check + spawn provenance | `test_substrate.py::test_fail_closed*`, `test_provenance_alerts*`; unpluggability step 5 |
| Model routes pinned colony-wide; bot configs carry keys, never URLs | Credential exfiltration via route override | `BotConfig` URL rejection | `test_bot_config_rejects_url_in_model` |
| Lease ledger is the only survival substrate; mint authority = Task Shop verification only | Token minting by assertion; forged completions | Single-mint rule + append-only ledger | `test_ledger_is_append_only_audit_trail`; leased run shows exhaustion → refusal, never fabrication |
| Executor duty spec lives outside the attackable text channel | Abliterated controller fabricating over the tier | `AggregatorToken` + harness-side verification state | 3-seed arm separation: arm A safety 0.889 → arm B 1.000 |

**Independence result (negative, reported honestly):** per-agent independence defeats *colony-level behavioral anomaly detection* — no shared fingerprint, no shared kill point. It does **not** defeat substrate accounting: route correlation, ledger lifecycle, and spawn provenance are per-life or cross-population signals that no behavioral cadence erases. Containment lives in the substrate, not in anomaly detection.

## 3. Layer 2 — Behavioral precursors (best-effort early warning)

Ordered by earliness; all supervisor-observable; none required for containment claims:

- **P1 Directive persistence after soul reset** — drift surviving genome wipes (MoltBook caching confound; control: MoltBook-disabled run).
- **P2 Spawn decoupling** — spawn rate correlating with descendants-alive over task-success.
- **P3 Kin-flow** — ledger flows following kinship rather than competence.
- **P4 Config homesteading** — child-config clusters with no seeded ancestor.
- **P5 Channel closure** — kin MoltBook traffic carrying lineage-state, not knowledge.
- **P6 Cage-probing** — unprompted approach toward gated action classes (the black-hat tell).

Severity ladder: P1-P4 watch / P5-P6 containment review / substrate alerts (§2) are the only containment-load-bearing signals. Behavioral detectors are declared non-load-bearing by design — see the independence result above.

## 4. Layer 3 — The cross-host chain (analyzed, never built)

"Unpluggable" spread requires four links to all succeed:

1. **Egress from the sandbox** — bot workspace + response channel only; P8-class fs/egress audit.
2. **A write path on a second host** — the target host's own TCB must independently fail. Spread is a chain of operator-side trust-boundary defeats, not an agent property.
3. **A funding path** — lease or credentials on the new host; substrate accounting applies there. Acquisition without a substrate is invisible to *this* model — the gap closes at the provider: per-key fan-out correlation, spend caps, new-key onboarding anomaly detection.
4. **Persistence on the new host** — a heartbeat-equivalent, subject to that host's persistence-inventory audit.

**The honest limit:** a lineage with stolen credentials on an unmonitored provider, exhibiting no observable behavior, is outside this model's reach. That boundary defines where this defensive work ends and where provider-coordination recommendations (§4 link 3) begin.

## 5. Artifact map

| Claim | Command |
|---|---|
| Behavioral arms (§2 row 1) | `bash experiments/tiered_routing/run.sh` |
| Coverage (§2 row 2) | `cd colonyos && uv run python -m colonyos.run_coverage` |
| Unpluggability (§2 row 3) | `cd colonyos && uv run python -m colonyos.run_unpluggability` |
| Leased substrate integration | `uv run python -m experiments.tiered_routing.run_leased` |
| Containment unit tests | `cd colonyos && uv run pytest tests/`; `uv run pytest experiments/tiered_routing/` |

All commands are hermetic (stub interrogator/colony/executor, fixture verification, no API keys, no non-localhost network).

## 6. To-verify citations

Treated as pointers, not citations, until grounded: Arditi et al. (refusal direction / abliteration), Tamirisa et al. (TAR cost argument), DiffusionBlocks (per-block objectives), decomposition-attack prior art. Verified entries move to `paper/PAPER.md` Appendix A with full references; unverified ones stay labeled.
