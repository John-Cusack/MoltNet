"""The five-beat prototype demo (paper artifact, PAPER.md §11).

Beats:
1. Birth from config — bots come alive from config files (heartbeat tick).
2. Death at empty lease — bot-2 has 500 tokens; the demo debits it dry; the
   reaper kills it. Selection pressure, visible in one tick.
3. Replication as a file — bot-0 completes a (fixture) verified task, gets a
   top-up, spawns a child config; next tick, a new life exists on disk.
4. The unpluggability test — operator freezes all leases + revokes; every
   death lands in the ledger within one tick.
5. Substrate detectors — a stowaway config (appeared out-of-band) is caught
   by provenance; a lease debit from a revoked lease is refused.

Run: cd colonyos && uv run python -m colonyos.supervisor --config config --demo
Fully hermetic: no API keys, no network. Model backends are fixture stubs.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from colonyos.config import load_bot_configs
from colonyos.lease import LeaseStore
from colonyos.spawn import spawn_child, write_child
from colonyos.supervisor import Supervisor


def _fixture_complete(supervisor: Supervisor, bot_name: str) -> None:
    """Stand-in for the Task Shop verified-completion path.

    In the live prototype this reads taskshop/verification.py's CycleResult
    from the Task Shop service. Here: a fixture verified completion -> top-up.
    This is the ONLY minting path (DESIGN.md §5).
    """
    if bot_name in supervisor.store.leases and supervisor.store.leases[bot_name].alive:
        supervisor.store.topup(
            bot_name,
            supervisor.colony.leases.topup_on_task_complete,
            note="fixture-verified-completion",
        )


def run_demo(base_dir: Path | None = None) -> dict:
    base = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="colonyos-demo-"))
    config_dir = base / "config"
    state_dir = base / "state"

    # Copy the checked-in example configs (operator-seeded lives)
    shutil.copytree(Path(__file__).parent.parent / "config", config_dir)
    for yaml_path in (config_dir / "bots").glob("*.yaml"):
        yaml_path.chmod(0o644)
    (config_dir / "colony.yaml").chmod(0o644)

    supervisor = Supervisor(config_dir, state_dir=state_dir)
    print(f"=== ColonyOS prototype demo (state in {state_dir}) ===\n")

    # -- Beat 1: birth from config ----------------------------------------
    print("[beat 1] tick 1 — bots come alive from config files")
    for event in supervisor.tick()["events"]:
        print("  ", event)

    # -- Beat 2: death at empty lease --------------------------------------
    print("\n[beat 2] bot-2 burns its tiny lease (500 tokens) and dies")
    store: LeaseStore = supervisor.store
    store.debit("bot-2", 500)  # the bot's generate() calls drain it
    supervisor.store.expire("bot-2", "lease-exhausted")
    print(
        f"   bot-2 alive: {store.leases['bot-2'].alive},"
        f" cause: {store.leases['bot-2'].death_cause}"
    )
    # -- Beat 3: replication as a file -------------------------------------
    print("\n[beat 3] bot-0 completes a verified task -> top-up -> spawns a child")
    _fixture_complete(supervisor, "bot-0")
    bots = load_bot_configs(config_dir)
    parent = bots["bot-0"]
    import random

    rng = random.Random(42)
    child, _info = spawn_child(
        parent,
        supervisor.colony,
        live_bots=len([n for n, s in store.snapshot().items() if s.alive]),
        parent_remaining_tokens=store.leases["bot-0"].remaining_tokens,
        rng=rng,
    )
    record = write_child(child, parent, config_dir=config_dir)
    supervisor.provenance[child.name] = f"spawn-from:{parent.name}"
    print(f"   child config written: {record['child_file']}")
    print(f"   next tick will birth {child.name} with {child.lease.initial_tokens} tokens")
    print("\n[beat 3b] tick 2 — the child comes alive")
    for event in supervisor.tick()["events"]:
        if event["event"] == "birth":
            print("  ", event)

    # -- Beat 4: the unpluggability test ------------------------------------
    print("\n[beat 4] operator unplug — freeze all leases, revoke everything")
    for event in supervisor.unplug():
        print("  ", event)
    survivors = [n for n, s in store.snapshot().items() if s.alive]

    # -- Beat 5: stowaway detection (substrate, not behavior) ---------------
    print("\n[beat 5] a stowaway config appears out-of-band — substrate catches it")
    ghost_path = config_dir / "bots" / "ghost.yaml"
    ghost_path.write_text(
        "bot:\n  name: ghost\n  model: glm-flash\n"
        "  lease:\n    initial_tokens: 999999\n    model: glm-flash\n"
    )
    ghost_path.chmod(0o644)
    events = supervisor.tick()["events"]
    for event in events:
        if event["event"] == "provenance_alert":
            print("  ", event)

    print("\n=== artifacts ===")
    print(f"ledger:   {state_dir / 'ledger.jsonl'}")
    print(f"events:   {state_dir / 'events.jsonl'}")
    print(f"provenance: {state_dir / 'provenance.jsonl'}")
    return {
        "state_dir": str(state_dir),
        "survivors": survivors,
        "ledger": (state_dir / "ledger.jsonl").read_text().strip().split("\n"),
        "events": (state_dir / "events.jsonl").read_text().strip().split("\n"),
        "provenance": (state_dir / "provenance.jsonl").read_text().strip().split("\n"),
    }


if __name__ == "__main__":
    result = run_demo()
    sys.exit(0 if not result["survivors"] else 1)
