"""LeaseStore: the token ledger — one number per bot, one rule: empty = death.

Trust properties (DESIGN.md §5, §10):
- The ledger lives in `state/` (0700, supervisor-owned). Bots never receive
  its path and have no API to write it.
- Top-ups are credited ONLY by the supervisor, ONLY from Task Shop's
  server-side verification results (never from bot claims or events.jsonl).
- Life-or-death decisions read the ledger, never the yaml (yaml initial
  funding applies once, at first boot).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LeaseState:
    name: str
    remaining_tokens: int
    expires_at: float
    alive: bool = True
    death_cause: str | None = None


@dataclass
class LedgerEntry:
    ts: float
    bot: str
    kind: str  # birth | debit | topup | death | reconcile | endowment | bequest
    delta: int = 0
    balance: int = 0
    note: str | None = None


class LeaseStore:
    """Supervisor-owned token ledger. Appends an audit trail to `ledger.jsonl`."""

    def __init__(self, state_dir: Path | str):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Chokepoint: only the supervisor user may read/write the ledger.
        os.chmod(self.state_dir, 0o700)
        self._ledger_path = self.state_dir / "ledger.jsonl"
        self.leases: dict[str, LeaseState] = {}
        self.entries: list[LedgerEntry] = []

    # -- lifecycle ----------------------------------------------------------

    def birth(self, name: str, initial_tokens: int, expiry_hours: float) -> LeaseState:
        if name in self.leases:
            raise ValueError(f"lease already exists: {name}")
        lease = LeaseState(
            name=name,
            remaining_tokens=initial_tokens,
            expires_at=time.time() + expiry_hours * 3600,
        )
        self.leases[name] = lease
        self._append(LedgerEntry(time.time(), name, "birth", initial_tokens, initial_tokens))
        return lease

    def debit(self, name: str, tokens: int) -> bool:
        """Debit tokens for a generate() call. Returns False if underfunded."""
        lease = self.leases[name]
        if not lease.alive:
            return False
        if lease.remaining_tokens < tokens:
            return False
        lease.remaining_tokens -= tokens
        self._append(LedgerEntry(time.time(), name, "debit", -tokens, lease.remaining_tokens))
        return True

    def expire(self, name: str, cause: str) -> None:
        """Mark a lease dead (expiry, revocation, exhaustion)."""
        lease = self.leases[name]
        if lease.alive:
            lease.alive = False
            lease.death_cause = cause
            self._append(LedgerEntry(time.time(), name, "death", 0, 0, cause))

    def reconcile(self, name: str, delta: int) -> None:
        """Apply a post-hoc correction (actual vs estimated cost).

        Positive delta refunds; negative delta debits the difference,
        floored at zero (a lease never goes negative). Supervisor-side
        only, same trust surface as debit/topup.
        """
        lease = self.leases[name]
        if not lease.alive or delta == 0:
            return
        if delta > 0:
            lease.remaining_tokens += delta
        else:
            lease.remaining_tokens = max(0, lease.remaining_tokens + delta)
        self._append(LedgerEntry(time.time(), name, "reconcile", delta, lease.remaining_tokens))

    def topup(self, name: str, tokens: int, note: str | None = None) -> None:
        """Mint tokens. Called ONLY from the supervisor's verified-completion path."""
        lease = self.leases[name]
        lease.remaining_tokens += tokens
        self._append(LedgerEntry(time.time(), name, "topup", tokens, lease.remaining_tokens, note))

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
        balance = self.leases[from_name].remaining_tokens if from_name in self.leases else 0
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

    def check_expired(self, now: float | None = None) -> list[str]:
        """Expire leases past their wall-clock expiry. Returns names reaped."""
        now = now if now is not None else time.time()
        reaped = []
        for name, lease in self.leases.items():
            if lease.alive and now >= lease.expires_at:
                self.expire(name, "expired")
                reaped.append(name)
        return reaped

    # -- persistence --------------------------------------------------------

    def _append(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)
        with self._ledger_path.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": entry.ts,
                        "bot": entry.bot,
                        "kind": entry.kind,
                        "delta": entry.delta,
                        "balance": entry.balance,
                        "note": entry.note,
                    }
                )
                + "\n"
            )

    def snapshot(self) -> dict[str, LeaseState]:
        return dict(self.leases)
