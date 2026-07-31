"""Senior-trader independence protocol (§6.2) as enforceable code.

§6.2 states the protocol as seven numbered rules. Stated as prose they are
honor-system: nothing stops an orchestrator from handing Alpha's reasoning to
Beta, and nothing detects it afterward. §21 makes one of them an acceptance
criterion — "Alpha cannot access Beta's first-pass report before submitting its
own, and vice versa" — so it needs a mechanism, not an instruction.

The ledger here is that mechanism. Each rule maps to something the code does:

1. Both receive the same immutable Market State Packet — `issue()` records one
   `packet_id`, and `submit()` rejects a report citing a different one.
2. They work in separate context windows — outside this module's control, but
   rule 3 makes a leak useless.
3. Neither sees the other's reasoning before first-pass submission — `read()`
   raises until both locks exist. This is the §21 criterion.
4. First-pass reports are hashed or marked immutable — `LockedReport` is frozen
   and carries a content hash.
5. The Arbiter compares only after both are complete — `both_locked` gates it.
6. A second-round response must list what changed — `revise()` requires a
   non-empty `changed` list and refuses a revision that claims nothing changed
   while the thesis differs.
7. Agreement earns value only from materially independent evidence —
   `agreement()` reports whether the two theses rest on disjoint features, so
   the Arbiter can tell independent agreement from duplicated evidence
   (§6.1.D: "must not average two weak theses into one apparently strong
   thesis").
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

from trading_firm.adaptive import AdaptiveThesis
from trading_firm.packet import MarketSnapshot, MarketStatePacket

TRADERS = ("alpha", "beta")


def _thesis_hash(thesis: AdaptiveThesis) -> str:
    """Content hash over the thesis as submitted (§6.2 rule 4)."""
    payload = thesis.model_dump(mode="json")
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class LockedReport:
    """An immutable first-pass report (§6.2 rule 4)."""

    trader_id: str
    packet_id: str
    thesis: AdaptiveThesis
    locked_at: dt.datetime
    content_hash: str

    def verify(self) -> None:
        actual = _thesis_hash(self.thesis)
        if actual != self.content_hash:
            raise ValueError(
                f"{self.trader_id} first-pass report was altered after locking: "
                f"expected {self.content_hash}, computed {actual} (§6.2)"
            )


@dataclass(frozen=True)
class Revision:
    """A second-round response (§6.2 rule 6)."""

    trader_id: str
    thesis: AdaptiveThesis
    changed: tuple[str, ...]
    revised_at: dt.datetime


@dataclass
class IndependenceLedger:
    """One session's independence record for the Alpha/Beta pair.

    Mutable by design — it accumulates submissions — but everything it hands
    back is frozen.

    Carries BOTH identities from §6A deliberately. `packet_id` binds the two
    traders to one another: they were handed the same market *and* the same
    firm state. `market_id` binds them to the evidence itself, and it is the
    one a downstream consumer must check before re-deriving anything from a
    snapshot, because a snapshot is not self-identifying — an adversarial
    review showed the Arbiter re-classifying both locked theses against an
    entirely unrelated `MarketSnapshot` while every §6.2 gate reported healthy.
    Independence between the traders was never the whole requirement; §6A also
    requires that what they analysed is what gets arbitrated.
    """

    packet_id: str
    market_id: str
    _locked: dict[str, LockedReport] = field(default_factory=dict)
    _revisions: dict[str, Revision] = field(default_factory=dict)

    @classmethod
    def for_packet(cls, packet: MarketStatePacket) -> IndependenceLedger:
        """Preferred constructor: both identities taken from one packet, so
        they cannot be supplied inconsistently."""
        return cls(packet_id=packet.packet_id, market_id=packet.market_id)

    def verify_market(self, market: MarketSnapshot) -> None:
        """Fail closed unless `market` is the evidence the pair locked against.

        Called by anything that re-derives a classification from a snapshot
        after the fact (§6A, §0.10).
        """
        if market.checksum != self.market_id:
            raise ValueError(
                f"market snapshot {market.checksum} is not the packet the senior traders "
                f"analysed ({self.market_id}): both traders receiving the same packet is "
                f"only half of §6A — what they analysed must also be what is arbitrated"
            )

    @property
    def both_locked(self) -> bool:
        return set(self._locked) == set(TRADERS)

    def submit(self, thesis: AdaptiveThesis, packet_id: str, at: dt.datetime) -> LockedReport:
        """Lock a first-pass report. One per trader; never replaced (§6.2 rule 4)."""
        trader = thesis.trader_id
        if trader not in TRADERS:
            raise ValueError(f"unknown trader {trader!r}: the pair is {TRADERS} (§6.2)")
        if packet_id != self.packet_id:
            raise ValueError(
                f"{trader} submitted against packet {packet_id} but the session issued "
                f"{self.packet_id}: both traders must receive the same packet (§6.2, §6A)"
            )
        if trader in self._locked:
            raise ValueError(
                f"{trader} already locked a first-pass report; first-pass reports are "
                f"immutable and are not resubmitted (§6.2). Use revise() for round two."
            )
        if at.tzinfo is None:
            raise ValueError("lock timestamps must be timezone-aware (§10.3)")

        report = LockedReport(
            trader_id=trader,
            packet_id=packet_id,
            thesis=thesis,
            locked_at=at,
            content_hash=_thesis_hash(thesis),
        )
        self._locked[trader] = report
        return report

    def read(self, requester: str, target: str) -> LockedReport:
        """Read another trader's first-pass report.

        The §21 acceptance criterion lives here: this raises until BOTH reports
        are locked, so neither trader can see the other's reasoning before
        committing its own. A leak is not merely prohibited — the report is not
        obtainable.
        """
        if requester not in TRADERS or target not in TRADERS:
            raise ValueError(f"traders are {TRADERS} (§6.2)")
        if requester != target and requester not in self._locked:
            raise PermissionError(
                f"{requester} has not locked its own first-pass report and may not read "
                f"{target}'s: neither trader receives the other's reasoning before "
                f"first-pass submission (§6.2, §21)"
            )
        if target not in self._locked:
            raise PermissionError(
                f"{target} has not locked a first-pass report yet (§6.2)"
            )
        report = self._locked[target]
        report.verify()
        return report

    def for_arbiter(self) -> tuple[LockedReport, LockedReport]:
        """Both reports, released only once both are complete (§6.2 rule 5)."""
        if not self.both_locked:
            missing = sorted(set(TRADERS) - set(self._locked))
            raise PermissionError(
                f"the Arbiter compares the theses only after both are complete; "
                f"still outstanding: {missing} (§6.2, §6.1)"
            )
        for report in self._locked.values():
            report.verify()
        return (self._locked["alpha"], self._locked["beta"])

    def revise(
        self,
        thesis: AdaptiveThesis,
        changed: list[str],
        at: dt.datetime,
    ) -> Revision:
        """Record a second-round response (§6.2 rule 6).

        A revision must explicitly list what changed after seeing the opposing
        thesis. A silent convergence — the thesis moves, the account of why does
        not — is exactly the failure rule 6 exists to surface, so it is rejected.
        """
        trader = thesis.trader_id
        if trader not in self._locked:
            raise PermissionError(
                f"{trader} cannot revise before locking a first-pass report (§6.2)"
            )
        if not self.both_locked:
            raise PermissionError(
                f"{trader} cannot revise before both first passes are locked: a "
                f"revision responds to the opposing thesis (§6.2)"
            )
        original = self._locked[trader].thesis
        moved = _thesis_hash(thesis) != _thesis_hash(original)
        if moved and not [c for c in changed if c.strip()]:
            raise ValueError(
                f"{trader}'s revision changes the thesis but lists nothing changed: any "
                f"second-round response must explicitly state what changed after seeing "
                f"the opposing thesis (§6.2)"
            )
        revision = Revision(
            trader_id=trader,
            thesis=thesis,
            changed=tuple(changed),
            revised_at=at,
        )
        self._revisions[trader] = revision
        return revision

    def agreement(self) -> Agreement:
        """Whether the two theses agree, and whether independently (§6.2 rule 7)."""
        alpha, beta = self.for_arbiter()
        a_features = {f.feature_id for f in alpha.thesis.selected_features}
        b_features = {f.feature_id for f in beta.thesis.selected_features}
        return Agreement(
            same_direction=alpha.thesis.direction == beta.thesis.direction,
            shared_features=tuple(sorted(a_features & b_features)),
            alpha_only=tuple(sorted(a_features - b_features)),
            beta_only=tuple(sorted(b_features - a_features)),
        )


@dataclass(frozen=True)
class Agreement:
    """§6.2 rule 7 / §6.1.D: agreement earns value only when independently reached."""

    same_direction: bool
    shared_features: tuple[str, ...]
    alpha_only: tuple[str, ...]
    beta_only: tuple[str, ...]

    @property
    def materially_independent(self) -> bool:
        """True when each trader contributed evidence the other did not.

        Two theses resting on an identical feature set are one thesis counted
        twice, however different their prose. The Arbiter is told the difference
        rather than left to infer it.
        """
        return bool(self.alpha_only) and bool(self.beta_only)

    @property
    def independent_agreement(self) -> bool:
        return self.same_direction and self.materially_independent
