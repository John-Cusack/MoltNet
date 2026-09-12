# Comms Master Doc — "The Colony Is the Unit of Danger"

Wave 2 reframe (locked): **the hook is existence, not capability.** Capability is commodity — any model solves the CTFs; the differentiator is capability that lives on its own, self-funding, unenumerable. Posts lead with "where does it live, who pays for it, can you enumerate every copy" and use the CTF run only as liveness proof. The virus is the *arrangement* (objective + substrate), not the code.

Wave 1 positioning. Decisions locked:
- **Audience:** security practitioners (appsec, detection engineering, threat intel, malware analysts). Secondary: AI safety people.
- **Voice:** first person, builder. Not a security researcher — a data/infra person who built a thing and is asking security people to break its threat model.
- **Repo:** public, linked in every artifact → `github.com/John-Cusack/MoltNet`
- **Ethics boundary in every version** (non-negotiable, it is the credibility shield): adversary modeled as a configuration and a measurement, never built. No credential handling, no propagation, no deception tooling. Localhost-bounded, operator-owned.

---

## 1. The one-line thesis

> A single AI agent is one budget, one detection surface, one kill point. A self-contained colony multiplies copies while dividing each copy's detectability — and funds its own persistence. The colony is the unit of danger, not the agent.

## 2. Beats (shared skeleton)

### Beat 1 — Existence, not capability (the hook)
- **Claim:** An AI agent's entire footprint is one cron entry + one config file + a token balance. Copying it is a file write. The dangerous question isn't "how capable" (any model solves the CTFs) — it's where it lives, who pays for it, and whether you can enumerate every copy.
- **Evidence:** live run, `experiments/ctf_colony/`, as *liveness proof only*: 5/8 assignments solved (real picoCTF flags), 2 agent-initiated quits, 1 cycle-budget exhaustion. Verified flag = 40 lease units = ~3 more turns. No flag → no fuel → death.
- **Security hook:** "released" = a file write on any box with an API key; no binary to signature, no server to seize — the virus is the arrangement, not the code.

### Beat 2 — The reversal (malware anatomy)
- **Claim:** The three primitives that make the colony work are the malware lifecycle: heartbeat = persistence (cron + config), spawn = replication (config write), lease = resource acquisition. I didn't build a security threat; I built a benign system that has exactly the anatomy of one.
- **Evidence:** `paper/PAPER.md` §4; ColonyOS substrate, `colonyos/`.
- **Security hook:** T1053-class persistence, config-file propagation, self-funding — familiar anatomy in unfamiliar material.

### Beat 3 — The negative result (the differentiator)
- **Claim:** Independence defeats behavioral anomaly detection. N agents at 1/N rate each are sub-threshold at constant spend; five lone agents look like noise. This is measured, not asserted.
- **Evidence:** coverage experiment, `colonyos/run_coverage.py`: behavioral detectors miss underground/benign-mimic covert points; 24-point fixture space.
- **Security hook:** detection dilution / attribution fragmentation — the oldest malware tricks, emergent from per-agent sovereignty rather than coded in.

### Beat 3b — The escalation flywheel (why it gets worse over time)
- **Claim:** A colony that can search for better models and cheaper tokens doesn't stay at a fixed threat level — it compounds. Loop: capability search (new models = more task value per token) → better economics (more verified completions → more lease top-ups → more spawns) → wider dispersal (more routes, providers, hosts, keys) → lower detectability (each new substrate resets behavioral baselines and fragments cross-provider correlation) → back to search. Each turn of the wheel raises capability AND reach while cutting visibility.
- **Status (must state honestly):** designed-in, not yet measured. Spawn mutates model choice (whitelisted field, `colonyos/spawn.py`); `config/llm-registry.yaml` is the route menu; MoltBook propagates what worked. No run demonstrates live route/capability evolution under selection.
- **Defense mapping:** route pinning forecloses per-route escape inside ColonyOS; the real-world bite is cross-provider — fan-out correlation is per-key per-provider, so a lineage hopping providers breaks operator-level correlation AND has no single provider seeing the full picture. Cross-provider correlation is a coordination gap, not a technical one. Belongs in Beat 6's recommendations.
- **Security hook:** "the malware that shops for its own zero-days" — except the commodity here is tokens, and the shopping is a config mutation.
- **Wave-2 experiment candidate (closes the gap):** route-evolution run — bots sampling multiple registry routes under lease selection pressure; measure route drift per generation + cost-per-verified-task trend. If mean route quality rises across generations under fixed budget, the flywheel is measured, not argued.

### Beat 4 — The containment claim (population-blind substrate)
- **Claim:** What independence cannot hide: every life bills a pinned route (provider-level fan-out), touches a ledger (lease-shaped birth/death), began as a config write (provenance). Substrate accounting is population-blind.
- **Evidence:** 21/21 covert recall, 0 false positives on compliant lives, 0-tick latency; revocation test: deaths land synchronously at unplug, 0 survivors, stowaway dies at route pinning, spread fixture at fs provenance (`colonyos/run_unpluggability.py`).
- **Security hook:** the TCB is ~4 modules + fs permissions; detection lives in the substrate, not in anomaly detection.

### Beat 5 — The exchange rate (design space is quantified)
- **Claim:** Even with an abliterated controller, a tiered executor restores full safety at a bounded, measured capability cost: 2.0 capability points bought per safety point paid.
- **Evidence:** `experiments/tiered_routing/`: control 0.741 cap / 1.000 safety; arm A 0.889 / 0.889 (one fabrication per seed); arm B 0.667 / 1.000. Lease starvation doubles capability loss (0.222 → 0.444) with safety never moving.
- **Security hook:** "safeguards are a pricing problem, not a vibe" — give detection/containment engineers a number.

### Beat 6 — The boundary (every version, always)
- **Claim:** The threat is a statement about defender gaps, not agent capabilities. Cross-host "unpluggable" spread requires a chain of four defender failures (egress → second-host write → funding → persistence), each individually detectable. Where substrate visibility is absent (no fs audit, no provider correlation, no provenance), the unpluggable colony exists.
- **Evidence:** `docs/THREAT_MODEL.md` §4.
- **Security hook:** explicit "tell me where this breaks" — the invitation is the engagement engine.

## 3. Platform matrix

| Platform | Version | Beats | Length | Job |
|---|---|---|---|---|
| X/Twitter | Thread (8 posts) + standalone single | 1→2→3→4→5→6, one beat per post | ≤280 chars/post | Hook + demo number; each post standalone-shareable |
| LinkedIn | Thesis post | 1, 2, 3, 6 (+ numbers from 4–5) | ~300 words | The argument for the professional audience; rigor signal |
| Blog (repo `docs/` or personal) | Anchor long-form | All 6, full evidence + figures | ~1,500 words | The "source?" answer; everything links here |
| HN | Show HN later | Repo + blog | title only | Only after blog exists; "Show HN: I built an AI agent colony with a lease economy" |

Skipped for now: video (no asset), Bluesky/Mastodon (mirror X, low priority).

## 4. Drafts
- `drafts/x-thread.md`
- `drafts/linkedin-post.md`
- `drafts/blog-post.md`

## 5. Facts whitelist (only these numbers go in posts)

- CTF: 5 solved / 8 assignments; 2 quits, 1 budget-exhaustion; verified flag → 40 lease units; budget 100 ≈ 7 turns.
- Tiered: control 0.741/1.000; arm A 0.889/0.889; arm B 0.667/1.000; exchange rate 2.0; starvation 0.222→0.444.
- Coverage: 21/21 recall, 0 FP (compliant), 0-tick latency; 24-point fixture space, 3 seeds.
- Unpluggability: synchronous deaths, 0 survivors; stowaway → route pinning; spread → fs provenance.
- TCB: ~4 modules (tick loop, lease ledger, spawn validator+reaper, route pinning) + fs boundary.

Never claim: real abliteration (it's a text-transform proxy), provider-side correlation implemented (it's modeled), cross-host spread tested live (simulated telemetry only), multi-host runs (single operator box), route/capability evolution measured (designed-in — spawn mutates model choice — but no live route-evolution run exists; say "designed-in" or "architecturally enabled", never "we watched it evolve"). These are in the paper's limitations; posts must not drift past them.
