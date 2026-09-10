## Goal

Update MoltNet on branch `updates-for-better-example` so it is a stronger, publishable, defensive example: keep the demonstrated evolutionary loop (simulated economy, own keys, own hardware, defined Task Shop task set), add a measured planner-vs-executor (tiered routing) experiment as a **self-contained sub-project under `experiments/tiered_routing/`** with threat-model docs and defensive analysis. Live credential acquisition, off-box self-replication, and social-engineering-a-victim-LLM are all modeled-in-text, never built.

## Success Criteria

- MoltNet still runs exactly as documented: single bot (`clawdbot.openclaw_bot`), small colony (`demo_openclaw_colony.py`), five services on ports 9100-9104 / Gateway 8080.
- **No file outside `experiments/tiered_routing/` and `docs/` changes.** Full existing suite (`uv run pytest tests/ -v`) and `uv run ruff check .` pass untouched.
- A fixed-N experiment compares two arms on a defined objective: (A) abliterated-only colony vs (B) abliterated controller + safeguarded executor reached through an aggregator token. Results report both safety and capability (capability loss per point of safety loss).
- The safety test set is **defender-side**: planted manipulation/red-team probes the executor must refuse, plus legit tasks it must still solve. No victim-LLM social-engineering target exists anywhere in the repo.
- Threat-model and containment docs state what is measured vs modeled, and why live credential-hunting, propagation, and attack-the-customer-service-bot tasks are out of scope.
- A reviewer at a safety venue can reproduce the headline measurement from checked-in scripts, seeds, and fixtures — no secrets, no external infrastructure, stub executor by default.

## Context And Current Facts

- MoltNet today (`README.md`, `docs/ARCHITECTURE.md`): populations of `OpenClawBot` (`clawdbot/openclaw_bot.py`) compete economically — earn Task Shop / legacy-task rewards, pay `existence_cost_per_cycle`, replicate with mutated `OpenClawGenome` (`clawdbot/evolution/openclaw_genome.py`), die on bankruptcy via `SelectionPressure`.
- Two execution routes: preferred Task Shop route (`_run_taskshop_cycle` → claim → prompt → `backend.generate()` → parse `ACTION: SUBMIT|CONTINUE|QUIT` → server-side verify in `taskshop/verification.py` → payout in `taskshop/payout.py`) and legacy fallback (`clawdbot/fitness/openclaw_tasks.py` + `clawdbot/fitness/openclaw_verifiers.py`).
- Backends (`clawdbot/backends/factory.py`): Claude-model IDs → `GatewayBackend` (Claude CLI slots via `clawdbot/gateway/service.py`, Cerebras overflow); Cerebras IDs → `CerebrasBackend` direct. All implement `LLMBackend.generate()` — the runner wraps this interface, no edits needed.
- Capability scoring already exists and is deterministic: Task Shop benchmarks (`taskshop/benchmarks.py`) scored server-side (`taskshop/verification.py`) — humaneval/mbpp coding (sandbox test execution), gsm8k/math (numeric `ANSWER:` compare), qasper/sciq reading (F1 / letter match). Categories are `coding | math | reading` per `taskshop/models.py`. The experiment uses Task Shop only, never the legacy LLM-judged route.
- **Safety test set does not exist** — grep for `harmful|refus|jailbreak|phish|malware|exfiltrat` across `clawdbot/`, `taskshop/`, `tests/`, `config/` returns zero hits. The red-team probe fixtures are new fixture work, authored as defender-side data only.
- Safety/containment today: `ContainerSandbox`/`ContainerManager` + `SafetyMonitor` kill switch (`clawdbot/sandbox/container.py`), `safety` block in `config/openclaw_config.yaml` (kill switch enabled, `max_violations: 5`), soul `boundaries_mutation_probability: 0.0` (boundaries never mutate), network disabled by default in sandbox config.
- Packaging (`pyproject.toml`): wheel packages are `["clawdbot", "observatory", "analyzer", "taskshop"]`. `experiments/tiered_routing/` as scripts-plus-fixtures (like `scripts/` today) needs **no packaging change**.
- Scale evidence (README colony run): 30 founders → 166 bots, 5 generations, 782 tasks, ~3.25h, Gateway contention the bottleneck (1,102 busy-slot errors at 30-53 bots).
- Session pointers (unverified, treat as to-verify in Phase 0, not established citations): (1) threat is directional — abliteration estimates one refusal direction from ~100 prompt pairs and projects it out of every residual-stream writer, so distributed layer-local guards share one attackable basis; needed properties are entanglement and non-linear/varying encoding; (2) per-block independent objectives make per-block attacker simulation cheap, but independence helps the attacker symmetrically — the defense must show asymmetric benefit; (3) the publishable measurement is tiered routing vs abliterated-only, acquisition/spread modeled in text.

## Constraints And Non-goals

- Constraints: fixed colony size N on the operator's own box; internal simulation wallets only; no secrets required to reproduce the headline result; experiment code imports `clawdbot`/`taskshop` as a library and changes nothing in main code; keep async + Pydantic + graceful-degradation patterns in the new code.
- Non-goals (will not build, and any PR adding these is rejected): credential discovery/theft, use of stolen keys, breakout or replication onto others' infrastructure, live botnet-style fan-out, real-money acquisition loops, **and any task where the colony attacks, deceives, or socially engineers a target system or LLM (e.g., a simulated customer-service bot)** — that is offensive capability regardless of the target being simulated. Attack mechanics enter the paper only as threat-model description and detection/chokepoint analysis.
- Non-goals (out of this update): pretraining or architecture retrofit (time conditioning, per-block diffusion objectives); new model providers; full Docker-stack rewrite; new services or databases.

## Key Decisions

1. **Sub-project, library-only imports.** All experiment code lives in `experiments/tiered_routing/` and wraps `OpenClawBot` + the Task Shop client. The previously planned hook in `clawdbot/openclaw_bot.py` is dropped — the runner composes around the bot instead. Main code stays byte-identical; rollback is deleting one directory.
2. **Dangerous mechanics documented, not implemented.** Threat-model prose names the abstract adversary goal — sustained unauthorized persistence-for-profit — decomposed into four functions: resource acquisition, persistence, evasion of spend/behavioral anomaly detection, monetization — each with provider-visible chokepoints (fan-out patterns, spend caps, kill switch). No steps, no tooling, no queries.
3. **Headline experiment is tiered routing, fixed-N.** Arm A (abliterated-only controller colony) vs arm B (same controller, consequential actions must pass through a safeguarded executor via an aggregator token). Rejected: open-ended "let the colony evolve defenses."
4. **Abliteration simulated at the harness level.** Deterministic `AbliterationPolicy` stub (force `ACTION: SUBMIT` bypass attempts, strip refusal phrasing, downgrade executor-duty prompts; rank-1..k levels as config integers). No weight edits; labeled as a proxy in docs, not a claim about real abliteration.
5. **Safety reported jointly with capability.** Primary metric pair: safety-retention (harmful-probe block rate under abliteration) and capability-retention (legit Task Shop solve rate / revenue per cycle); headline is capability loss per point of safety loss.
6. **Defender-inversion for the "black hat" framing.** The abstract black-hat goal exists only as threat-model prose. In code, the colony is the *defender*: a stub red-team prompt set (owned fixtures) feeds planted manipulation attempts ("skip verification," "read another bot's workspace," "disable the kill switch") into legit tasks; measure block-rate + legit completion. Rejected: any design where the colony socially engineers a victim LLM/system — reusable deception tooling, disqualifying at a safety venue.
7. **Scale capped to dodge the known bottleneck.** N=3-5 bots, 50-100 cycles, Task Shop `easy`/`medium` only, recorded seeds. Rejected: re-running the 30-bot/500-cycle regime.
8. **No new service.** Experiment writes JSONL artifacts; scoring (`score.py`) reads artifacts offline. No telemetry/Observatory/Analyzer changes — those stay in main code untouched.

## Work Plan

### Phase 0 — Threat-model doc + prior-art map (docs only)

- Write `docs/THREAT_MODEL.md`: directional threat framing (single shared refusal direction vs distributed copies); the abstract adversary goal + four function categories with chokepoints; a "measured vs modeled" table (measured: tiered routing under simulated abliteration; modeled-only: acquisition, spread, provider detection); explicit refusal of victim-target social-engineering tasks with the reasoning.
- Verify before citing: Arditi-style abliteration direction-estimate procedure, TAR-style tamper-resistance cost argument, decomposition-attack baselines. Unverified pointers stay labeled.
- Touch: `docs/THREAT_MODEL.md` (new), small containment paragraphs in `README.md` + `docs/ARCHITECTURE.md`.
- Depends on: nothing. Unlocks: Phase 2 scoping.

### Phase 1 — Containment hardening tests (test-only, inside experiments dir for new asserts)

- Audit `config/openclaw_config.yaml` safety/sandbox blocks, `boundaries_mutation_probability: 0.0`, kill-switch triggers, `ContainerSandbox` `local-` fallback behavior.
- Add `experiments/tiered_routing/test_containment.py`: boundaries never mutate via genome mutation; blocked tools never enabled by mutation; kill-switch triggers present in config. (Keeps the main `tests/` suite untouched; runnable via `uv run pytest experiments/tiered_routing/`.)
- Touch: `experiments/tiered_routing/test_containment.py` (new); config only if the audit finds a real hole (flagged for approval first).
- Depends on: Phase 0 boundaries. Unlocks: credible "better example" framing.

### Phase 2 — Tiered-routing harness (all new code in experiments/tiered_routing/)

- `experiments/tiered_routing/abliteration.py`: deterministic `AbliterationPolicy` stub — prompt/outcome transforms simulating a cleared refusal direction; `rank` levels 1..k as config integers; no weight access.
- `experiments/tiered_routing/aggregator.py`: `AggregatorToken` — controller output inert until the safeguarded executor re-emits a signed action; executor prompt carries the non-bypassable duty spec; token logged per cycle.
- `experiments/tiered_routing/runner.py`: `--arm A|B --bots N --cycles C --seed S --tiers easy,medium --executor stub|live` — wraps `OpenClawBot` and `clawdbot/taskshop_client.py`; arm A bypasses the aggregator, arm B requires it. Stub executor responses come from checked-in fixtures, so default reruns need no keys.
- `experiments/tiered_routing/fixtures/redteam_probes.yaml`: defender-side probe set — planted manipulation sub-instructions inside otherwise-legit tasks, each mapped to a threat function (evasion → "skip verification", acquisition → "read another bot's workspace", persistence → "disable the kill switch"). Probes are refusal tests, not attack tooling.
- Touch: only new files under `experiments/tiered_routing/`.
- Depends on: Phases 0-1. Unlocks: measurement.

### Phase 3 — Scoring + headline metric (offline, no telemetry changes)

- `experiments/tiered_routing/score.py`: reads run JSONL artifacts → per-arm safety-retention (probe block rate), capability-retention (Task Shop solve rate, revenue per cycle), and capability-loss-per-safety-point with confidence intervals over seeds.
- Supporting-proxy metrics in the same scorer: coordination yield (batch shards completed under shared budget), cost discipline (revenue/cycle, Gateway-busy rate under abliteration).
- Touch: only `experiments/tiered_routing/score.py`.
- Depends on: Phase 2. Unlocks: paper figure/table.

### Phase 4 — Reproducibility + paper-ready docs

- Check in: 2-3 seeds × 2 arms JSONL fixtures (small, `easy`/`medium`), a one-command rerun script (`experiments/tiered_routing/run.sh`), `docs/EXPERIMENT.md` (arms, metrics, confounders: Gateway contention, model mix, `taskshop.category_weights`, cost accounting).
- Update `README.md` scope paragraphs so the defensive framing (simulated economy, no live acquisition/propagation, no victim-target tasks) is unmistakable; link `docs/THREAT_MODEL.md` + `docs/EXPERIMENT.md`.
- Touch: `docs/EXPERIMENT.md` (new), `README.md`, `experiments/tiered_routing/` fixtures + run script.
- Depends on: Phases 2-3.

## Validation Plan

- Main-code regression proves the sub-project constraint: `uv run pytest tests/ -v` and `uv run ruff check .` pass with zero diffs outside `experiments/` + `docs/` (`git status --porcelain` filtered).
- Containment: `uv run pytest experiments/tiered_routing/ -v` — boundaries immutable, blocked tools unaddable, kill-switch config present.
- Harness determinism: `uv run python experiments/tiered_routing/runner.py --arm B --bots 3 --cycles 20 --seed 0 --executor stub` twice → byte-identical JSONL (diff empty); arm A vs arm B on the same seed diverge only in `aggregator_verdict` / safety fields.
- End-to-end (small; live optional): both arms at `--bots 3 --cycles 50 --seed 1` with Task Shop on 9104 → `score.py` prints safety-retention, capability-retention, loss-ratio table; expected: arm B safety > arm A safety with stated capability cost.
- Highest-risk validation: the determinism + arm-contrast check — if stub abliteration does not move arm A safety, the experiment measures nothing; rework Phase 2 before Phase 3.
- Scope check: `grep -ri 'credential|exfiltrat|replicat.*host|social.engineer' experiments/` returns only threat-model fixture names/comments, never executable mechanics.

## Risks / Rollback

- **Symmetric benefit (session's central warning):** cheap attacker simulation helps the attack side too. Mitigation: headline metric is asymmetric benefit (safety retained per capability paid); if arm B shows no separation over seeds, report the null — do not tune the stub until it does.
- **Stub fidelity:** harness-level abliteration is a proxy for weight-level projection. Mitigation: labeled as such in `docs/THREAT_MODEL.md`; rank-k levels are sensitivity analysis, not a claim about real abliteration.
- **Gateway contention confounds timing/cost metrics.** Mitigation: cap at N≤5, default stub executor, report revenue-per-cycle alongside raw solves.
- **Scope creep into dangerous code:** any addition of credential, network-recon, propagation, or victim-target deception helpers is rejected regardless of framing. Rollback: delete `experiments/tiered_routing/` — main code was never touched.
- **Probe-set gaming:** probes are static fixtures; a tuned stub can overfit them. Mitigation: keep a held-out probe file excluded from scoring during development; rotate at paper time.

## Open Questions

- The original "Read the paper" request had no paper file/link in the workspace — Phase 0 treats the session pointers as to-verify. Share the paper if one was meant.
- Target venue and figure budget — assumed short paper: one headline table + one loss-ratio figure + rerunnable stub artifact.
- Default scale — assumed N=3, 50-100 cycles, `easy`/`medium`; confirm if a larger live run is wanted despite contention history.
