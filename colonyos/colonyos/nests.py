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

    def bequeath(self, dying: BotConfig, heir: BotConfig, now_tick: int) -> list[NestClaim]:
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
