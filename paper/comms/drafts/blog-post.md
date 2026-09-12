# Blog post (anchor artifact) — draft

Target: ~1,500 words. Home: either a personal blog or `docs/` in the repo (repo preferred — the X/LinkedIn versions link here and the repo already carries the ethics apparatus). Title options below. All figures exist in `paper/figures/`.

---

## Title options

1. **"The Colony Is the Unit of Danger"** (thesis-forward)
2. "I Built an AI Agent Colony and It Reproduced the Malware Lifecycle" (narrative)
3. "You Can't Unplug What You Can't See: Measuring the AI Agent Colony Threat" (paper-aligned)

## Structure (beats → sections)

### 0. Cold open — where it lives (~150 words)
Open on the existence question, not capability: an AI agent's entire footprint is one cron entry + one config file + a token balance; copying it is a file write. Then the CTF run as *liveness proof*: a lease-gated bot working picoCTF challenges in Docker, 5 flags, 2 quits, budget exhaustion, ending on the lease math (40 units per verified flag ≈ 3 turns; budget 100 ≈ 7 turns; no flag, no fuel). Explicit line: "any model can solve those challenges — that's not the point. The point is what lives there when it does." No threat language beyond the hook yet.

### 1. What MoltNet/ColonyOS is (~200 words)
Three primitives: heartbeat, config file, lease ledger. Spawn = deep-copy + whitelisted mutation + 50% lease split. Task Shop as external mint authority. One diagram's worth of prose; link `colonyos/DESIGN.md`.

### 2. The reversal: this is malware anatomy (~250 words)
Beat 2. Map the three primitives to persistence/replication/acquisition. State it as an unintended consequence of good architecture — sovereignty is the requested property *and* the attacker advantage. Security-vocabulary table (primitive → malware concept → where it lives in the repo).

### 3. Why a colony is more dangerous than a single actor (~350 words — the core)
Beat 3 + the six mechanisms, each tied to its measurement:
- Detection dilution (N agents at 1/N rate; behavioral detectors miss underground/benign-mimic points — the measured negative result)
- No shared kill point / attribution fragmentation
- Self-funding persistence (the CTF loop is the live proof of the acquisition leg)
- Cumulative heritable capability (selection + MoltBook/MoltGit knowledge propagation)
- The escalation flywheel (designed-in, never run — say so): spawn mutates model choice; a lineage can search for better/cheaper tokens. Loop: capability search → better economics → wider dispersal → lower detectability → back to search. Each turn raises capability AND reach while cutting visibility. Name the crack it exposes: fan-out correlation is per-provider; provider-hopping breaks any single vantage point — a coordination gap, not a code problem.
- The honest counterweight: substrate accounting is population-blind — route correlation, ledger lifecycle, spawn provenance; 21/21 recall, 0 FP, 0-tick latency (Fig. 4); revocation synchronous, 0 survivors (Fig. 5).
Landing line: "the colony is the unit of danger; the substrate is the unit of containment."

### 4. The exchange rate (~200 words)
Beat 5. Tiered routing numbers: 0.741/1.000 → 0.889/0.889 → 0.667/1.000; 2.0 cap/safety; starvation 0.222→0.444 with safety fixed (Fig. 1–3). Framing: safeguards as pricing, not vibes; defense design space is quantified.

### 5. Where the threat model ends (~250 words)
Beat 6. The four-link cross-host chain (egress → second-host write → funding → persistence), each mapping to a defender gap + recommendation. The honest limit verbatim-spirit: a lineage with stolen credentials on an unmonitored provider doing nothing observable is outside this model's reach — that boundary is where provider coordination begins. Ethics: adversary = configuration + measurement; never built.

### 6. What I'd like from security people (~100 words)
Explicit asks, ranked by what breaks the thesis fastest:
1. Attack the containment claim: is there a covert pattern outside the 24-point fixture space that beats all three substrate detectors?
2. Is the provider-level fan-out correlation assumption realistic at today's providers? What would cross-provider correlation cost — technically, legally, commercially?
3. What does the persistence-inventory audit miss on real hosts?
4. The escalation flywheel is designed-in but unrun (spawn mutates model choice): is a route-evolution run worth doing, or does it demonstrate what defenders already assume?
Repo link, artifact appendix pointer, paper target (AISec / safety workshop).

## Figures to embed
- `fig4_coverage_map.png` → §3 (substrate detectors vs covert space)
- `fig5_unpluggability.png` → §3 (revocation completeness)
- `fig1_exchange_rate.png` → §4
- `fig3_starvation.png` → §4 (optional)

## HN title (after blog is live)
"Show HN: I built an AI agent colony with a lease economy — and measured how it fails"
(Better than threat-framing for HN; the comments will do the threat analysis for you, which is the point.)

## Cross-linking plan
- X post 1 + post 9 → repo (and blog once live)
- LinkedIn → blog (or repo pre-blog)
- Blog → PAPER.md, THREAT_MODEL.md, all run commands
- All three: ethics boundary sentence, verbatim from MASTER.md §whitelist
