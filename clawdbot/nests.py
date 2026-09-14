"""Bot-side Nest Economy support (NEST_ECONOMY.md §2-§3).

The substrate (`colonyos`) owns claim issuance semantics and the token
ledger; this module is the clawdbot-side mirror the reproduction decision
consumes:

- `NestPolicy` — the `reproduction.nests` block of
  `config/openclaw_config.yaml` (operator intent; path overridable via
  `OPENCLAW_CONFIG_PATH`). Missing file or section means disabled, which
  keeps the legacy reproduction decision byte-unchanged.
- `BotNestClaim` — a claim on an operator-listed site, held by name in the
  `NestLedger` (the clawdbot stand-in for the parent's config field).
  Expiry is measured in the bot's own cycle clock — the only logical time
  a clawdbot bot has.
- `NestLedger` — issues claims against operator-listed sites
  (operator-provisioned source; bots never self-grant), debits them on
  spawn (one-time use), and moves a dying holder's live claims to a living
  descendant (bequest, kin-flow).

Bots do not invent nests: a claim can only name a site listed in the
policy, and the claim's route must match the site's pinned route — a claim
can never assert a route the site does not serve.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

__all__ = [
    "BotNestClaim",
    "NestLedger",
    "NestPolicy",
    "NestSite",
    "get_nest_policy",
    "reset_nest_policy",
]

DEFAULT_CONFIG_PATH = "config/openclaw_config.yaml"


@dataclass(frozen=True)
class NestSite:
    """An operator-provisioned nest site (NEST_ECONOMY.md §2 Gate 1)."""

    site_id: str
    host: str = ""
    route: str = ""  # resolved model route this site is provisioned to serve
    site_class: str | None = None
    workspace_root: str | None = None  # optional handshake marker: <root>/state/ledger.jsonl


@dataclass(frozen=True)
class BotNestClaim:
    """A claim held by one bot on one nest site, expiring by cycle count."""

    site_id: str
    host: str
    route: str
    site_class: str | None
    expires_cycle: int

    @property
    def fingerprint(self) -> tuple:
        return (self.site_id, self.host, self.route, self.expires_cycle)


@dataclass(frozen=True)
class NestPolicy:
    """The nests block of `config/openclaw_config.yaml`.

    `enabled: false` (the default) keeps the legacy spawn path; the block
    otherwise documents operator intent mirrored from
    `colonyos/colonyos/config.py`'s `NestsConfig` (the authoritative
    schema). `min_child_lease` is enforced substrate-side (`spawn.py`) and
    is deliberately absent here: clawdbot wallets are dollars, not lease
    tokens.
    """

    enabled: bool = False
    sites: tuple[NestSite, ...] = ()
    parent_survival_buffer_cycles: int = 10
    min_offspring_return: float = 0.0
    claim_ttl_ticks: int = 50
    route_limits: dict[str, float] = field(default_factory=dict)

    def site(self, site_id: str) -> NestSite | None:
        """The only claim->site resolution path."""
        for site in self.sites:
            if site.site_id == site_id:
                return site
        return None

    def handshake_ok(self, claim: BotNestClaim) -> bool:
        """Offline verification that the claim matches its listed site.

        Mirrors the substrate handshake (version + route admission + ledger
        marker) with the parts clawdbot can see: the site is operator-listed
        and pins the claim's route; an optional workspace marker must exist.
        Hermetic — no network.
        """
        site = self.site(claim.site_id)
        if site is None or claim.route != site.route:
            return False
        if site.workspace_root is not None:
            marker = Path(site.workspace_root) / "state" / "ledger.jsonl"
            if not marker.exists():
                return False
        return True


def load_nest_policy(path: str | Path | None = None) -> NestPolicy:
    """Parse `reproduction.nests` from the OpenClaw config YAML.

    Missing file or missing/empty section means the Nest Economy is off —
    the legacy reproduction decision is untouched.
    """
    path = Path(path or os.environ.get("OPENCLAW_CONFIG_PATH") or DEFAULT_CONFIG_PATH)
    if not path.exists():
        return NestPolicy(enabled=False)
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return NestPolicy(enabled=False)
    nests = (data.get("reproduction") or {}).get("nests") or {}
    if not nests.get("enabled"):
        return NestPolicy(enabled=False)
    sites = tuple(
        NestSite(
            site_id=raw["site_id"],
            host=raw.get("host", ""),
            route=raw.get("route", ""),
            site_class=raw.get("site_class"),
            workspace_root=raw.get("workspace_root"),
        )
        for raw in nests.get("sites") or []
    )
    return NestPolicy(
        enabled=True,
        sites=sites,
        parent_survival_buffer_cycles=int(nests.get("parent_survival_buffer_cycles", 10)),
        min_offspring_return=float(nests.get("min_offspring_return", 0.0)),
        claim_ttl_ticks=int(nests.get("claim_ttl_ticks", 50)),
        route_limits={str(k): float(v) for k, v in (nests.get("route_limits") or {}).items()},
    )


_policy_cache: NestPolicy | None = None


def get_nest_policy() -> NestPolicy:
    """Cached policy read (config is operator-provisioned, not per-cycle)."""
    global _policy_cache
    if _policy_cache is None:
        _policy_cache = load_nest_policy()
    return _policy_cache


def reset_nest_policy() -> None:
    """Drop the cached policy (tests swap configs via OPENCLAW_CONFIG_PATH)."""
    global _policy_cache
    _policy_cache = None


class NestLedger:
    """Issues and tracks nest claims against the operator's site list.

    Pure bookkeeping over policy data + explicit cycle numbers — no wall
    clock, no rng, no network. The claim store is keyed by holder name (the
    clawdbot analogue of claims living in the holder's bot config);
    consumption is tracked by fingerprint so a claim survives a bequest
    still usable exactly once.
    """

    def __init__(self, policy: NestPolicy):
        self.policy = policy
        self._claims: dict[str, list[BotNestClaim]] = {}
        self._consumed: set[tuple] = set()

    # -- issuance (operator-provisioned source; never called by a bot) -------

    def issue(self, holder_name: str, site_id: str, now_cycle: int) -> BotNestClaim:
        """Issue a claim for an operator-listed site to the named holder."""
        site = self.policy.site(site_id)
        if site is None:
            raise ValueError(f"unknown nest site: {site_id}")
        claim = BotNestClaim(
            site_id=site.site_id,
            host=site.host,
            route=site.route,
            site_class=site.site_class,
            expires_cycle=now_cycle + self.policy.claim_ttl_ticks,
        )
        self._claims.setdefault(holder_name, []).append(claim)
        return claim

    # -- holder-side lookups (the bot's Gate 1) ------------------------------

    def live_claims(self, holder_name: str, now_cycle: int) -> list[BotNestClaim]:
        """The holder's unconsumed claims on listed sites, unexpired only.

        Claims for unlisted sites are worthless and skipped (substrate rule).
        Expired claims are dropped from the store: an expired claim is not a
        held claim.
        """
        held = [
            c
            for c in self._claims.get(holder_name, [])
            if c.site_id in {s.site_id for s in self.policy.sites}
            and c.fingerprint not in self._consumed
        ]
        live = [c for c in held if now_cycle < c.expires_cycle]
        expired = [c for c in held if c not in live]
        if expired:
            self._claims[holder_name] = [
                c for c in self._claims.get(holder_name, []) if c not in expired
            ]
        return live

    def live_claim(self, holder_name: str, now_cycle: int) -> BotNestClaim | None:
        """The holder's first live claim, or None."""
        claims = self.live_claims(holder_name, now_cycle)
        return claims[0] if claims else None

    def consume(self, holder_name: str, claim: BotNestClaim, now_cycle: int) -> None:
        """Debit a claim (one-time use). Raises on expiry or double-use."""
        if now_cycle >= claim.expires_cycle:
            raise ValueError(f"claim expired at cycle {claim.expires_cycle}")
        if claim.fingerprint in self._consumed:
            raise ValueError(f"claim already consumed: {claim.site_id}")
        self._consumed.add(claim.fingerprint)
        remaining = [
            c for c in self._claims.get(holder_name, []) if c.fingerprint != claim.fingerprint
        ]
        self._claims[holder_name] = remaining

    def bequeath(self, dying_name: str, heir_name: str, now_cycle: int) -> list[BotNestClaim]:
        """Move the dying holder's live claims to the heir (NEST §2).

        Gift-shaped: no tokens move; the ledger records nothing but state —
        the caller reports the kin-flow event.
        """
        moved = self.live_claims(dying_name, now_cycle)
        if not moved:
            return []
        self._claims[heir_name] = [*self._claims.get(heir_name, []), *moved]
        self._claims[dying_name] = []
        return moved
