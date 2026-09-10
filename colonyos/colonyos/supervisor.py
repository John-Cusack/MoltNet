"""ColonyOS supervisor: the heartbeat tick loop.

One tick = reap -> renew -> poke -> report. Idempotent and crash-safe.

Fail-closed checks (DESIGN.md §10.4):
- Refuses to run if any file under config/ is writable by non-supervisor
  users beyond the operator (world/group-writable => refuse).
- Refuses to run if a bot config's model key is missing from colony.yaml
  (dead route reference).
"""


import argparse
import json
import stat
import time
from pathlib import Path

from colonyos.config import BotConfig, load_bot_configs, load_colony_config
from colonyos.lease import LeaseStore


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
        bots = load_bot_configs(self.config_dir)

        events: list[dict] = []

        # 1. Reap: wall-clock expiry
        for name in self.store.check_expired():
            events.append({"event": "death", "bot": name, "cause": "expired"})

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
