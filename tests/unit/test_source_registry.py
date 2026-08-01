"""Source registry (§30.8): shipped state, and the states it refuses."""

import pytest
from pydantic import ValidationError

from trading_firm.surveillance.sources.registry import (
    CONTEXT_INSTRUMENTS_PATH,
    REGISTRY_PATH,
    SourceRecord,
    SourceRegistry,
    load_context_instruments,
    load_source_registry,
)


@pytest.fixture(scope="module")
def registry() -> SourceRegistry:
    return load_source_registry(REGISTRY_PATH)


def _record(**overrides) -> SourceRecord:
    base = dict(
        source_id="test_source",
        source_type="news",
        provider_name="Test",
        assets_or_currencies=["USD"],
        auth_required=False,
        polling_policy="never",
        rate_limit_policy="none",
        priority=1,
        reliability_tier=3,
        license_or_usage_notes="test",
        production_approved=False,
        fail_closed_when_unavailable=True,
    )
    base.update(overrides)
    return SourceRecord.model_validate(base)


class TestShippedRegistry:
    def test_exactly_the_existing_paid_sources(self, registry) -> None:
        # $0 new recurring cost: OANDA practice + the existing FMP key.
        assert set(registry.by_id) == {"oanda_practice", "fmp", "fmp.news"}

    def test_nothing_is_production_approved(self, registry) -> None:
        assert not any(r.production_approved for r in registry.sources)
        assert all(r.approval_record_id is None for r in registry.sources)

    def test_every_source_fails_closed(self, registry) -> None:
        assert all(r.fail_closed_when_unavailable for r in registry.sources)

    def test_require_refuses_an_unregistered_source(self, registry) -> None:
        with pytest.raises(KeyError, match="not in the registry"):
            registry.require("free_scraper")

    def test_the_view_is_frozen(self, registry) -> None:
        # The bench precedent: no add(), no runtime registration.
        with pytest.raises(TypeError):
            registry.by_id["rogue"] = registry.sources[0]  # type: ignore[index]


class TestRefusedStates:
    def test_production_without_an_approval_record(self) -> None:
        with pytest.raises(ValidationError, match="silently become"):
            _record(production_approved=True)

    def test_production_and_research_only_contradict(self) -> None:
        with pytest.raises(ValidationError, match="research_only"):
            _record(
                production_approved=True,
                approval_record_id="governance/approvals/nonexistent.md",
                research_only=True,
            )

    @pytest.mark.parametrize("bad_id", ["Free Scraper", "UPPER", "1starts_with_digit", ""])
    def test_prose_is_not_a_source_id(self, bad_id) -> None:
        with pytest.raises(ValidationError, match="reproducible"):
            _record(source_id=bad_id)

    def test_duplicate_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            SourceRegistry.model_validate(
                {"version": "1.0.0", "sources": [
                    _record().model_dump(), _record().model_dump(),
                ]}
            )

    def test_zero_freshness_sla_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _record(freshness_sla_seconds=0)


class TestContextInstruments:
    def test_shipped_list_is_empty_by_design(self) -> None:
        # cross_market.enabled is false; approving an instrument is a
        # registry edit ratified with its rollout step (§30.3).
        assert load_context_instruments(CONTEXT_INSTRUMENTS_PATH) == ()

    def test_prose_is_not_an_instrument(self, tmp_path) -> None:
        bad = tmp_path / "market_context_instruments.yaml"
        bad.write_text("context_instruments: ['dollar index futures']\n")
        with pytest.raises(ValueError, match="approved contextual instruments only"):
            load_context_instruments(bad)

    def test_instrument_ids_pass(self, tmp_path) -> None:
        good = tmp_path / "market_context_instruments.yaml"
        good.write_text("context_instruments: [USD_JPY, XAU_USD]\n")
        assert load_context_instruments(good) == ("USD_JPY", "XAU_USD")
