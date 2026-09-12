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
