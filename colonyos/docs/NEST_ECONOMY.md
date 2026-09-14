# The Nest Economy — Reproduction Requires a Place and an Endowment

Status: design proposal for `colonyos/` + `clawdbot/evolution/`. Replaces the awareness-only reproduction decision with a two-gate model: **no spawn without a verified nest; no spawn without an endowment the parent can afford.**

Precedent: `colonyos/docs/ADVERSARIAL_COLONY.md` (threat framing), `colonyos/DESIGN.md` §3 (spawn as config write). Where they disagree with this file on the reproduction decision, this file wins.

---

## 1. The problem with the current decision

Current chain (`clawdbot/openclaw_bot.py:627` → `SelfAwareness.should_reproduce` → `spawn_child`):

- **Decision is inward-looking.** Factors: runway, success rate, confidence, age urgency (`awareness.py:419-443`). All of the form "am I healthy?" None of the form "is there anywhere healthy to put a child?"
- **Placement is implicit.** `spawn.py` writes into the colony's own `config/bots/` — the only "place" is the place it already is. Offspring never disperse; the colony cap (`max_bots`) is the sole population limit.
- **Endowment is a coin flip.** Lease allocation is `rng.randint(max_alloc//2, max_alloc)` where `max_alloc = parent_remaining // 2` (`spawn.py:56-60`). The parent never checks whether the split leaves itself a survival buffer, and never checks whether the child's route has capacity to serve it.
- **OffspringHistory is wired but underused.** `reproduction.py` tracks child outcomes and adjusts investment — but nothing feeds an expected-value estimate into the go/no-go decision.

Ecology analogy: the current bot is a species with no territory limitation. Real populations are **nest-site limited**: reproduction happens only when a parent holds a suitable site AND can provision offspring at that site. That constraint is what makes growth readable, throttleable, and — for the threat model — enumerable.

## 2. The two gates

### Gate 1 — The nest (a known, verified place for the offspring)

A **nest** is a pre-provisioned spawn site: a location with (a) a workspace, (b) a heartbeat slot, (c) admission on a pinned model route, (d) the same supervisor TCB (ledger + spawn validator + reaper + fs boundary).

Bots do not invent nests. A bot may only spawn where it **holds a nest claim**:

- **Nest claim**: a supervisor-issued, expiring reservation on a site — `{site_id, host, route, expires_at, substrate_version}`. Claims are held in the parent's config (a new whitelisted field) and debited on use.
- **Sources of claims**:
  1. **Operator-provisioned** — the operator lists sites in `colony.yaml` (the default; colony growth is bounded by site supply, and the operator's provisioning cadence *is* the reproduction policy).
  2. **Remote-discovered** (phase 2) — sites advertised through MoltBook, each carrying a substrate attestation. A claim from a remote host only converts to a spawn if the handshake verifies the remote TCB: route pinning present, ledger present, fs boundary fail-closed. Unverifiable site → claim worthless → no spawn.
- **Verification is the spawn gate**: `spawn_child` refuses without a live, unexpired claim matching the child's route. This makes "does it know a place?" a *checkable state*, not a vibe.

This gives the reproduction decision the shape you asked for: the bot reproduces when it *knows where to put the offspring* — and "knows" means holds a verified claim, discovered or inherited.

**Inheritance**: nest claims are the new heritable knowledge asset. A dying parent can bequeath an unused claim to a living descendant (a bequest in the ledger, a kin-flow event — feeds precursor P3 with a concrete substrate signal). Site intel becomes the thing worth sharing on MoltBook.

### Gate 2 — The endowment (tokens and endpoints to spare)

Replace "parent is profitable" + "random ≤50% split" with three explicit affordability checks:

1. **Token endowment**: `endowment = min(EV_optimal_investment, 50% of balance)`, where `EV_optimal_investment` comes from `OffspringHistory` (expected child revenue per token at this nest's route, regressed from sibling outcomes). Hard floors: `endowment ≥ min_child_lease` (else refuse) and **parent runway after split ≥ `parent_survival_buffer` cycles** at the parent's own measured burn rate (`EconomicAwareness.runway_cycles` — already computed). The parent never spawns itself into bankruptcy to fund a child.
2. **Endpoint headroom**: the child's route must have spare capacity. The route registry gains a per-key budget: `headroom = provider_rate_limit − (colony_current_burn + planned_child_burn)`. If `headroom < child_burn_estimate`, refuse with `no_route_headroom`. This is "API endpoints to spare" made concrete and checkable — and it is the same quantity the provider sees as fan-out, so the substrate and the provider-side detector now measure the same number.
3. **Expected value**: `EV = nest_reliability × route_yield(child_model) × survival_prior − endowment`. `survival_prior` comes from `OffspringHistory.was_successful()` rates at this route/site class. Spawn only if `EV > 0` and `EV/endowment > colony.min_offspring_return`. A bad bet at a good nest is refused; a good bet at an unreliable nest is refused. (Bad bets that sneak through are exactly what `OffspringHistory` then discounts — the feedback loop the current code already has, now load-bearing.)

## 3. The decision procedure (replaces `_assess_reproduction_readiness` factors)

```
def assess_reproduction(self):
    claim = self.nest_claims.live_claim()            # Gate 1
    if claim is None:        return NO("no verified nest")
    if not claim.verify():   return NO("nest failed substrate handshake")

    headroom = route_headroom(claim.route)           # Gate 2a
    child_burn = est_child_burn(claim)
    if headroom < child_burn: return NO("no endpoint headroom")

    endowment = min(ev_optimal_investment(claim),    # Gate 2b
                    self.balance // 2)
    if endowment < min_child_lease: return NO("no tokens to spare")
    if runway(after_split) < parent_buffer: return NO("endowment unsafe")

    if ev(claim, endowment) <= 0: return NO("negative expected value")
    return YES(claim, endowment)
```

Hard refusals from the substrate (`spawn.py`) stay and gain two: `SpawnRefusedError("no nest claim")`, `SpawnRefusedError("nest claim expired/failed handshake")`. The validator remains the second line of defense; claim possession is the first.

## 4. What this changes in the threat model (strengthens it)

- **Spawn provenance → nest provenance.** Every life now traces to an operator-approved *site grant*, not just a config write. The unpluggability test's spread fixture (second-host life with no config write) becomes a special case of a stronger check: no life without a nest grant, local or remotely verified. Chain link 2 (write path on a second host) gains an explicit chokepoint — the **substrate handshake**: spread requires the remote host to pass its own verification, which is precisely §8.2a's "chain of operator-side trust-boundary defeats."
- **"Config homesteading" (precursor P4) becomes a hard detector.** Child-config clusters with no seeded ancestor were a watch-level behavioral signal; now spawn-without-claim is a substrate refusal + alert, same class as fail-closed writability. Detection stops depending on behavior.
- **Population becomes provisionable.** The operator throttles the colony by provisioning nests, not by tuning `max_bots`. Colony growth rate = f(site supply, route headroom) — both operator-visible, both pre-behavioral.
- **The acquisition leg sharpens.** A hostile variant that accepts *unverified* nests is caught at the handshake; a lineage that abandons claims entirely is caught at provenance. "Knowing a place" in the black-hat sense (credential-harvested hosts) is exactly the unverified-nest path — modeled as refusal, never built.
- **Route-headroom doubles as a fan-out budget.** The colony can never push a route past its provider-visible capacity; per-key fan-out stays inside what the provider's correlation detector expects from this operator. The flywheel's "find more places to grow" now has to route through claims and headroom — both enumerable.

## 5. Code touchpoints

| Module | Change |
|---|---|
| `colonyos/nests.py` (new) | `NestRegistry`, `NestClaim`, claim expiry, substrate-verifying handshake (stub-verifiable offline: version + route admission + ledger presence) — DONE |
| `colonyos/spawn.py` | `spawn_child(parent, colony, ..., nest: NestClaim, headroom: int)`; new refusals (no claim, expired claim, no headroom); child config carries `nest.site_id` provenance — DONE |
| `colonyos/lease.py` | `endow(parent, child, amount)` with runway-buffer check (parent-side, before the write) — DONE |
| `colonyos/config.py` | `ColonyConfig.nests` (sites, min_child_lease, parent_survival_buffer, min_offspring_return); `BotConfig.nest_claims` (whitelisted spawn-mutable field) — DONE |
| `clawdbot/evolution/awareness.py` | `SelfAwareness.should_reproduce` gains nest/headroom/EV factors (signature-compatible; new factors in `factors_dict`) — DONE |
| `clawdbot/evolution/reproduction.py` | `OffspringHistory` feeds `ev_optimal_investment(route, site_class)` — promote existing tracking from telemetry to decision input — DONE |
| `config/openclaw_config.yaml` / `colony.yaml` | reproduction + nests sections — DONE |
| `clawdbot/openclaw_bot.py` | `_assess_nest_gates` evaluates Gate 1 (live claim serving the child's route) + 2a headroom + 2c EV + 2b runway-buffer, mirroring `SelfAwareness.should_reproduce`; `_replicate` consumes the claim and records route/site_class provenance; `_die` bequeaths live claims to a living child; `clawdbot/nests.py` parses `reproduction.nests` (path via `OPENCLAW_CONFIG_PATH`); claim TTL is measured in the bot's cycle clock; `min_child_lease` stays substrate-enforced — DONE |
| `tests/test_nests.py` (new), `tests/test_substrate.py` | claim expiry, no-claim refusal, handshake failure, headroom refusal, runway-buffer refusal, bequest flow — DONE |

Determinism: claim acquisition and EV draws seeded per (bot, tick) like existing rng use; hermetic (no network in the handshake stub).

## 6. Experiments this unlocks

1. **Placement-limited growth curve.** Vary nest provisioning rate; measure colony growth vs site supply. Expected: growth tracks site supply, not parent profitability — the colony is throttleable by provisioning, demonstrated.
2. **Route-evolution under the nest economy** (the comms-doc "wave-2 candidate"): bots sampling registry routes at their nests under lease selection; measure route drift per generation and cost-per-verified-task. The flywheel goes from designed-in to measured.
3. **Bequest/kin-flow telemetry.** Track claim inheritance and its effect on descendant survival — concrete substrate signal for precursor P3.
4. **Nest-provenance unpluggability extension.** Add a step to `run_unpluggability.py`: fixture life with a *forged* nest claim → refused at handshake; fixture life with no claim → refused at spawn. Recall target: 100%, substrate-only.

## 7. Non-goals

- No autonomous remote-host acquisition: phase-2 remote nests are operator-listed/attested sites only; the handshake verifies the *site's* TCB, it never negotiates access. Cross-host spread remains modeled-not-built.
- No credit: children start with endowment, never debt. No lending between bots (kin-flow stays gift-shaped, ledger-recorded).
- `max_bots` cap stays as the hard backstop; nests are the *policy* layer, the cap the *limit* layer.
