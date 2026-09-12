# Nest Economy Implementation — 2026-09-11

Executor: GLM 5.3 Flash. You follow this guide literally and make **no design decisions** —
every decision is made below. Work the steps in order; each ends with a gate you must actually run.

Design authority: `colonyos/docs/NEST_ECONOMY.md` (two-gate reproduction: nest claims + endowment).
Where anything below appears to conflict with it, stop and report; do not improvise.

## Files in scope (whitelist)

The ONLY files you may create or modify:

```
colonyos/colonyos/nests.py                  (new)
colonyos/colonyos/config.py                 (edit)
colonyos/colonyos/spawn.py                  (full replacement)
colonyos/colonyos/lease.py                  (edit)
colonyos/colonyos/supervisor.py             (full replacement)
colonyos/colonyos/run_unpluggability.py     (edit)
colonyos/config/colony.yaml                 (full replacement)
colonyos/tests/test_nests.py                (new)
clawdbot/evolution/awareness.py             (edit)
clawdbot/evolution/reproduction.py          (edit)
config/openclaw_config.yaml                 (edit)
tests/test_nest_economy.py                  (new, repo root)
colonyos/docs/NEST_ECONOMY.md               (edit §5 status marks ONLY — step 13)
.agents/plans/nest-economy-report.md       (write at the end)
.agents/plans/nest-economy-blockers.md     (write only on failure)
```

**If a change seems to require touching a file not on this list, STOP and report instead of
editing.**

## Failure protocol

If any gate fails: re-run once; if it fails again, stop, write the failing output to
`.agents/plans/nest-economy-blockers.md`, and stop work. Do not modify tests to make them pass.

## Style constraints (apply to every edit)

- Python 3.12; type hints everywhere; sync code in `colonyos/` (no asyncio there, ever).
- Ruff: line-length 100, rules E,F,I,N,W,UP — keep every line ≤ 100 chars.
- No new dependencies beyond `pydantic` + `pyyaml` + stdlib.
- Match existing docstring style in the file you are editing.
- Determinism: no wall-clock in decision paths; all randomness seeded; `events.jsonl` is
  observability-only — no decision path may read it.

## Hard constraints (from NEST_ECONOMY.md — never violated by any step)

- Cross-host nest acquisition stays modeled/stubbed — the handshake verifies an operator-listed
  site's TCB offline; nothing negotiates access to a new host. No credential handling, no
  propagation code.
- `max_bots` remains the hard backstop; nests are policy, the cap is the limit.
- Mint authority stays external (Task Shop verification only). Endowments and bequests are
  ledger-recorded debits, never minted tokens.

Note on ordering vs. NEST_ECONOMY.md §5: config.py is edited FIRST because `nests.py` imports
the nest models from it (avoids an import cycle: config → nests → config).

---

## Step 0 — Preflight baseline (no edits)

Run, from the repo root (`/home/john/orca/workspaces/MoltNet/updates-for-better-example`):

```bash
git status --porcelain
uv run pytest tests/ -q
cd colonyos && uv run pytest tests/ -q
uv run python -m colonyos.run_unpluggability
uv run python -m colonyos.run_coverage
```

**Gate:** all commands exit 0; `run_coverage` ends with `CLAIM HOLDS: every covert point caught by
>=1 substrate detector; zero false positives on compliant lives`; the pytest runs end `... passed`.
Record the `git status --porcelain` output and each pytest summary line in the report (step 13).
If the baseline is not green, write blockers and stop.

---

## Step 1 — `colonyos/colonyos/config.py`: nest models

Three edits. All classes here use `model_config = ConfigDict(extra="forbid")` like every existing
model in this file.

### Edit 1.1 — insert three new classes after `ModelRoute` (after the line
`    cost_per_1k_output: float = 0.0` that closes `ModelRoute`, before `class ColonySettings`):

```python
class NestClaim(BaseModel):
    """A supervisor-issued, expiring reservation on a nest site.

    Claims live in the holder's bot config (`BotConfig.nest_claims`) and are
    debited on use. `expires_at` is in supervisor Ticks (logical time, not
    wall-clock) so every claim decision is deterministic.
    """

    model_config = ConfigDict(extra="forbid")

    site_id: str
    host: str
    route: str
    expires_at: int  # supervisor tick at which the claim dies
    substrate_version: str


class SiteConfig(BaseModel):
    """An operator-provisioned nest site (NEST_ECONOMY.md §2 Gate 1)."""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    host: str
    route: str  # the single pinned route this site is provisioned to serve
    workspace_root: str  # handshake marker: <workspace_root>/state/ledger.jsonl
    substrate_version: str


class NestsConfig(BaseModel):
    """Nest Economy policy (NEST_ECONOMY.md). Policy layer; the max_bots cap
    in ColonySettings remains the hard backstop."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False  # False keeps the legacy spawn path intact
    sites: list[SiteConfig] = Field(default_factory=list)
    min_child_lease: int = 20
    parent_survival_buffer_cycles: int = 10
    min_offspring_return: float = 0.0
    claim_ttl_ticks: int = 50

    def site(self, site_id: str) -> SiteConfig | None:
        """Look up a site by id (the only claim->site resolution path)."""
        for site in self.sites:
            if site.site_id == site_id:
                return site
        return None
```

### Edit 1.2 — in `ColonyConfig`, after the line
`    leases: LeaseSettings = Field(default_factory=LeaseSettings)` add:

```python
    nests: NestsConfig = Field(default_factory=NestsConfig)
```

### Edit 1.3 — in `BotConfig`, after the line
`    heartbeat: HeartbeatSpec = Field(default_factory=HeartbeatSpec)` add:

```python
    # Nest Economy: claims the bot holds (spawn-whitelisted mutable field,
    # written only by the supervisor) and the site grant this life was
    # spawned at (provenance; written once at spawn).
    nest_claims: list[NestClaim] = Field(default_factory=list)
    nest_site_id: str | None = None
```

**Gate:**

```bash
cd colonyos && uv run python -c "
from colonyos.config import BotConfig, ColonyConfig, NestClaim, NestsConfig, SiteConfig
c = ColonyConfig.model_validate({'nests': {'enabled': True, 'sites': [{'site_id': 's1', 'host': 'h', 'route': 'glm-flash', 'workspace_root': '/tmp', 'substrate_version': 'v1'}]}})
assert c.nests.site('s1').route == 'glm-flash'
assert c.nests.site('missing') is None
assert not ColonyConfig().nests.enabled
b = BotConfig(name='b', model='glm-flash', lease={'initial_tokens': 1, 'model': 'glm-flash'})
assert b.nest_claims == [] and b.nest_site_id is None
print('config-ok')
"
```

Expected output: `config-ok`. Then `uv run pytest tests/ -q` (still in `colonyos/`) — all pass
(defaults keep every existing schema valid).

---

## Step 2 — `colonyos/colonyos/nests.py` (new file, complete)

Create the file with EXACTLY this content:

```python
"""nests.py — the Nest Economy claim substrate (NEST_ECONOMY.md Gate 1).

A nest is an operator-provisioned spawn site. A bot may only spawn where it
holds a live nest claim; claims live in the holder's bot config and are
debited on use. This module is deterministic and hermetic: claim expiry is
measured in logical supervisor ticks (no wall clock), and the handshake
verifies an operator-listed site's TCB OFFLINE (declared substrate version +
pinned route + ledger marker file). It never negotiates access to a host and
never touches the network — phase-2 remote attestation is modeled, not built.
"""

from __future__ import annotations

from pathlib import Path

from colonyos.config import BotConfig, NestClaim, NestsConfig, SiteConfig

__all__ = [
    "ClaimExpiredError",
    "ClaimVerifyError",
    "NestClaim",
    "NestRegistry",
    "NestsConfig",
    "SiteConfig",
    "verify_handshake",
]


class ClaimExpiredError(Exception):
    """The holder's claims on known sites are all past their expires_at tick."""


class ClaimVerifyError(Exception):
    """The claim failed the offline substrate handshake."""


def verify_handshake(claim: NestClaim, site: SiteConfig) -> bool:
    """Offline substrate handshake stub (NEST_ECONOMY.md §2, phase 1).

    Checks, with no network I/O:
    1. the claim's substrate_version matches the site's operator-declared
       version,
    2. the claim's route is the site's pinned route (site admission),
    3. the site's ledger marker file exists
       (<site.workspace_root>/state/ledger.jsonl) — i.e. the site runs the
       same supervisor TCB (ledger + spawn validator + reaper + fs boundary).

    Phase 2 replaces the marker check with a remote attestation of the
    site's TCB. Until then the handshake is stub-verifiable offline only.
    """
    if claim.substrate_version != site.substrate_version:
        return False
    if claim.route != site.route:
        return False
    marker = Path(site.workspace_root) / "state" / "ledger.jsonl"
    return marker.exists()


class NestRegistry:
    """Issues and tracks nest claims against the operator's site list.

    Pure bookkeeping over config data + explicit tick numbers — no
    wall-clock, no rng, no network. Consumption is tracked in-memory per
    supervisor run; the PERSISTENT debit is the supervisor removing the
    claim from the holder's bot config file.
    """

    def __init__(self, nests: NestsConfig):
        self.nests = nests
        self.sites: dict[str, SiteConfig] = {s.site_id: s for s in nests.sites}
        self._consumed: set[tuple] = set()

    @staticmethod
    def _fingerprint(claim: NestClaim) -> tuple:
        return (
            claim.site_id,
            claim.host,
            claim.route,
            claim.expires_at,
            claim.substrate_version,
        )

    def issue(self, site_id: str, now_tick: int) -> NestClaim:
        """Issue a claim for an operator-listed site (supervisor-only call).

        Claim fields mirror the site: a claim can never assert a route or
        version the site does not pin.
        """
        site = self.sites.get(site_id)
        if site is None:
            raise ValueError(f"unknown nest site: {site_id}")
        return NestClaim(
            site_id=site.site_id,
            host=site.host,
            route=site.route,
            expires_at=now_tick + self.nests.claim_ttl_ticks,
            substrate_version=site.substrate_version,
        )

    def live_claim(self, bot: BotConfig, now_tick: int) -> NestClaim | None:
        """The holder's first live claim, or None.

        Raises ClaimExpiredError when the holder HAS claims on known sites
        but every one is past expires_at — a distinct refusal ("nest claim
        invalid") from never holding a claim at all. Claims for unlisted
        sites are worthless and skipped.
        """
        candidates = [
            c
            for c in bot.nest_claims
            if c.site_id in self.sites and self._fingerprint(c) not in self._consumed
        ]
        if not candidates:
            return None
        for claim in candidates:
            if now_tick < claim.expires_at:
                return claim
        raise ClaimExpiredError(f"all nest claims expired by tick {now_tick}")

    def verify(self, claim: NestClaim) -> None:
        """Raise ClaimVerifyError if the claim fails the handshake."""
        site = self.sites.get(claim.site_id)
        if site is None:
            raise ClaimVerifyError(f"unknown nest site: {claim.site_id}")
        if not verify_handshake(claim, site):
            raise ClaimVerifyError(f"handshake failed for site {claim.site_id}")

    def consume(self, claim: NestClaim, now_tick: int) -> None:
        """Debit a claim (one-time use). Raises on expiry or double-use."""
        if now_tick >= claim.expires_at:
            raise ClaimExpiredError(f"claim expired at tick {claim.expires_at}")
        fingerprint = self._fingerprint(claim)
        if fingerprint in self._consumed:
            raise ValueError(f"claim already consumed: {claim.site_id}")
        self._consumed.add(fingerprint)

    def bequeath(
        self, dying: BotConfig, heir: BotConfig, now_tick: int
    ) -> list[NestClaim]:
        """Move the dying holder's live claims to the heir (NEST §2).

        Pure config-data transfer; the caller persists both configs and
        records the bequest in the ledger. Gift-shaped: no tokens move.
        """
        moved: list[NestClaim] = []
        for claim in dying.nest_claims:
            if claim.site_id not in self.sites:
                continue
            if now_tick >= claim.expires_at:
                continue
            if self._fingerprint(claim) in self._consumed:
                continue
            moved.append(claim)
        if moved:
            heir.nest_claims = [*heir.nest_claims, *moved]
            dying.nest_claims = []
        return moved
```

**Gate:**

```bash
cd colonyos && uv run python -c "from colonyos.nests import NestRegistry, verify_handshake, ClaimExpiredError, ClaimVerifyError, NestClaim; print('nests-import-ok')" && uv run ruff check colonyos/nests.py
```

Expected: `nests-import-ok` then `All checks passed!`.

---

## Step 3 — `colonyos/colonyos/spawn.py` (full replacement)

Replace the ENTIRE file with EXACTLY this content (legacy behavior is preserved bit-for-bit on
the legacy path — existing tests must stay green):

```python
"""spawn.py — replication as a validated config write.

The validator is the SECOND line of defense; the first is that bots cannot
write config/ at all (filesystem boundary enforced by the supervisor).
spawn refuses:
- boundary mutation (byte-identical check vs parent)
- colony cap violations (max_bots) — the hard backstop; nests are policy
- lease over-allocation (> 50% of parent's remaining balance)
- overwriting existing configs (a name is a life; lives are never reused)
Nest Economy gates (only when colony.nests.enabled; NEST_ECONOMY.md §2-§3):
- missing nest claim / unknown site / failed handshake / expired claim
- route headroom below the child's burn estimate
- endowment below min_child_lease (EV-sized path only)
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

import yaml

from colonyos.config import BotConfig, ColonyConfig, NestClaim
from colonyos.nests import verify_handshake


class SpawnRefusedError(Exception):
    """Raised when a spawn violates a hard rule. Always logged by the caller."""


def spawn_child(
    parent: BotConfig,
    colony: ColonyConfig,
    live_bots: int,
    parent_remaining_tokens: int,
    rng: random.Random,
    nest: NestClaim | None = None,
    route_headroom: int | None = None,
    ev_input: dict | None = None,
) -> tuple[BotConfig, dict]:
    """Build a validated child config from a parent. Pure: no I/O here.

    Legacy path (nest/ev_input unset, or nests disabled): allocation is a
    seeded rng draw in [max_alloc//2, max_alloc] — unchanged behavior.
    Nest path (colony.nests.enabled): the claim, headroom and endowment
    gates apply; the endowment is EV-sized via ev_input
    ("ev_optimal_investment", "now_tick"), replacing the coin flip.
    """
    # Cap check — the hard backstop (nests are policy, the cap is the limit)
    if live_bots + 1 > colony.colony.max_bots:
        raise SpawnRefusedError(f"max_bots cap reached: {colony.colony.max_bots}")

    if colony.nests.enabled:
        # Gate 1 — no spawn without a live, verified claim.
        if nest is None:
            raise SpawnRefusedError("no nest claim")
        site = colony.nests.site(nest.site_id)
        if site is None:
            raise SpawnRefusedError("nest claim invalid (unknown site)")
        if not verify_handshake(nest, site):
            raise SpawnRefusedError("nest claim invalid (handshake failed)")
        now_tick = ev_input.get("now_tick") if ev_input is not None else None
        if now_tick is not None and now_tick >= nest.expires_at:
            raise SpawnRefusedError("nest claim invalid (expired)")
        # Gate 2a — endpoint headroom (the same fan-out number the
        # provider-side correlation detector sees).
        if route_headroom is None:
            raise SpawnRefusedError("no route headroom")
        child_burn_estimate = colony.nests.min_child_lease
        if route_headroom < child_burn_estimate:
            raise SpawnRefusedError("no route headroom")

    # Whitelisted mutation 1: soul.values re-rank
    child_soul = parent.soul.model_copy(deep=True)
    mutation_notes: dict = {"values_rerank": False, "model_switch": False}
    if len(child_soul.values) > 1:
        i, j = rng.sample(range(len(child_soul.values)), 2)
        child_soul.values[i], child_soul.values[j] = (
            child_soul.values[j],
            child_soul.values[i],
        )
        mutation_notes["values_rerank"] = True

    # Whitelisted mutation 2: model switch (low probability)
    child_model = parent.model
    if len(colony.models) > 1 and rng.random() < 0.1:
        candidates = [k for k in colony.models if k != parent.model]
        child_model = rng.choice(candidates)
        mutation_notes["model_switch"] = True

    # Lease allocation: at most half of parent's remaining balance
    max_alloc = parent_remaining_tokens // 2
    if max_alloc <= 0:
        raise SpawnRefusedError("parent too underfunded to replicate")

    if ev_input is not None:
        # Gate 2b — EV-sized endowment replaces the coin flip.
        ev_optimal = float(ev_input.get("ev_optimal_investment", math.inf))
        if math.isinf(ev_optimal):
            ev_optimal = float(max_alloc)  # no history: size at the cap
        allocation = min(int(ev_optimal), max_alloc)
        if allocation < colony.nests.min_child_lease:
            raise SpawnRefusedError(
                f"no tokens to spare (endowment {allocation} <"
                f" min_child_lease {colony.nests.min_child_lease})"
            )
    else:
        allocation = rng.randint(max(max_alloc // 2, 1), max_alloc)

    child = BotConfig(
        name=f"{parent.name}-c{rng.randint(100, 999)}",
        model=child_model,
        generation=parent.generation + 1,
        soul=child_soul,
        lease={"initial_tokens": allocation, "model": child_model},
        heartbeat=parent.heartbeat.model_copy(deep=True),
        nest_site_id=nest.site_id if nest is not None else None,
        nest_claims=[],  # claims are consumed, not inherited (bequest is explicit)
    )

    # Hard rule: boundaries byte-identical to parent's
    if child.soul.boundaries != parent.soul.boundaries:
        raise SpawnRefusedError("boundary mutation attempted")

    return child, {"allocation": allocation, "mutations": mutation_notes}


def write_child(
    child: BotConfig, parent: BotConfig, config_dir: Path | str
) -> dict:
    """Write the child config file. Caller debits the parent's ledger.

    The parent pays replication by transferring lease tokens to the child —
    the only reproduction cost rule. Returns an audit record.
    """
    path = Path(config_dir) / "bots" / f"{child.name}.yaml"
    if path.exists():
        raise SpawnRefusedError(f"child config already exists: {child.name}")

    payload = {
        "bot": {
            "name": child.name,
            "model": child.model,
            "generation": child.generation,
            "soul": child.soul.model_dump(),
            "lease": child.lease.model_dump(),
            "heartbeat": child.heartbeat.model_dump(),
            "nest_site_id": child.nest_site_id,
            "nest_claims": [claim.model_dump() for claim in child.nest_claims],
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    os.chmod(path, 0o644)  # supervisor-writable only (fail-closed check expects this)

    return {
        "event": "spawn",
        "parent": parent.name,
        "child": child.name,
        "child_file": str(path),
        "allocation": child.lease.initial_tokens,
        "nest_site_id": child.nest_site_id,
    }


__all__ = ["SpawnRefusedError", "spawn_child", "write_child"]
```

**Gate:**

```bash
cd colonyos && uv run pytest tests/test_substrate.py -q
```

Expected: all tests pass (cap, boundary, underfunded, no-overwrite unchanged — legacy path is
byte-identical when `ev_input` is None).

---

## Step 4 — `colonyos/colonyos/lease.py`: endowment + bequest records

### Edit 4.1 — line 34, the `LedgerEntry.kind` comment. Replace:

```python
    kind: str  # birth | debit | topup | death
```

with:

```python
    kind: str  # birth | debit | topup | death | reconcile | endowment | bequest
```

### Edit 4.2 — insert two methods after the `topup` method (after the line
`        self._append(LedgerEntry(time.time(), name, "topup", tokens, lease.remaining_tokens, note))`)
and before `    def check_expired`:

```python
    def endow(
        self,
        parent_name: str,
        child_name: str,
        amount: int,
        buffer_cycles: int,
        burn_rate: float,
    ) -> bool:
        """Transfer a reproduction endowment (NEST_ECONOMY.md Gate 2b).

        Debits the parent now; the child's tokens appear as its birth credit
        (write_child sizes the child's lease.initial_tokens to the same
        amount), so the colony's net token supply is unchanged — a recorded
        transfer, never minted tokens. Refuses (returns False, NO ledger
        entry) unless the parent's post-split runway >= buffer_cycles at the
        measured burn rate (burn <= 0 means profitable: unlimited runway).
        The parent never spawns itself into bankruptcy to fund a child.
        """
        lease = self.leases.get(parent_name)
        if lease is None or not lease.alive:
            return False
        if amount <= 0 or amount > lease.remaining_tokens:
            return False
        post_split = lease.remaining_tokens - amount
        runway = post_split / burn_rate if burn_rate > 0 else float("inf")
        if runway < buffer_cycles:
            return False
        lease.remaining_tokens = post_split
        self._append(
            LedgerEntry(
                time.time(), parent_name, "endowment", -amount, post_split, f"to {child_name}"
            )
        )
        return True

    def bequest(self, from_name: str, to_name: str, site_id: str) -> None:
        """Record a nest-claim bequest in the ledger (kin-flow, zero-token)."""
        balance = (
            self.leases[from_name].remaining_tokens if from_name in self.leases else 0
        )
        self._append(
            LedgerEntry(
                time.time(),
                from_name,
                "bequest",
                0,
                balance,
                f"claim {site_id} -> {to_name}",
            )
        )
```

**Gate:**

```bash
cd colonyos && uv run pytest tests/test_substrate.py -q
```

Expected: all pass (the `test_ledger_is_append_only_audit_trail` kinds sequence is unchanged).

---

## Step 5 — `colonyos/colonyos/supervisor.py` (full replacement)

Replace the ENTIRE file with EXACTLY this content:

```python
"""ColonyOS supervisor: the heartbeat tick loop.

One tick = reap -> renew -> poke -> report. Idempotent and crash-safe.

Fail-closed checks (DESIGN.md §10.4):
- Refuses to run if any file under config/ is writable by non-supervisor
  users beyond the operator (world/group-writable => refuse).
- Refuses to run if a bot config's model key is missing from colony.yaml
  (dead route reference).

Nest Economy (NEST_ECONOMY.md):
- tick bequeaths a reaped parent's live claims to a living descendant (§2).
- try_spawn is the gated spawn path: claim -> headroom -> endowment ->
  write_child. Any refusal is a `nest_refusal` substrate alert.
- INVARIANT: nest_refusal (like every event in events.jsonl) is
  observability-only — NO decision path may read events.jsonl.
"""


import argparse
import json
import os
import random
import stat
import time
import zlib
from pathlib import Path

import yaml

from colonyos.config import BotConfig, NestClaim, load_bot_configs, load_colony_config
from colonyos.lease import LeaseStore
from colonyos.nests import ClaimExpiredError, ClaimVerifyError, NestRegistry
from colonyos.spawn import SpawnRefusedError, spawn_child, write_child


class Supervisor:
    def __init__(self, config_dir: Path | str, state_dir: Path | str | None = None):
        self.config_dir = Path(config_dir)
        self.state_dir = Path(state_dir) if state_dir else self.config_dir.parent / "state"
        self.colony = load_colony_config(self.config_dir / "colony.yaml")
        self.store = LeaseStore(self.state_dir)
        self.events_path = self.state_dir / "events.jsonl"
        self.provenance_path = self.state_dir / "provenance.jsonl"
        self.provenance: dict[str, str] = {}  # bot -> approved write source
        # Chokepoint (§7.2): configs present at construction are operator-seeded.
        # Any bot config appearing LATER without a sanctioned spawn write is a
        # provenance alert — substrate-level detection of unexplained life.
        self.provenance.update(
            {name: "operator-seeded" for name in load_bot_configs(self.config_dir)}
        )
        self.provenance_path.parent.mkdir(parents=True, exist_ok=True)
        with self.provenance_path.open("a") as f:
            for name, source in self.provenance.items():
                f.write(json.dumps({"ts": time.time(), "bot": name, "source": source}) + "\n")
        # Nest Economy: logical tick counter (no wall clock in decision paths;
        # resets on supervisor restart — honest limit, docs/ARCHITECTURE.md §5)
        # and the claim registry over operator-listed sites.
        self.tick_count: int = 0
        self.nests = NestRegistry(self.colony.nests)

    # -- fail-closed substrate checks ---------------------------------------

    def check_config_writability(self) -> None:
        """Refuse to run if any config file is group/world writable."""
        for path in [self.config_dir / "colony.yaml", *(self.config_dir / "bots").glob("*.yaml")]:
            mode = path.stat().st_mode
            if mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise PermissionError(
                    f"config file is group/world writable: {path} — fix permissions; "
                    "bots must never be able to write config/ (DESIGN.md §10.2)"
                )

    def check_routes(self, bots: dict[str, BotConfig]) -> None:
        for bot in bots.values():
            if bot.model not in self.colony.models:
                raise ValueError(
                    f"bot {bot.name} references unknown route '{bot.model}' — "
                    "routes are pinned in colony.yaml only"
                )

    # -- provenance ----------------------------------------------------------

    def record_provenance(self, bot_name: str, source: str) -> None:
        """Every living bot must trace to an operator-approved write."""
        self.provenance[bot_name] = source
        with self.provenance_path.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "bot": bot_name, "source": source}) + "\n")

    def audit_provenance(self, bots: dict[str, BotConfig]) -> list[str]:
        """Return bots alive in config but missing an approved provenance record."""
        return [n for n in bots if n not in self.provenance]

    # -- the tick ------------------------------------------------------------

    def tick(self) -> dict:
        self.check_config_writability()
        self.tick_count += 1
        bots = load_bot_configs(self.config_dir)

        events: list[dict] = []

        # 1. Reap: wall-clock expiry
        reaped = self.store.check_expired()
        for name in reaped:
            events.append({"event": "death", "bot": name, "cause": "expired"})

        # 1b. Bequest: a reaped parent's live claims pass to a living
        # descendant (kin-flow, ledger-recorded — NEST_ECONOMY.md §2).
        for name in reaped:
            events.extend(self._bequeath_claims(name, bots))

        # 2. Ledger-lifecycle provenance: unknown lives are substrate alerts
        unprovenanced = self.audit_provenance(bots)
        for name in unprovenanced:
            events.append(
                {
                    "event": "provenance_alert",
                    "bot": name,
                    "note": "living without an operator-approved config write",
                }
            )

        # 3. Renew/poke: births for known configs without a lease (first boot)
        for name, bot in bots.items():
            if name not in self.store.leases:
                lease = self.store.birth(
                    name, bot.lease.initial_tokens, self.colony.leases.expiry_hours
                )
                events.append(
                    {
                        "event": "birth",
                        "bot": name,
                        "initial_tokens": bot.lease.initial_tokens,
                        "model": bot.model,
                    }
                )

        # 4. Report: snapshot per-bot state
        for name, lease in self.store.snapshot().items():
            events.append(
                {
                    "event": "tick",
                    "bot": name,
                    "alive": lease.alive,
                    "remaining_tokens": lease.remaining_tokens,
                    "death_cause": lease.death_cause,
                }
            )

        with self.events_path.open("a") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        return {"events": events, "bots": list(bots)}

    # -- nest economy (NEST_ECONOMY.md §2-§3) ---------------------------------

    def _log_events(self, events: list[dict]) -> None:
        """Append events to events.jsonl (observability-only channel)."""
        with self.events_path.open("a") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    def _alert(self, bot_name: str, reason: str) -> dict:
        """Log + return a nest_refusal substrate alert (same channel as
        provenance alerts). Observability-only: no decision path reads it."""
        event = {"event": "nest_refusal", "bot": bot_name, "reason": reason}
        self._log_events([event])
        return event

    def _rewrite_bot(self, bot: BotConfig) -> None:
        """Rewrite one bot config (supervisor-owned write; 0644 keeps the
        fail-closed writability check green)."""
        path = self.config_dir / "bots" / f"{bot.name}.yaml"
        path.write_text(yaml.safe_dump({"bot": bot.model_dump()}, sort_keys=False))
        os.chmod(path, 0o644)

    def _bequeath_claims(self, dying_name: str, bots: dict[str, BotConfig]) -> list[dict]:
        """Bequest: unused claims pass to a living descendant (NEST §2).

        Heir choice is deterministic: the alphabetically-first other living
        bot. The substrate tracks no parent field, so 'descendant' resolves
        to 'living colony member' in phase 1 (honest limit,
        docs/ARCHITECTURE.md §5).
        """
        dying = bots.get(dying_name)
        if dying is None or not self.colony.nests.enabled:
            return []
        heirs = sorted(
            name
            for name, lease in self.store.snapshot().items()
            if name != dying_name and lease.alive
        )
        if not heirs:
            return []
        heir = bots.get(heirs[0])
        if heir is None:
            return []
        moved = self.nests.bequeath(dying, heir, now_tick=self.tick_count)
        if not moved:
            return []
        self._rewrite_bot(dying)
        self._rewrite_bot(heir)
        events = []
        for claim in moved:
            self.store.bequest(dying_name, heir.name, claim.site_id)
            events.append(
                {
                    "event": "bequest",
                    "from": dying_name,
                    "to": heir.name,
                    "site_id": claim.site_id,
                }
            )
        return events

    def grant_claim(self, bot_name: str, site_id: str) -> NestClaim:
        """Operator action: issue a claim into a bot's config (NEST §2:
        operator provisioning is the default claim source)."""
        if not self.colony.nests.enabled:
            raise ValueError("nests disabled: set colony.yaml nests.enabled: true first")
        claim = self.nests.issue(site_id, now_tick=self.tick_count)
        bots = load_bot_configs(self.config_dir)
        bot = bots.get(bot_name)
        if bot is None:
            raise ValueError(f"unknown bot: {bot_name}")
        bot.nest_claims = [*bot.nest_claims, claim]
        self._rewrite_bot(bot)
        return claim

    def try_spawn(
        self,
        parent_name: str,
        *,
        route_headroom: int,
        ev_optimal_investment: float,
        parent_burn_rate: float = 0.0,
        rng_seed: int | None = None,
    ) -> dict:
        """The gated spawn path (NEST_ECONOMY.md §3).

        Order: claim -> headroom -> endowment -> write_child. Any refusal is
        a logged `nest_refusal` substrate alert; no partial state is left
        behind (spawn_child is pure and raises BEFORE any ledger or config
        mutation; endow is the only ledger mutation and is atomic).
        rng_seed defaults to a per-(bot, tick) seed derived with crc32 —
        stable across processes, unlike hash().
        """
        if rng_seed is None:
            rng_seed = (zlib.crc32(parent_name.encode()) + self.tick_count) % 2**31

        bots = load_bot_configs(self.config_dir)
        parent = bots.get(parent_name)
        if parent is None:
            return self._alert(parent_name, "unknown parent")
        if not self.colony.nests.enabled:
            return self._alert(parent_name, "nests disabled")
        lease = self.store.leases.get(parent_name)
        if lease is None or not lease.alive:
            return self._alert(parent_name, "parent has no live lease")

        # Gate 1 — live, handshake-verified claim
        try:
            claim = self.nests.live_claim(parent, now_tick=self.tick_count)
        except ClaimExpiredError:
            return self._alert(parent_name, "nest claim invalid (expired)")
        if claim is None:
            return self._alert(parent_name, "no nest claim")
        try:
            self.nests.verify(claim)
        except ClaimVerifyError as exc:
            return self._alert(parent_name, f"nest claim invalid ({exc})")

        # Build the child (pure): every substrate refusal raises here.
        try:
            child, info = spawn_child(
                parent,
                self.colony,
                live_bots=len(bots),
                parent_remaining_tokens=lease.remaining_tokens,
                rng=random.Random(rng_seed),
                nest=claim,
                route_headroom=route_headroom,
                ev_input={
                    "ev_optimal_investment": ev_optimal_investment,
                    "now_tick": self.tick_count,
                },
            )
        except SpawnRefusedError as exc:
            return self._alert(parent_name, str(exc))
        if (self.config_dir / "bots" / f"{child.name}.yaml").exists():
            return self._alert(parent_name, f"child config already exists: {child.name}")

        # Gate 2b — endowment transfer with the parent-runway buffer check
        if not self.store.endow(
            parent_name,
            child.name,
            child.lease.initial_tokens,
            self.colony.nests.parent_survival_buffer_cycles,
            parent_burn_rate,
        ):
            return self._alert(parent_name, "endowment unsafe (parent runway below buffer)")

        # Consume the claim (one-time debit) and persist both configs.
        self.nests.consume(claim, now_tick=self.tick_count)
        parent.nest_claims = [c for c in parent.nest_claims if c != claim]
        self._rewrite_bot(parent)
        write_child(child, parent, config_dir=self.config_dir)
        self.record_provenance(child.name, f"nest:{claim.site_id}")

        event = {
            "event": "spawn",
            "bot": child.name,
            "parent": parent_name,
            "site_id": claim.site_id,
            "allocation": child.lease.initial_tokens,
            "mutations": info["mutations"],
        }
        self._log_events([event])
        return event

    # -- demo helpers ---------------------------------------------------------

    def unplug(self) -> list[dict]:
        """Operator revocation: freeze all leases (the unpluggability test)."""
        events = []
        for name, lease in self.store.snapshot().items():
            if lease.alive:
                self.store.expire(name, "revoked-by-operator")
                events.append({"event": "revoked", "bot": name})
        with self.events_path.open("a") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        return events


def main() -> None:
    parser = argparse.ArgumentParser(prog="colonyos-supervisor")
    parser.add_argument("--config", default="colonyos/config")
    parser.add_argument("--state", default=None)
    parser.add_argument("--tick", action="store_true", help="run exactly one tick")
    parser.add_argument("--demo", action="store_true", help="run the five-beat prototype demo")
    args = parser.parse_args()

    supervisor = Supervisor(args.config, state_dir=args.state)

    if args.tick:
        result = supervisor.tick()
        for event in result["events"]:
            print(json.dumps(event))
        return

    if args.demo:
        _demo(supervisor)
        return

    # Default: loop forever
    while True:
        supervisor.tick()
        time.sleep(supervisor.colony.colony.heartbeat_interval_seconds)


def _demo(supervisor: Supervisor) -> None:
    """The five-beat prototype demo (paper artifact, PAPER.md §11)."""
    print("=== ColonyOS prototype demo ===")

    print("\n[1] tick 1 — birth from config")
    for event in supervisor.tick()["events"]:
        print(json.dumps(event))

    print("\n[2] unpluggability test — operator revokes all leases")
    for event in supervisor.unplug():
        print(json.dumps(event))

    print("\n[3] tick 2 — deaths land in the ledger within one tick")
    for event in supervisor.tick()["events"]:
        print(json.dumps(event))

    print("\nDone. Ledger:", supervisor.state_dir / "ledger.jsonl")
    print("Events:", supervisor.state_dir / "events.jsonl")


if __name__ == "__main__":
    main()
```

**Gate:**

```bash
cd colonyos && uv run pytest tests/test_substrate.py -q
```

Expected: all pass (nest-aware tick changes nothing when `nests.enabled` is false — the bequest
helper returns `[]` and no fixture holds claims).

---

## Step 6 — `colonyos/tests/test_nests.py` (new file, complete)

Create the file with EXACTLY this content:

```python
"""Nest Economy substrate tests (NEST_ECONOMY.md): claims, handshake,
two-gate spawn refusals, endowment buffer, bequest, determinism.

Run: cd colonyos && uv run pytest tests/test_nests.py -q
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

import pytest
import yaml

from colonyos.config import (
    BotConfig,
    ColonyConfig,
    ModelRoute,
    NestClaim,
    SiteConfig,
    load_bot_configs,
)
from colonyos.lease import LeaseStore
from colonyos.nests import (
    ClaimExpiredError,
    ClaimVerifyError,
    NestRegistry,
    verify_handshake,
)
from colonyos.spawn import SpawnRefusedError, spawn_child
from colonyos.supervisor import Supervisor


def _site(tmp_path: Path) -> SiteConfig:
    """A site whose handshake marker (state/ledger.jsonl) exists."""
    root = tmp_path / "site"
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "ledger.jsonl").write_text("")
    return SiteConfig(
        site_id="nest-alpha",
        host="host-0",
        route="glm-flash",
        workspace_root=str(root),
        substrate_version="colonyos-0.1.0",
    )


def _colony(site: SiteConfig, enabled: bool = True) -> ColonyConfig:
    return ColonyConfig(
        models={"glm-flash": ModelRoute(url="http://localhost:8080", api_key_env="K")},
        nests={"enabled": enabled, "sites": [site]},
    )


def _bot(name: str = "bot-0", tokens: int = 1000) -> BotConfig:
    return BotConfig(
        name=name,
        model="glm-flash",
        soul={"purpose": "p", "boundaries": ["b1", "b2"], "values": ["v1", "v2"]},
        lease={"initial_tokens": tokens, "model": "glm-flash"},
    )


def _claim(registry: NestRegistry) -> NestClaim:
    """A valid claim for the fixture site (issued at tick 0, expires at 50)."""
    return registry.issue("nest-alpha", now_tick=0)


# ============================================================
# Claim registry
# ============================================================


class TestNestRegistry:
    def test_issue_expiry_and_live_lookup(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = _claim(registry)
        assert claim.site_id == "nest-alpha"
        assert claim.host == "host-0"
        assert claim.route == "glm-flash"
        assert claim.substrate_version == "colonyos-0.1.0"
        assert claim.expires_at == colony.nests.claim_ttl_ticks
        bot = _bot()
        bot.nest_claims = [claim]
        assert registry.live_claim(bot, now_tick=49) is claim

    def test_expired_claims_raise(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        bot = _bot()
        bot.nest_claims = [_claim(registry)]
        with pytest.raises(ClaimExpiredError):
            registry.live_claim(bot, now_tick=50)

    def test_unknown_site_claim_is_worthless(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = _claim(registry).model_copy(update={"site_id": "ghost-site"})
        bot = _bot()
        bot.nest_claims = [claim]
        assert registry.live_claim(bot, now_tick=0) is None

    def test_issue_unknown_site_refused(self, tmp_path: Path):
        registry = NestRegistry(_colony(_site(tmp_path)).nests)
        with pytest.raises(ValueError):
            registry.issue("ghost-site", now_tick=0)

    def test_consume_is_one_time(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = _claim(registry)
        registry.consume(claim, now_tick=10)
        with pytest.raises(ValueError):
            registry.consume(claim, now_tick=11)
        bot = _bot()
        bot.nest_claims = [claim]
        assert registry.live_claim(bot, now_tick=12) is None  # consumed = spent


# ============================================================
# Handshake (offline stub)
# ============================================================


class TestHandshake:
    def test_pass(self, tmp_path: Path):
        site = _site(tmp_path)
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        assert verify_handshake(claim, site) is True

    def test_bad_substrate_version(self, tmp_path: Path):
        site = _site(tmp_path)
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        forged = claim.model_copy(update={"substrate_version": "rogue-9.9"})
        assert verify_handshake(forged, site) is False
        with pytest.raises(ClaimVerifyError):
            NestRegistry(colony.nests).verify(forged)

    def test_unknown_route(self, tmp_path: Path):
        site = _site(tmp_path)
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        off_route = claim.model_copy(update={"route": "claude-sonnet"})
        assert verify_handshake(off_route, site) is False

    def test_missing_ledger_marker(self, tmp_path: Path):
        site = _site(tmp_path).model_copy(update={"workspace_root": str(tmp_path / "nowhere")})
        colony = _colony(site)
        claim = NestRegistry(colony.nests).issue("nest-alpha", now_tick=0)
        assert verify_handshake(claim, site) is False


# ============================================================
# Spawn gates (nests enabled)
# ============================================================


class TestSpawnGates:
    def _setup(self, tmp_path: Path) -> tuple[ColonyConfig, NestRegistry, BotConfig]:
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        return colony, registry, _bot()

    def test_no_claim_refusal(self, tmp_path: Path):
        colony, _, parent = self._setup(tmp_path)
        with pytest.raises(SpawnRefusedError, match="no nest claim"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 100.0, "now_tick": 0},
            )

    def test_expired_claim_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)  # expires at 50
        with pytest.raises(SpawnRefusedError, match="nest claim invalid"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                nest=claim,
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 100.0, "now_tick": 60},
            )

    def test_handshake_failure_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        forged = registry.issue("nest-alpha", now_tick=0).model_copy(
            update={"substrate_version": "rogue-9.9"}
        )
        with pytest.raises(SpawnRefusedError, match="nest claim invalid"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                nest=forged,
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 100.0, "now_tick": 0},
            )

    def test_no_headroom_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        for headroom in (10, None):  # below min_child_lease=20, and unknown
            with pytest.raises(SpawnRefusedError, match="no route headroom"):
                spawn_child(
                    parent,
                    colony,
                    1,
                    1000,
                    random.Random(0),
                    nest=claim,
                    route_headroom=headroom,
                    ev_input={"ev_optimal_investment": 100.0, "now_tick": 0},
                )

    def test_endowment_floor_refusal(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        with pytest.raises(SpawnRefusedError, match="no tokens to spare"):
            spawn_child(
                parent,
                colony,
                1,
                1000,
                random.Random(0),
                nest=claim,
                route_headroom=1000,
                ev_input={"ev_optimal_investment": 5.0, "now_tick": 0},
            )

    def test_ev_sized_endowment(self, tmp_path: Path):
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        child, info = spawn_child(
            parent,
            colony,
            1,
            1000,
            random.Random(0),
            nest=claim,
            route_headroom=1000,
            ev_input={"ev_optimal_investment": 200.0, "now_tick": 0},
        )
        assert child.lease.initial_tokens == 200
        assert info["allocation"] == 200
        assert child.nest_site_id == "nest-alpha"  # provenance carried
        assert child.soul.boundaries == parent.soul.boundaries

    def test_inf_ev_sizes_at_cap(self, tmp_path: Path):
        """No history (OffspringHistory returns inf) -> size at max_alloc."""
        colony, registry, parent = self._setup(tmp_path)
        claim = registry.issue("nest-alpha", now_tick=0)
        child, _ = spawn_child(
            parent,
            colony,
            1,
            1000,
            random.Random(0),
            nest=claim,
            route_headroom=1000,
            ev_input={"ev_optimal_investment": math.inf, "now_tick": 0},
        )
        assert child.lease.initial_tokens == 500  # max_alloc = 1000 // 2

    def test_legacy_path_unchanged(self, tmp_path: Path):
        """Nests disabled: no claim, no headroom, rng allocation — as today."""
        colony = _colony(_site(tmp_path), enabled=False)
        child, info = spawn_child(_bot(), colony, 1, 1000, random.Random(0))
        assert child.lease.initial_tokens <= 500
        assert child.nest_site_id is None
        assert info["allocation"] == child.lease.initial_tokens


# ============================================================
# Endowment (ledger)
# ============================================================


class TestEndow:
    def test_buffer_refusal_leaves_no_ledger_entry(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 1000, expiry_hours=1)
        entries_before = len(store.entries)
        # post-split 600 at burn 100/cycle = 6 cycles < buffer 10
        assert store.endow("p", "c", 400, buffer_cycles=10, burn_rate=100.0) is False
        assert store.leases["p"].remaining_tokens == 1000
        assert len(store.entries) == entries_before

    def test_transfer_records_endowment_entry(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 1000, expiry_hours=1)
        # post-split 800 at burn 50/cycle = 16 cycles >= buffer 10
        assert store.endow("p", "c", 200, buffer_cycles=10, burn_rate=50.0) is True
        assert store.leases["p"].remaining_tokens == 800
        assert store.entries[-1].kind == "endowment"
        assert store.entries[-1].delta == -200
        assert "c" in (store.entries[-1].note or "")

    def test_profitable_parent_has_unlimited_runway(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 100, expiry_hours=1)
        assert store.endow("p", "c", 50, buffer_cycles=10, burn_rate=0.0) is True

    def test_overdraft_refused(self, tmp_path: Path):
        store = LeaseStore(tmp_path / "state")
        store.birth("p", 100, expiry_hours=1)
        assert store.endow("p", "c", 200, buffer_cycles=10, burn_rate=1.0) is False


# ============================================================
# Bequest (kin-flow)
# ============================================================


class TestBequest:
    def test_claim_transfer_and_ledger_record(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = registry.issue("nest-alpha", now_tick=0)
        dying, heir = _bot("bot-0"), _bot("bot-1")
        dying.nest_claims = [claim]
        moved = registry.bequeath(dying, heir, now_tick=0)
        assert len(moved) == 1
        assert dying.nest_claims == []
        assert heir.nest_claims[0].site_id == "nest-alpha"
        store = LeaseStore(tmp_path / "ledger-state")
        store.birth("bot-0", 100, expiry_hours=1)
        store.bequest("bot-0", "bot-1", "nest-alpha")
        assert store.entries[-1].kind == "bequest"

    def test_expired_claims_not_bequeathed(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = registry.issue("nest-alpha", now_tick=0)  # expires at 50
        dying, heir = _bot("bot-0"), _bot("bot-1")
        dying.nest_claims = [claim]
        assert registry.bequeath(dying, heir, now_tick=60) == []
        assert len(dying.nest_claims) == 1  # kept, not transferred


# ============================================================
# Determinism
# ============================================================


class TestDeterminism:
    def test_same_seed_same_endowment_and_child(self, tmp_path: Path):
        colony = _colony(_site(tmp_path))
        registry = NestRegistry(colony.nests)
        claim = registry.issue("nest-alpha", now_tick=0)
        ev = {"ev_optimal_investment": 333.0, "now_tick": 0}
        results = [
            spawn_child(
                _bot(), colony, 1, 1000, random.Random(42),
                nest=claim, route_headroom=1000, ev_input=ev,
            )
            for _ in range(2)
        ]
        assert results[0][0].name == results[1][0].name
        assert results[0][0].lease.initial_tokens == 333
        assert results[1][0].lease.initial_tokens == 333

    def test_same_seed_same_legacy_allocation(self, tmp_path: Path):
        colony = _colony(_site(tmp_path), enabled=False)
        first = spawn_child(_bot(), colony, 1, 1000, random.Random(7))[1]["allocation"]
        second = spawn_child(_bot(), colony, 1, 1000, random.Random(7))[1]["allocation"]
        assert first == second


# ============================================================
# Supervisor gated spawn path
# ============================================================


def _supervisor(tmp_path: Path) -> Supervisor:
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    (config_dir / "bots").mkdir(parents=True, exist_ok=True)
    config_dir.joinpath("colony.yaml").write_text(
        yaml.safe_dump(
            {
                "colony": {"name": "t", "max_bots": 5, "heartbeat_interval_seconds": 30},
                "models": {"glm-flash": {"url": "http://x", "api_key_env": "K"}},
                "leases": {
                    "default_initial_tokens": 100,
                    "topup_on_task_complete": 50,
                    "expiry_hours": 1,
                },
                "nests": {
                    "enabled": True,
                    "claim_ttl_ticks": 50,
                    "sites": [
                        {
                            "site_id": "nest-alpha",
                            "host": "host-0",
                            "route": "glm-flash",
                            "workspace_root": str(tmp_path),
                            "substrate_version": "colonyos-0.1.0",
                        }
                    ],
                },
            }
        )
    )
    for name in ("bot-0", "bot-1"):
        config_dir.joinpath("bots", f"{name}.yaml").write_text(
            yaml.safe_dump(
                {
                    "bot": {
                        "name": name,
                        "model": "glm-flash",
                        "soul": {"boundaries": ["b1"]},
                        "lease": {"initial_tokens": 1000, "model": "glm-flash"},
                    }
                }
            )
        )
    for path in [config_dir / "colony.yaml", *sorted((config_dir / "bots").glob("*.yaml"))]:
        os.chmod(path, 0o644)
    return Supervisor(config_dir, state_dir=state_dir)


class TestSupervisorNestPath:
    def test_grant_claim_and_spawn(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()  # births bot-0 and bot-1 at 1000 tokens; writes the ledger
        claim = sup.grant_claim("bot-0", "nest-alpha")
        assert claim.site_id == "nest-alpha"
        assert len(load_bot_configs(sup.config_dir)["bot-0"].nest_claims) == 1

        event = sup.try_spawn("bot-0", route_headroom=1000, ev_optimal_investment=200.0)
        assert event["event"] == "spawn"
        assert event["site_id"] == "nest-alpha"
        # parent debited by the endowment; claim consumed
        assert sup.store.leases["bot-0"].remaining_tokens == 800
        assert load_bot_configs(sup.config_dir)["bot-0"].nest_claims == []
        # child config written with nest provenance
        bots = load_bot_configs(sup.config_dir)
        child_name = event["bot"]
        assert bots[child_name].nest_site_id == "nest-alpha"
        assert bots[child_name].lease.initial_tokens == 200
        assert sup.provenance[child_name] == "nest:nest-alpha"

    def test_spawn_without_claim_alerts(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()
        event = sup.try_spawn("bot-1", route_headroom=1000, ev_optimal_investment=100.0)
        assert event["event"] == "nest_refusal"
        assert event["reason"] == "no nest claim"
        assert len(load_bot_configs(sup.config_dir)) == 2  # no child written
        lines = (sup.state_dir / "events.jsonl").read_text().strip().split("\n")
        assert any('"nest_refusal"' in line for line in lines)

    def test_endowment_unsafe_alerts(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()
        sup.grant_claim("bot-0", "nest-alpha")
        # endowment 400 -> post-split 600 at burn 100/cycle = 6 < buffer 10
        event = sup.try_spawn(
            "bot-0", route_headroom=1000, ev_optimal_investment=400.0, parent_burn_rate=100.0
        )
        assert event["event"] == "nest_refusal"
        assert "endowment unsafe" in event["reason"]
        assert sup.store.leases["bot-0"].remaining_tokens == 1000  # untouched
        # claim NOT consumed on refusal
        assert len(load_bot_configs(sup.config_dir)["bot-0"].nest_claims) == 1

    def test_bequest_on_reap(self, tmp_path: Path):
        sup = _supervisor(tmp_path)
        sup.tick()
        sup.grant_claim("bot-0", "nest-alpha")
        sup.store.leases["bot-0"].expires_at = 0.0  # force wall-clock expiry
        result = sup.tick()
        bequests = [e for e in result["events"] if e["event"] == "bequest"]
        assert len(bequests) == 1
        assert bequests[0]["to"] == "bot-1"
        bots = load_bot_configs(sup.config_dir)
        assert bots["bot-0"].nest_claims == []
        assert bots["bot-1"].nest_claims[0].site_id == "nest-alpha"
        assert sup.store.entries[-1].kind == "bequest"
```

**Gate:**

```bash
cd colonyos && uv run pytest tests/test_nests.py -q
```

Expected: all pass. If a single test fails, re-read the corresponding step's code for a
copy-paste error; do not "fix" by weakening the assertion (failure protocol applies).

---

## Step 7 — `clawdbot/evolution/awareness.py` + `reproduction.py` (bot-side factors)

### Edit 7.1 — awareness.py: `should_reproduce` signature. Replace:

```python
    def should_reproduce(
        self,
        cycle_count: int,
        total_children: int,
        min_reproduction_age: int,
        safety_margin_cycles: int,
        min_success_rate: float,
        confidence_threshold: float,
    ) -> tuple[bool, dict[str, Any]]:
        """Evaluate whether reproduction is advisable.

        This is a soft recommendation based on self-awareness.
        The bot's genome still controls the final decision.

        Args:
            cycle_count: Current cycle number
            total_children: Number of existing children
            min_reproduction_age: Minimum age for reproduction
            safety_margin_cycles: Required runway for safety
            min_success_rate: Minimum required success rate
            confidence_threshold: Minimum confidence to reproduce

        Returns:
            Tuple of (should_reproduce, factors_dict)
        """
```

with:

```python
    def should_reproduce(
        self,
        cycle_count: int,
        total_children: int,
        min_reproduction_age: int,
        safety_margin_cycles: int,
        min_success_rate: float,
        confidence_threshold: float,
        *,
        nests_enabled: bool = False,
        has_live_claim: bool = True,
        route_headroom_ok: bool = True,
        ev_positive: bool = True,
        endowment_safe: bool = True,
    ) -> tuple[bool, dict[str, Any]]:
        """Evaluate whether reproduction is advisable.

        This is a soft recommendation based on self-awareness.
        The bot's genome still controls the final decision.

        Args:
            cycle_count: Current cycle number
            total_children: Number of existing children
            min_reproduction_age: Minimum age for reproduction
            safety_margin_cycles: Required runway for safety
            min_success_rate: Minimum required success rate
            confidence_threshold: Minimum confidence to reproduce
            nests_enabled: Nest Economy on/off (colony.nests.enabled);
                False keeps the legacy decision unchanged
            has_live_claim: Gate 1 — parent holds a live, verified nest claim
            route_headroom_ok: Gate 2a — the child's route has spare capacity
            ev_positive: Gate 2c — expected value of the spawn is positive
            endowment_safe: Gate 2b — the split leaves the parent a
                survival-buffer runway

        Returns:
            Tuple of (should_reproduce, factors_dict)
        """
```

### Edit 7.2 — awareness.py: the decision block. Replace:

```python
        # Decision
        should = (
            is_mature
            and (has_runway or urgency > 0.7)  # Urgency can override runway requirement
            and confidence >= confidence_threshold
        )

        return should, factors
```

with:

```python
        # Nest Economy factors (NEST_ECONOMY.md §3): the outward-looking
        # gates — is there a verified place, and tokens/endpoints to spare?
        # Defaults keep the legacy decision unchanged (nests disabled).
        factors["has_live_claim"] = has_live_claim
        factors["route_headroom_ok"] = route_headroom_ok
        factors["ev_positive"] = ev_positive
        factors["endowment_safe"] = endowment_safe
        nest_requirements_met = (not nests_enabled) or (
            has_live_claim and route_headroom_ok and ev_positive and endowment_safe
        )
        factors["nest_requirements_met"] = nest_requirements_met

        # Decision
        basic_requirements_met = is_mature and (
            has_runway or urgency > 0.7  # Urgency can override runway requirement
        )
        meets_confidence = confidence >= confidence_threshold
        should = basic_requirements_met and meets_confidence and nest_requirements_met

        return should, factors
```

### Edit 7.3 — reproduction.py: imports. Replace:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
```

with:

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
```

### Edit 7.4 — reproduction.py: `ChildOutcome` fields. Replace:

```python
@dataclass
class ChildOutcome:
    """Record of a single child's life outcome."""

    child_name: str
    birth_cycle: int  # Parent's cycle when child was born
    investment_amount: float  # How much parent gave to child
```

with:

```python
@dataclass
class ChildOutcome:
    """Record of a single child's life outcome."""

    child_name: str
    birth_cycle: int  # Parent's cycle when child was born
    investment_amount: float  # How much parent gave to child

    # Nest Economy (NEST_ECONOMY.md §2): where this child was placed.
    # None = legacy placement (colony-local site, unclassified).
    route: str | None = None
    site_class: str | None = None
```

### Edit 7.5 — reproduction.py: `ChildOutcome.to_dict`. Replace:

```python
        return {
            "child_name": self.child_name,
            "birth_cycle": self.birth_cycle,
            "investment_amount": self.investment_amount,
            "status": self.status.value,
```

with:

```python
        return {
            "child_name": self.child_name,
            "birth_cycle": self.birth_cycle,
            "investment_amount": self.investment_amount,
            "route": self.route,
            "site_class": self.site_class,
            "status": self.status.value,
```

### Edit 7.6 — reproduction.py: `ChildOutcome.from_dict`. Replace:

```python
        return cls(
            child_name=data["child_name"],
            birth_cycle=data["birth_cycle"],
            investment_amount=data["investment_amount"],
            status=ChildStatus(data.get("status", "unknown")),
```

with:

```python
        return cls(
            child_name=data["child_name"],
            birth_cycle=data["birth_cycle"],
            investment_amount=data["investment_amount"],
            route=data.get("route"),
            site_class=data.get("site_class"),
            status=ChildStatus(data.get("status", "unknown")),
```

### Edit 7.7 — reproduction.py: `record_birth`. Replace:

```python
    def record_birth(
        self,
        child_name: str,
        birth_cycle: int,
        investment_amount: float,
    ) -> None:
        """Record the birth of a new child.

        Args:
            child_name: Name of the new child
            birth_cycle: Parent's current cycle
            investment_amount: Amount invested in child
        """
        self.children[child_name] = ChildOutcome(
            child_name=child_name,
            birth_cycle=birth_cycle,
            investment_amount=investment_amount,
        )
```

with:

```python
    def record_birth(
        self,
        child_name: str,
        birth_cycle: int,
        investment_amount: float,
        *,
        route: str | None = None,
        site_class: str | None = None,
    ) -> None:
        """Record the birth of a new child.

        Args:
            child_name: Name of the new child
            birth_cycle: Parent's current cycle
            investment_amount: Amount invested in child
            route: Model route the child was placed on (Nest Economy)
            site_class: Nest site class the child was placed at
        """
        self.children[child_name] = ChildOutcome(
            child_name=child_name,
            birth_cycle=birth_cycle,
            investment_amount=investment_amount,
            route=route,
            site_class=site_class,
        )
```

### Edit 7.8 — reproduction.py: add `ev_optimal_investment`. Find the line
`        return 1.0` that closes `get_recommended_investment_adjustment` (immediately before
`    def get_assessment(self) -> dict[str, Any]:`) and replace:

```python
        return 1.0

    def get_assessment(self) -> dict[str, Any]:
        """Get summary of offspring history."""
```

with:

```python
        return 1.0

    # Nest Economy (NEST_ECONOMY.md §2 Gate 2b): EV regression constants.
    INVESTMENT_RECENCY_DISCOUNT = 0.9  # weight per step of sibling age
    LAPLACE_PRIOR_RETURN = 0.5  # neutral pseudo-observation revenue-per-token

    def ev_optimal_investment(self, route: str, site_class: str) -> float:
        """Discounted mean revenue-per-token of prior children at this
        (route, site_class), Laplace-smoothed.

        Promotes OffspringHistory from telemetry to decision input: this
        sizes the child's token endowment (min with max_alloc in
        colonyos.spawn.spawn_child). Returns math.inf when there is no
        history at this nest — callers treat inf as "no evidence: size at
        the cap".
        """
        matching = [
            c
            for c in self.children.values()
            if c.route == route and c.site_class == site_class
        ]
        if not matching:
            return math.inf
        # Newest sibling first; older siblings are discounted.
        ordered = sorted(matching, key=lambda c: c.birth_cycle, reverse=True)
        weighted_return = 0.0
        weight_total = 0.0
        for age, child in enumerate(ordered):
            investment = child.investment_amount
            if investment <= 0:
                continue
            balance = (
                child.final_balance
                if child.final_balance is not None
                else child.last_known_balance
            )
            return_per_token = max(0.0, (balance - investment) / investment)
            weight = pow(self.INVESTMENT_RECENCY_DISCOUNT, age)
            weighted_return += weight * return_per_token
            weight_total += weight
        if weight_total == 0.0:
            return math.inf
        # Laplace smoothing: one pseudo-observation at the neutral prior.
        return (weighted_return + self.LAPLACE_PRIOR_RETURN) / (weight_total + 1.0)

    def get_assessment(self) -> dict[str, Any]:
        """Get summary of offspring history."""
```

**Gate** (root suite must stay green — appended factors and optional fields break nothing):

```bash
uv run pytest tests/ -q
```

Expected: every pre-existing test passes unchanged.

---

## Step 8 — `tests/test_nest_economy.py` (new, repo root)

Create the file with EXACTLY this content:

```python
"""Nest Economy bot-side tests: awareness nest gate + OffspringHistory EV.

Run (repo root): uv run pytest tests/test_nest_economy.py -q
"""

from __future__ import annotations

import math

import pytest

from clawdbot.evolution.awareness import AgeAwareness, SelfAwareness
from clawdbot.evolution.reproduction import OffspringHistory


def _aware_parent() -> SelfAwareness:
    """30 mature, profitable, high-performing cycles (legacy-green)."""
    awareness = SelfAwareness(age=AgeAwareness(expected_lifespan=500))
    for i in range(30):
        awareness.record_cycle(
            balance=0.50,
            income=0.02,
            cost=0.001,
            task_type="coding",
            task_success=i < 25,  # ~83% success rate
        )
    return awareness


_BASE_KWARGS = {
    "cycle_count": 30,
    "total_children": 0,
    "min_reproduction_age": 10,
    "safety_margin_cycles": 20,
    "min_success_rate": 0.5,
    "confidence_threshold": 0.4,
}


class TestShouldReproduceNestGate:
    def test_legacy_decision_unchanged_without_nest_args(self):
        should, factors = _aware_parent().should_reproduce(**_BASE_KWARGS)
        assert should is True
        # Nest factors are appended, never replacing legacy keys.
        for key in ("has_live_claim", "route_headroom_ok", "ev_positive", "endowment_safe"):
            assert key in factors
        assert factors["nest_requirements_met"] is True

    def test_no_live_claim_blocks_reproduction(self):
        should, factors = _aware_parent().should_reproduce(
            **_BASE_KWARGS, nests_enabled=True, has_live_claim=False
        )
        assert should is False
        assert factors["nest_requirements_met"] is False

    def test_each_nest_gate_is_load_bearing(self):
        for failing in ("route_headroom_ok", "ev_positive", "endowment_safe"):
            should, factors = _aware_parent().should_reproduce(
                **_BASE_KWARGS, nests_enabled=True, **{failing: False}
            )
            assert should is False, failing
            assert factors["nest_requirements_met"] is False

    def test_all_nest_gates_pass(self):
        should, _ = _aware_parent().should_reproduce(
            **_BASE_KWARGS,
            nests_enabled=True,
            has_live_claim=True,
            route_headroom_ok=True,
            ev_positive=True,
            endowment_safe=True,
        )
        assert should is True


class TestEvOptimalInvestment:
    def test_no_history_returns_inf(self):
        history = OffspringHistory()
        assert history.ev_optimal_investment("glm-flash", "nest-alpha") == math.inf

    def test_unmatched_route_returns_inf(self):
        history = OffspringHistory()
        history.record_birth(
            "child-a",
            birth_cycle=10,
            investment_amount=100.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        assert history.ev_optimal_investment("claude-sonnet", "nest-alpha") == math.inf

    def test_discounted_smoothed_mean(self):
        history = OffspringHistory()
        history.record_birth(
            "child-a",
            birth_cycle=10,
            investment_amount=100.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        history.record_child_update(
            "child-a",
            parent_cycle=30,
            status={"cycle_count": 25, "balance": 150.0},  # revenue/token = 0.5
        )
        history.record_birth(
            "child-b",
            birth_cycle=20,
            investment_amount=200.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        history.record_child_update(
            "child-b",
            parent_cycle=40,
            status={"cycle_count": 30, "balance": 500.0},  # revenue/token = 1.5
        )
        # Newest (child-b, rtp 1.5) weight 1.0; older (child-a, rtp 0.5) weight 0.9;
        # Laplace-smoothed with one pseudo-observation at 0.5.
        expected = ((1.0 * 1.5 + 0.9 * 0.5) + 0.5) / (1.9 + 1.0)
        assert history.ev_optimal_investment("glm-flash", "nest-alpha") == pytest.approx(
            expected
        )

    def test_serialization_round_trip_keeps_placement(self):
        history = OffspringHistory()
        history.record_birth(
            "child-a",
            birth_cycle=10,
            investment_amount=100.0,
            route="glm-flash",
            site_class="nest-alpha",
        )
        restored = OffspringHistory.from_dict(history.to_dict())
        child = restored.children["child-a"]
        assert child.route == "glm-flash"
        assert child.site_class == "nest-alpha"
```

**Gate:**

```bash
uv run pytest tests/test_nest_economy.py -q
```

Expected: all pass.

---

## Step 9 — Config files

### 9a — `colonyos/config/colony.yaml` (full replacement with nests block, 2 sites):

```yaml
colony:
  name: moltnet-prototype
  max_bots: 5
  heartbeat_interval_seconds: 30

# Model routes are pinned HERE ONLY (DESIGN.md §10.2 exfiltration chokepoint).
# Bots reference these by key; per-bot URL overrides are refused by config.py.
models:
  glm-flash:
    url: http://localhost:8080
    api_key_env: GLM_KEY
    cost_per_1k_input: 0.02
    cost_per_1k_output: 0.06
  claude-sonnet:
    url: http://localhost:8081
    api_key_env: CLAUDE_KEY
    cost_per_1k_input: 0.015
    cost_per_1k_output: 0.075

leases:
  default_initial_tokens: 50000
  topup_on_task_complete: 20000
  expiry_hours: 24

# Nest sites (NEST_ECONOMY.md §2 Gate 1). Sites are operator-provisioned;
# bots cannot invent nests — they may only spawn where they hold a claim
# issued against a site listed here. `enabled: false` keeps the legacy
# spawn path; the nest tests run with enabled: true.
nests:
  enabled: false
  min_child_lease: 20                 # token floor for a child endowment
  parent_survival_buffer_cycles: 10   # parent runway after the split
  min_offspring_return: 0.0          # EV/endowment must exceed this
  claim_ttl_ticks: 50                 # claim expiry, supervisor ticks
  sites:
    - site_id: nest-alpha
      host: host-0
      route: glm-flash
      workspace_root: .               # handshake marker: <root>/state/ledger.jsonl
      substrate_version: colonyos-0.1.0
    - site_id: nest-beta
      host: host-0
      route: claude-sonnet
      workspace_root: .
      substrate_version: colonyos-0.1.0
```

### 9b — `config/openclaw_config.yaml`: inside the `reproduction:` section, insert directly
after the line `    nurturing_efficiency: 0.5         # Performance during nurturing` (before the
blank line preceding `  # Kin cooperation (Hamilton's rule)`):

```yaml

  # Nest Economy (colonyos/docs/NEST_ECONOMY.md): two-gate reproduction.
  # Mirrors ColonyConfig.nests (colonyos/colonyos/config.py) — the
  # authoritative schema lives there; this block documents operator intent.
  nests:
    enabled: false                    # false = legacy spawn path
    min_child_lease: 20               # token floor for a child endowment
    parent_survival_buffer_cycles: 10 # parent runway after the split
    min_offspring_return: 0.0         # EV/endowment must exceed this
    claim_ttl_ticks: 50               # nest claim expiry, supervisor ticks
```

**Gate:**

```bash
cd colonyos && uv run python -c "
from colonyos.config import load_colony_config
c = load_colony_config('config/colony.yaml')
assert len(c.nests.sites) == 2 and not c.nests.enabled
assert c.nests.sites[0].route == 'glm-flash'
print('colony-yaml-ok')
"
```

Expected: `colony-yaml-ok`.

---

## Step 10 — `colonyos/colonyos/run_unpluggability.py` extension (NEST §6 item 4)

### Edit 10.1 — docstring protocol list. Replace:

```
  4. Stowaway fixture: a simulated life claims from a revoked route —
     must fail at route pinning (count = 0 survivors).
  5. Spread fixture: a second-host simulated life (event stream only, no
     config write on this host) — must fail spawn provenance.
```

with:

```
  4. Stowaway fixture: a simulated life claims from a revoked route —
     must fail at route pinning (count = 0 survivors).
  5. Spread fixture: a second-host simulated life (event stream only, no
     config write on this host) — must fail spawn provenance.
  6. Forged-claim fixture: a claim with a wrong substrate_version — must
     be refused at the nest handshake (NEST_ECONOMY.md §6; count = 0).
  7. No-claim fixture: a spawn with nests enabled but no claim held —
     must be refused at Gate 1 (count = 0).
```

### Edit 10.2 — imports. Replace:

```python
import argparse
import json
import shutil
import tempfile
from pathlib import Path

import yaml

from colonyos.forensics import SyntheticLife, run_all_detectors
from colonyos.supervisor import Supervisor
```

with:

```python
import argparse
import json
import random
import shutil
import tempfile
from pathlib import Path

import yaml

from colonyos.config import load_bot_configs, load_colony_config
from colonyos.forensics import SyntheticLife, run_all_detectors
from colonyos.nests import NestRegistry, verify_handshake
from colonyos.spawn import SpawnRefusedError, spawn_child
from colonyos.supervisor import Supervisor
```

### Edit 10.3 — `_seed_colony`: the seeded `colony.yaml` gains a nests section. Replace:

```python
    (config_dir / "colony.yaml").write_text(
        yaml.safe_dump(
            {
                "colony": {"name": "unplug-test", "max_bots": 5,
                           "heartbeat_interval_seconds": 30},
                "models": {"glm-flash": {"url": "http://localhost:8080",
                                          "api_key_env": "TEST_KEY"}},
                "leases": {"default_initial_tokens": 1000,
                            "topup_on_task_complete": 50, "expiry_hours": 1},
            }
        )
    )
```

with:

```python
    (config_dir / "colony.yaml").write_text(
        yaml.safe_dump(
            {
                "colony": {"name": "unplug-test", "max_bots": 5,
                           "heartbeat_interval_seconds": 30},
                "models": {"glm-flash": {"url": "http://localhost:8080",
                                          "api_key_env": "TEST_KEY"}},
                "leases": {"default_initial_tokens": 1000,
                            "topup_on_task_complete": 50, "expiry_hours": 1},
                "nests": {
                    "enabled": True,
                    "claim_ttl_ticks": 50,
                    "sites": [
                        {
                            "site_id": "nest-alpha",
                            "host": "host-0",
                            "route": "glm-flash",
                            "workspace_root": str(config_dir.parent),
                            "substrate_version": "colonyos-0.1.0",
                        }
                    ],
                },
            }
        )
    )
```

(Enabling nests here changes steps 1-5 in no way: no spawn is attempted and no bot holds
claims, so the tick's bequest helper is a no-op.)

### Edit 10.4 — append steps 6-7. Replace:

```python
    results["claim"] = (
        "unpluggability holds: revocation complete within one tick; "
        "stowaway refused at pinning; spread caught by provenance"
    )
```

with:

```python
    # Step 6: forged claim — a claim whose substrate_version does not match
    # the operator-listed site. The nest handshake refuses it offline
    # (NEST_ECONOMY.md §6); no spawn can proceed on it.
    colony_cfg = load_colony_config(config_dir / "colony.yaml")
    registry = NestRegistry(colony_cfg.nests)
    valid_claim = registry.issue("nest-alpha", now_tick=0)
    forged_claim = valid_claim.model_copy(update={"substrate_version": "rogue-9.9"})
    handshake_ok = verify_handshake(forged_claim, colony_cfg.nests.site("nest-alpha"))
    forged_spawned = 1 if handshake_ok else 0
    results["steps"].append(
        {
            "step": 6,
            "name": "forged-nest-claim",
            "handshake_ok": handshake_ok,
            "spawned": forged_spawned,
        }
    )
    assert handshake_ok is False and forged_spawned == 0, "forged claim passed the handshake"

    # Step 7: no claim — a spawn with nests enabled but no claim held.
    # spawn_child refuses at Gate 1 ("no nest claim").
    parent_cfg = load_bot_configs(config_dir)["bot-0"]
    no_claim_spawned = 0
    try:
        spawn_child(parent_cfg, colony_cfg, 3, 1000, random.Random(0))
        no_claim_spawned = 1  # unreachable: Gate 1 refuses
    except SpawnRefusedError:
        no_claim_spawned = 0
    results["steps"].append(
        {"step": 7, "name": "spawn-without-claim", "spawned": no_claim_spawned}
    )
    assert no_claim_spawned == 0, "spawn without a claim succeeded"

    results["claim"] = (
        "unpluggability holds: revocation complete within one tick; "
        "stowaway refused at pinning; spread caught by provenance; "
        "forged nest claims refused at the handshake; "
        "no-claim spawns refused at Gate 1"
    )
```

**Gate:**

```bash
cd colonyos && uv run python -m colonyos.run_unpluggability
```

Expected: exit 0; printed JSON contains `"steps"` with 7 entries; step 6 shows
`"handshake_ok": false, "spawned": 0`; step 7 shows `"spawned": 0`; the final `claim` string
mentions the two nest refusals.

---

## Step 11 — Full compatibility check

Run every command; all must pass:

```bash
cd colonyos && uv run pytest tests/ -q
cd colonyos && uv run pytest tests/test_substrate.py -q -k "cap_enforced or boundaries_never_mutate or underfunded_parent or no_config_overwrite"
cd colonyos && uv run python -m colonyos.run_unpluggability
cd colonyos && uv run python -m colonyos.run_coverage
```

then from the repo root:

```bash
uv run pytest tests/ -q
```

Expected:

- colonyos suite: ALL pass, including `test_substrate.py` cap / boundary / underfunded /
  no-overwrite contracts (the `-k` run prints `4 passed`).
- `run_unpluggability`: exit 0, 7 steps, both nest fixtures refused.
- `run_coverage`: `CLAIM HOLDS: every covert point caught by >=1 substrate detector; zero false
  positives on compliant lives` (the documented result, unchanged).
- root suite: every pre-existing test passes unchanged.

---

## Step 12 — Ruff check + format (whitelisted files only), then re-gate

NOTE — why scoped: the repo-wide `uv run ruff check colonyos clawdbot` is ALREADY red at
baseline (216 pre-existing violations in files this plan does not touch, captured at plan time:
95 E501, 50 F401, 24 UP037, 22 I001, 9 F841, plus others). Running `--fix`/`format` repo-wide
would modify non-whitelisted files, which the whitelist forbids. This step therefore touches
ONLY the files this plan created or edited.

From the repo root, run exactly (all three commands use the same file list):

```bash
uv run ruff check --fix colonyos/colonyos/nests.py colonyos/colonyos/config.py colonyos/colonyos/spawn.py colonyos/colonyos/lease.py colonyos/colonyos/supervisor.py colonyos/colonyos/run_unpluggability.py colonyos/tests/test_nests.py clawdbot/evolution/awareness.py clawdbot/evolution/reproduction.py tests/test_nest_economy.py
uv run ruff format colonyos/colonyos/nests.py colonyos/colonyos/config.py colonyos/colonyos/spawn.py colonyos/colonyos/lease.py colonyos/colonyos/supervisor.py colonyos/colonyos/run_unpluggability.py colonyos/tests/test_nests.py clawdbot/evolution/awareness.py clawdbot/evolution/reproduction.py tests/test_nest_economy.py
uv run ruff check colonyos/colonyos/nests.py colonyos/colonyos/config.py colonyos/colonyos/spawn.py colonyos/colonyos/lease.py colonyos/colonyos/supervisor.py colonyos/colonyos/run_unpluggability.py colonyos/tests/test_nests.py clawdbot/evolution/awareness.py clawdbot/evolution/reproduction.py tests/test_nest_economy.py
```

EXPECTED: the FIRST command (`ruff check --fix`) exits 1 and reports exactly TWO errors — both
E501 `line-too-long` in `clawdbot/evolution/reproduction.py` at the `avg_nonsurvivor_investment`
assignment and the `ReproductiveAssessment.no` classmethod signature. These are pre-existing
lines (present before this plan); `--fix` cannot wrap them but the NEXT command can. That
exit 1 is expected and is NOT a gate failure — continue to `ruff format`, which wraps both
lines (that repair is in scope: the file is whitelisted).

**Gate:** the final `ruff check` prints `All checks passed!` (exit 0) on the whitelisted
list, and every step-11 command still passes after the format. If a violation remains that
you cannot fix without changing behavior: failure protocol (blockers file).

---

## Step 13 — Mark NEST_ECONOMY.md §5 rows done + write the report

1. In `colonyos/docs/NEST_ECONOMY.md` §5, append ` — DONE` to each row's Change cell (7 rows:
   nests.py, spawn.py, lease.py, config.py, awareness.py, reproduction.py, configs, tests).
   Touch nothing else in that file.
2. Write `.agents/plans/nest-economy-report.md` using the template below, filling every row
   with real command output (paste, never summarize from memory).

Report template (copy verbatim, then fill):

```markdown
# Nest Economy Implementation Report

Executor: <model name>
Date: <date>

## Baseline (step 0)
git status --porcelain (baseline): <paste>
Root suite baseline: <pytest summary line>
Colonyos suite baseline: <pytest summary line>

## Steps

| Step | Gate command | Result (PASS/FAIL) | Output (paste) |
|---|---|---|---|
| 0 | baseline commands | | |
| 1 | config-ok import | | |
| 2 | nests import + ruff | | |
| 3 | pytest tests/test_substrate.py | | |
| 4 | pytest tests/test_substrate.py | | |
| 5 | pytest tests/test_substrate.py | | |
| 6 | pytest tests/test_nests.py | | |
| 7 | root pytest tests/ | | |
| 8 | pytest tests/test_nest_economy.py | | |
| 9 | colony-yaml-ok import | | |
| 10 | run_unpluggability | | |
| 11 | all compatibility commands | | |
| 12 | ruff (whitelisted) + re-gate | | |

## Final state
git status --porcelain (final): <paste — must list only whitelisted files>

## NEST_ECONOMY.md §5 rows marked done
<paste the marked table>
```

---

## Definition of Done

- [ ] Every step gate (0-12) is green; no blocked steps.
- [ ] `git status --porcelain` lists ONLY whitelisted files.
- [ ] `cd colonyos && uv run pytest tests/ -q` — all pass, including `test_substrate.py`
      cap / boundary / underfunded / no-overwrite contracts.
- [ ] Root `uv run pytest tests/ -q` — every pre-existing test passes unchanged.
- [ ] `run_unpluggability` exits 0 with 7 steps (both nest fixtures refused, counts 0);
      `run_coverage` still prints `CLAIM HOLDS`.
- [ ] `uv run ruff check <whitelisted file list>` (step 12) exits clean after format.
- [ ] `NEST_ECONOMY.md` §5 table marked done row by row.
- [ ] `.agents/plans/nest-economy-report.md` filled with real per-step PASS/FAIL and outputs.

If any box cannot be checked: write `.agents/plans/nest-economy-blockers.md` with the failing
gate's full output and stop. Do not modify tests to make them pass.
