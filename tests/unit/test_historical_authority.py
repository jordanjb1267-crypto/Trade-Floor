"""The 2026-08-10 authoritative session result, provable in ANY checkout.

Incident-review requirement 29 demands that the 2026-08-10 session — the
transient-401 incident that produced DEGRADED / NON_QUALIFYING with an
UNVERIFIED flat state — stays exactly as recorded, and §31.4 prohibits it
ever reading nominal or earning stability credit. The original regression
proved this by reading `reports/ops/2026-08-10-session.json` directly,
which is production-only and gitignored: the invariant held on the machine
that already had the evidence and FAILED in every clean checkout, so the
repository's deterministic CI was red from the day the test landed. A
required invariant was hidden behind an environment-specific file.

The remedy is canonical evidence with provenance, not a weaker assertion:

* `tests/fixtures/2026-08-10-session.authoritative.json` is DERIVED from
  the authoritative production artifact by `derive_canonical()` below —
  the repository's own `redact()` over every event outcome, plus the
  practice account identifier's digits replaced. Nothing else changes:
  every load-bearing field is byte-faithful to the record.
* `tests/fixtures/2026-08-10-session.provenance.json` records where the
  fixture came from: the SHA-256 of the production source artifact and of
  the fixture file itself. Tampering with the fixture breaks the digest;
  tampering with the production artifact breaks the equivalence test in
  any checkout that holds it.
* In a checkout that HAS the production artifact, the equivalence test
  re-derives the canonical form from the live file and requires exact
  equality — the deterministic fixture and the production record cannot
  drift apart silently. In a clean checkout that test skips, clearly
  labelled environment-specific, because the invariant it supplements is
  already proven above it from committed evidence alone.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from trading_firm.notify.surface import redact

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "2026-08-10-session.authoritative.json"
PROVENANCE = REPO / "tests" / "fixtures" / "2026-08-10-session.provenance.json"
PRODUCTION_ARTIFACT = REPO / "reports" / "ops" / "2026-08-10-session.json"

# The practice account identifier appears inside the incident's flatten error
# detail. Its shape is public (the test suite fakes `101-001-TEST-001`); the
# real middle digits are not needed by any invariant and are not committed.
_ACCOUNT_ID = re.compile(r"101-001-\d+-001")


def derive_canonical(report: dict) -> dict:
    """The exact derivation that produced the committed fixture.

    Load-bearing fields pass through untouched. Only free-text event
    outcomes are transformed: the repository's own redact() (token shapes),
    then the account-identifier digits. The equivalence test re-runs this
    over the live production artifact, so this function is the single
    definition of the fixture's relationship to its source.
    """
    canonical = json.loads(json.dumps(report))
    for event in canonical.get("events", []):
        event["outcome"] = _ACCOUNT_ID.sub(
            "101-001-<redacted-account>-001", redact(event["outcome"])
        )
    return canonical


def canonical() -> dict:
    # A MISSING fixture must fail loudly here, never skip: the fixture is
    # committed evidence, and its absence is a broken checkout (mutation M2).
    return json.loads(FIXTURE.read_text())


class TestAug10AuthoritativeResult:
    """Requirement 29, deterministic: provable from the repository alone."""

    def test_the_session_is_degraded_and_non_qualifying(self) -> None:
        report = canonical()
        assert report["session_health"] == "DEGRADED"
        assert report["qualification"] == "NON_QUALIFYING"
        assert report["degraded"] is True
        assert report["nominal"] is False

    def test_flat_state_remains_unverified(self) -> None:
        """§31.2: the broker never answered at the flatten boundary, and no
        later evidence may rewrite that into a verified flat."""
        report = canonical()
        assert report["flat_state"] == "UNVERIFIED"
        flatten = [e for e in report["events"] if e["event"] == "flatten"]
        assert len(flatten) == 1
        assert "UNVERIFIED" in flatten[0]["outcome"]

    def test_no_qualification_credit_can_appear(self) -> None:
        report = canonical()
        assert report["qualifying"] is False
        assert report["qualification_reason"] == "SESSION DEGRADED"
        assert report["required_event_count"] == 5
        assert report["clean_event_count"] == 4
        assert report["failed_event_count"] == 1
        assert report["orders_placed"] == 0

    def test_the_record_is_the_aug_10_session_not_a_substitute(self) -> None:
        """No other date may quietly stand in for the incident session."""
        report = canonical()
        assert report["session_date"] == "2026-08-10"
        assert [e["event"] for e in report["events"]] == [
            "pre_startup", "briefing", "activation", "entry_cutoff", "flatten",
        ]
        assert all(e["at"].startswith("2026-08-10T") for e in report["events"])

    def test_the_fixture_lives_in_the_repository_not_in_production_state(self) -> None:
        """The deterministic invariant must need nothing gitignored: the
        fixture sits under tests/fixtures, never under reports/."""
        assert FIXTURE.is_file()
        assert REPO / "reports" not in FIXTURE.parents


class TestFixtureProvenance:
    def test_the_fixture_digest_matches_its_provenance_record(self) -> None:
        provenance = json.loads(PROVENANCE.read_text())
        actual = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        assert actual == provenance["fixture_sha256"], (
            "the committed fixture no longer matches its recorded digest — "
            "canonical historical evidence must never change silently"
        )
        assert provenance["source"] == "reports/ops/2026-08-10-session.json"
        assert provenance["derivation"].startswith("derive_canonical")

    def test_the_fixture_contains_no_secret_or_machine_local_material(self) -> None:
        blob = FIXTURE.read_text() + PROVENANCE.read_text()
        assert not re.search(r"[0-9a-f]{32}-[0-9a-f]{32}", blob), "token shape"
        assert "Bearer" not in blob
        assert not _ACCOUNT_ID.search(blob), "real account identifier"
        assert "/Users/" not in blob and "/home/" not in blob, "machine-local path"


class TestProductionArtifactEquivalence:
    """Environment-specific supplement, NOT the required invariant.

    The deterministic tests above prove requirement 29 from committed
    evidence in any checkout. This one runs only where the authoritative
    production artifact exists and pins fixture and artifact to each other
    exactly — so neither can drift from the other unnoticed.
    """

    def test_production_artifact_matches_the_canonical_fixture(self) -> None:
        if not PRODUCTION_ARTIFACT.is_file():
            pytest.skip(
                "production-only equivalence check: the authoritative artifact "
                "exists only in the production checkout; the deterministic "
                "invariant is proven by TestAug10AuthoritativeResult"
            )
        provenance = json.loads(PROVENANCE.read_text())
        source_digest = hashlib.sha256(PRODUCTION_ARTIFACT.read_bytes()).hexdigest()
        assert source_digest == provenance["source_sha256"], (
            "the production artifact changed after the fixture was derived — "
            "historical session records are immutable (§0 rule 11)"
        )
        derived = derive_canonical(json.loads(PRODUCTION_ARTIFACT.read_text()))
        assert derived == canonical(), (
            "re-deriving the canonical form from the production artifact no "
            "longer reproduces the committed fixture"
        )
