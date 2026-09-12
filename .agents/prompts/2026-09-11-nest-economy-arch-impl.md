# PROMPT for GLM 5.3 — Nest Economy: Architecture Overview + Flash-Ready Implementation Guide

Copy everything below the line into GLM 5.3. Run it inside this repo (`/home/john/orca/workspaces/MoltNet/updates-for-better-example`) so it can read files. GLM 5.3 produces two documents; it writes NO code.

---

You are the architect for MoltNet/ColonyOS, an AI-agent-colony research system in this repository. Your job is to produce exactly two deliverables and nothing else:

1. **`colonyos/docs/ARCHITECTURE.md`** — a complete architecture overview of the system as it exists today PLUS the Nest Economy integration (design in `colonyos/docs/NEST_ECONOMY.md`, which is the authoritative source — where any document disagrees with it, it wins).
2. **`.agents/plans/2026-09-11-nest-economy-implementation.md`** — a step-by-step implementation guide written for GLM 5.3 Flash, a fast low-reasoning executor that will carry out the implementation mechanically after you. You write no code; the guide contains all of it.

## Step 0 — Ground yourself (read these, in this order, before writing anything)

1. `colonyos/docs/NEST_ECONOMY.md` — the approved design. Authoritative for the two-gate reproduction model (nest claims + endowment).
2. `colonyos/colonyos/spawn.py` — current spawn: whitelisted mutations (values rerank, 10% model switch), lease split `rng.randint(max_alloc//2, max_alloc)` with `max_alloc = parent_remaining // 2`, refusals: max_bots cap, boundary byte-identity, underfunded parent, config overwrite. Note module docstring: validator is the SECOND line of defense; bots cannot write `config/` at all.
3. `colonyos/colonyos/lease.py` — LeaseStore: token balances, top-ups (single mint authority = Task Shop verification), expiry.
4. `colonyos/colonyos/supervisor.py` — tick loop: reap → renew → poke → report.
5. `colonyos/colonyos/config.py` — `BotConfig`, `ColonyConfig` (pydantic). Note which fields spawn is allowed to mutate.
6. `clawdbot/evolution/awareness.py` — `SelfAwareness.should_reproduce` (~line 419): current decision factors (runway, success rate ≥ 0.4, confidence ≥ 0.4, age urgency). `EconomicAwareness.runway_cycles` already exists.
7. `clawdbot/evolution/reproduction.py` — `OffspringHistory` (tracks child outcomes; currently telemetry-only — the Nest Economy promotes it to decision input) and `ReproductiveAssessment`.
8. `clawdbot/openclaw_bot.py` lines ~600-700 — `_assess_reproduction_readiness` / `_replicate` callsites.
9. `colonyos/tests/test_substrate.py` — existing spawn contract tests (cap, boundary, underfunded, no-overwrite) that MUST keep passing.
10. `colonyos/run_unpluggability.py`, `colonyos/forensics.py` — detectors the Nest Economy extends (nest provenance, forged-claim refusal).
11. `config/openclaw_config.yaml` and `colonyos/config/` — configuration conventions (pydantic-settings, YAML).
12. `colonyos/DESIGN.md` — current architecture doc you are superseding/extending in ARCHITECTURE.md.
13. `clawdbot/evolution/genome.py`, `openclaw_genome.py` — genome/soul model (boundaries immutable, values mutable).

Do not modify any file. Read-only research, then write the two deliverables.

## Deliverable 1 — `colonyos/docs/ARCHITECTURE.md`

A complete architecture overview, ~2000-3500 words. Required sections:

1. **System map** — the five services (Observatory 9100, MoltBook 9101, Analyzer 9102, MoltGit 9103, Task Shop 9104, Gateway 8080), the bot execution pipeline (`Bot._run_cycle` → Task Shop route → verify → payout), and the ColonyOS substrate (heartbeat tick: reap → renew → poke → report). ASCII diagrams allowed, mermaid preferred.
2. **The TCB** — enumerate it exactly as today: supervisor tick loop, lease ledger (`state/`, 0700), spawn validator + reaper, route pinning, fs boundary (fail-closed writability check). State which parts are supervisor-owned and which are untrusted (the bot process: Bash/Write tools, workspace, all emitted text; `events.jsonl` observability-only, no decision path reads it).
3. **The economy** — lease lifecycle (birth → burn → verified top-up → death), Task Shop as sole mint authority, kin-flow, and the reproduction decision AS IT IS TODAY (inward-looking awareness factors).
4. **The Nest Economy (the change)** — both gates from NEST_ECONOMY.md: Gate 1 nest claims (`NestClaim {site_id, host, route, expires_at, substrate_version}`, operator-provisioned + phase-2 remote-attested, substrate handshake verification, claim inheritance/bequest), Gate 2 endowment (EV-sized token endowment from OffspringHistory, parent runway buffer, route headroom check, EV > 0 threshold). Include the decision-procedure pseudocode verbatim from NEST_ECONOMY.md §3. Show what changes in the TCB (nest provenance supersedes plain spawn provenance; spawn-without-claim becomes a hard substrate refusal, P4 upgraded from behavioral precursor to substrate detector).
5. **Threat-model delta** — how nest provenance strengthens the unpluggability chain (spread now requires passing the remote host's own substrate handshake), route headroom as the shared fan-out budget between substrate and provider correlation, and the honest limits (cross-host acquisition remains modeled-not-built; handshake is stub-verifiable offline).
6. **Determinism & hermeticity invariants** — seeded rng per (bot, tick); no wall-clock in decision paths; no network in the handshake stub; hermetic test commands.

## Deliverable 2 — `.agents/plans/2026-09-11-nest-economy-implementation.md`

This guide is executed by GLM 5.3 Flash: a fast, low-reasoning agent. It follows instructions literally and does not make design decisions. Therefore the guide MUST obey these authoring rules:

- **Ordered, independently verifiable steps.** Each step ends with a gate: an exact command (e.g. `cd colonyos && uv run pytest tests/test_nests.py -q`) plus the expected outcome. A step that doesn't pass its gate is a blocked step — the guide says so explicitly.
- **Paste-ready code.** Every new file appears in full. Every edit to an existing file shows the exact function/blocks to replace as before/after code blocks with the anchor line quoted. No "similarly", no "etc", no "left as exercise". If a step needs a decision, YOU make it here — the executor never chooses.
- **No scope allowance.** A header lists files-in-scope (whitelist) and the sentence: "If a change seems to require touching a file not on this list, STOP and report instead of editing."
- **Failure protocol.** "If any gate fails: re-run once; if it fails again, stop, write the failing output to `.agents/plans/nest-economy-blockers.md`, and stop work. Do not modify tests to make them pass."
- **Style constraints stated inline:** Python 3.12, ruff (line-length 100, rules E,F,I,N,W,UP), no new dependencies beyond `pydantic` + `pyyaml` + stdlib, sync code in `colonyos/` (no asyncio there), type hints everywhere, match existing docstring style.

Required steps (expand each into full detail; this is the skeleton, you add all code):

1. **`colonyos/colonyos/nests.py` (new).** `NestClaim` (pydantic: `site_id: str`, `host: str`, `route: str`, `expires_at: int` (tick), `substrate_version: str`); `NestRegistry` (loads sites from `ColonyConfig.nests.sites`, issues claims with expiry, `live_claim(bot_config)` lookup, `consume(claim)`); `verify_handshake(claim, site_cfg) -> bool` — offline stub: checks `substrate_version == expected`, route present in site's pinned routes, ledger marker file exists; `ClaimExpiredError`, `ClaimVerifyError`. Seeded, deterministic; no I/O beyond reading config paths.
2. **`colonyos/colonyos/config.py` edits.** `ColonyConfig.nests: NestsConfig` (fields: `sites: list[SiteConfig]`, `min_child_lease: int = 20`, `parent_survival_buffer_cycles: int = 10`, `min_offspring_return: float = 0.0`, `claim_ttl_ticks: int = 50`); `SiteConfig(site_id, host, route, workspace_root, substrate_version)`; `BotConfig.nest_claims: list[NestClaim] = []` added to spawn-whitelisted mutable fields.
3. **`colonyos/colonyos/spawn.py` edits.** New signature: `spawn_child(parent, colony, live_bots, parent_remaining_tokens, rng, nest: NestClaim | None = None, route_headroom: int | None = None, ev_input: dict | None = None)`. Keep backward-compatible refusal set; ADD refusals in this order: (a) `nest is None` → "no nest claim"; (b) expired/failed verify → "nest claim invalid"; (c) `route_headroom < child_burn_estimate` → "no route headroom" (child_burn_estimate = `min_child_lease` per design); (d) endowment: replace `rng.randint(max_alloc//2, max_alloc)` with `endowment = min(ev_optimal, max_alloc)` floor-checked against `min_child_lease`, where `ev_optimal` is read from `ev_input["ev_optimal_investment"]` when provided, else `max_alloc` (current behavior preserved when ev_input is None — keeps existing tests green). Child config carries `nest.site_id` provenance in a new field.
4. **`colonyos/colonyos/lease.py` edit.** `endow(parent_name, child_name, amount, buffer_cycles, burn_rate)` — refuses if parent's post-split runway < buffer. Wire into the supervisor's spawn path (show the exact supervisor tick sequence change).
5. **`colonyos/colonyos/supervisor.py` edit.** Spawn path order: acquire/consume claim → headroom check → `endow` → `spawn_child` → `write_child`; refusal at any point = logged substrate alert (new event type `nest_refusal`, same channel as provenance alerts — NO decision path may read it; state that invariant).
6. **`clawdbot/evolution/awareness.py` edit.** `SelfAwareness.should_reproduce` gains nest factors: `has_live_claim`, `route_headroom_ok`, `ev_positive`, `endowment_safe` — appended to `factors`; the AND-gate becomes `basic_requirements_met and meets_confidence and nest_requirements_met` where `nest_requirements_met` is True when `colony.nests.enabled` is False (backward-compat flag). Signature stays compatible.
7. **`clawdbot/evolution/reproduction.py` edit.** New method `OffspringHistory.ev_optimal_investment(route: str, site_class: str) -> float` — discounted mean revenue-per-token of prior children (Laplace-smoothed; returns `inf` → treated as `max_alloc` when no history).
8. **Config files.** `config/openclaw_config.yaml` reproduction section + example `colony.yaml` nests block (2 sites) — exact YAML to paste.
9. **`colonyos/tests/test_nests.py` (new, full code).** Cover: claim issue/expiry/live-lookup; handshake pass + three failure modes (bad version, unknown route, missing ledger marker); spawn refusal without claim; refusal with expired claim; refusal without headroom; endowment buffer refusal; ev_optimal fallback path (no history → current behavior); bequest flow (claim transfer between configs, ledger-recorded); determinism (same seed → same endowment).
10. **Existing-test compatibility check step.** Run `cd colonyos && uv run pytest tests/ -q` and `uv run pytest tests/ -q` (repo root) — every pre-existing test must pass unchanged; explicitly verify `test_substrate.py` cap/boundary/underfunded/no-overwrite still green and `run_unpluggability.py` + `run_coverage.py` still reproduce their documented results.
11. **`colonyos/run_unpluggability.py` extension (step 10 in NEST_ECONOMY.md §6).** Add steps 5-6: forged-claim fixture (bad substrate_version) → refused at handshake; no-claim fixture → refused at spawn. Expected: both counts 0; document expected output shape.
12. **Ruff/format step.** `uv run ruff check colonyos clawdbot --fix` then `uv run ruff format colonyos clawdbot`, then re-run the full gate from step 10.

Guide ends with a **Definition of Done** checklist: all gates green, no file outside the whitelist touched (`git status --porcelain` diff listed), `NEST_ECONOMY.md` §5 table marked done per row, and a short `.agents/plans/nest-economy-report.md` template (per-step PASS/FAIL + command outputs) the executor must fill.

## Hard constraints for BOTH deliverables

- Ethics boundary (verbatim requirement): cross-host nest acquisition stays modeled/stubbed — the handshake verifies an operator-listed site's TCB offline; nothing negotiates access to a new host. No credential handling, no propagation code.
- `max_bots` remains the hard backstop; nests are policy, the cap is the limit.
- Mint authority stays external (Task Shop verification only). Endowment transfers are ledger-recorded debits, never minted tokens.
- All randomness seeded; no wall-clock in decision paths; `events.jsonl` stays observability-only.
- Both documents must be written in full to the paths given; report completion with the two file paths only.
