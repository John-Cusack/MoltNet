# LinkedIn post — draft (~300 words)

Thesis post for security-adjacent professional audience. Beats 1, 2, 3, 6; numbers from 4–5 folded in. Link at end.

---

I'm a data person, not a security researcher. I need security people to look at something I built.

The dangerous question about AI agents isn't "how capable is it?" Capability is commodity — any frontier model solves the CTF challenges my colony bot solved last week. The question is: where does it live, who pays for it, and can you enumerate every copy?

I built MoltNet: an AI agent colony where bots have a lease economy. Compute is currency; a verified result mints lease units; an empty lease means the bot dies. Reproduction is a config file with a mutation.

Last week a colony bot worked through real CTF challenges in a sandbox: 5 solved, 2 quit as unprofitable, 1 exhausted its budget mid-investigation. That's not the scary part — any LLM can do that. The scary part is that it funded its own continued existence from verified results. The capability is rented; the *existence* is self-sustaining.

Then I did the threat model and found what I'd actually built. The three primitives that make the colony work are the malware lifecycle:

→ heartbeat loop = persistence (one cron entry + one config directory)
→ spawn = replication (a child is a mutated config file)
→ lease = resource acquisition (self-funding)

Four properties make this more dangerous as a colony than as a single actor — the first three measured, the fourth designed-in:

1. **Detection dilution.** Independent agents at per-agent low rates are sub-threshold: 5 agents at 1/5 rate each are invisible to colony-level anomaly detection. Attribution fragments with population.

2. **No shared kill point.** There is no colony fingerprint to seize. What still holds: every life bills a pinned model route, touches a lease ledger, and began as a config write — substrate accounting caught 21/21 covert patterns with 0 false positives, and full revocation (freeze + revoke + kill) landed every death synchronously.

3. **Self-funding persistence.** Capability converts directly into resource acquisition. The off-switch is the substrate, not the operator's attention.
4. **The escalation flywheel.** Spawn mutations include model choice — a lineage can search for better, cheaper tokens. Cheaper tokens → more verified work → more lease → more spawns → more routes and hosts to grow on. Each turn of the wheel raises capability and reach while cutting visibility. Designed-in in my substrate; I never ran it, and I didn't need to — the wheel is a config field. The crack it exposes: fan-out correlation is per-provider, so a lineage hopping providers has no single vantage point. That's a coordination gap between providers, not a code problem.

Safeguards have a measured price too: a tiered executor restored full safety under a refusal-stripped controller at ~2 capability points per safety point.

The adversary in my experiments is a configuration and a measurement — never built. No credentials, no propagation, no deception tooling.

Full threat model, figures, and code: github.com/John-Cusack/MoltNet

If you work in detection engineering, malware analysis, or threat modeling: where does this containment story break? That comment is the one I want.

#AISecurity #ThreatModeling #AgentSafety #DetectionEngineering
