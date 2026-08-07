"""Configuration schema tests (governing spec §21 'Configuration schema').

The base config must load, and every constitutional invariant must be
enforced by the schema — i.e., a config edited to contradict the
constitution must FAIL to load.
"""

import copy

import pytest
import yaml
from pydantic import ValidationError

from trading_firm.config import BASE_CONFIG_PATH, FirmConfig, load_config


@pytest.fixture(scope="module")
def base_raw() -> dict:
    return yaml.safe_load(BASE_CONFIG_PATH.read_text())


@pytest.fixture(scope="module")
def base_config() -> FirmConfig:
    return load_config(BASE_CONFIG_PATH)


class TestBaseConfigLoads:
    def test_loads_and_validates(self, base_config: FirmConfig) -> None:
        assert base_config.firm.name == "Claude London Trading Firm"
        assert base_config.firm.environment == "research"

    def test_live_allowed_empty(self, base_config: FirmConfig) -> None:
        # §24: the repository begins with live_allowed empty.
        assert base_config.strategies.live_allowed == []
        assert base_config.instruments.live_allowed == []

    def test_ladder_matches_anchor_fractions(self, base_config: FirmConfig) -> None:
        # §3.2: $2.50/1%, $7.50/3%, $12.50/5%, $25/10% of $250 exactly.
        ladder = base_config.risk_ladder
        anchor = base_config.risk.tier_anchor_usd
        assert ladder.standard.initial_usd == anchor * 0.01
        assert ladder.strong.initial_usd == anchor * 0.03
        assert ladder.high.initial_usd == anchor * 0.05
        assert ladder.exceptional.initial_usd == anchor * 0.10

    def test_session_anchored_in_london(self, base_config: FirmConfig) -> None:
        # §14 (R: C-2): Europe/London anchor, boundaries strictly increasing.
        assert base_config.session.anchor_timezone == "Europe/London"
        assert base_config.session.activation_london == "08:00"
        assert base_config.session.flatten_london == "11:00"

    def test_limits_match_constitution(self, base_config: FirmConfig) -> None:
        risk = base_config.risk
        assert risk.max_open_positions == 1
        assert risk.max_trades_per_session == 2
        assert risk.initial_session_loss_limit_usd == 25.00
        assert risk.initial_weekly_loss_limit_usd == 37.50
        assert risk.initial_live_floor_usd == 200.00


def _mutated(base_raw: dict, path: list, value) -> dict:
    raw = copy.deepcopy(base_raw)
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return raw


class TestConstitutionalInvariants:
    """Each case edits the config to contradict the constitution; loading must fail."""

    @pytest.mark.parametrize(
        "path,value",
        [
            (["risk", "martingale"], True),  # §0.7
            (["risk", "stop_widening"], True),  # §0.7
            (["risk", "averaging_down"], True),  # §0.7
            (["risk", "recovery_sizing"], True),  # §0.7
            (["risk", "tier_promotion_requires_owner_approval"], False),  # C-3 / D-2
            (["risk", "deposits_advance_milestones"], True),  # C-3 / D-3
            (["execution", "fail_closed"], False),  # §0.10
            (["execution", "require_broker_stop_confirmation"], False),  # §0.9
            (["session", "anchor_timezone"], "America/Chicago"),  # C-2
            (["session", "holiday_calendar_required"], False),  # N-11
            (["firm", "profit_target"], 100.0),  # §3.5
            (["risk_ladder", "standard", "initial_usd"], 5.00),  # §3.2 fraction mismatch
            (["risk_ladder", "exceptional", "prohibited_after_session_loss"], False),  # §3.4
            (["strategies", "live_allowed"], ["london_breakout"]),  # §24 outside live env
            (["risk", "initial_weekly_loss_limit_usd"], 20.00),  # §3.4 weekly > session
            (["risk", "initial_live_floor_usd"], 300.00),  # §3.4 floor < anchor
            # v2 adaptive layer (§6.8, §6.2, §11) — an unvalidated idea must not
            # be able to reach live exposure through configuration.
            (["adaptive_trading", "allowed_live_novelty_classes"], ["N2"]),  # §6.8
            (["adaptive_trading", "allowed_live_novelty_classes"], ["N3"]),  # §6.8
            (["adaptive_trading", "exceptional_risk_allowed_novelty_classes"], ["N1"]),  # §6.8
            (["adaptive_trading", "independent_first_pass_required"], False),  # §6.2
            (["adaptive_trading", "market_state_packet_checksum_required"], False),  # §6.2
            (["adaptive_trading", "narrative_only_candidates_rejected"], False),  # §21
            (["feature_registry", "production_allowed"], ["unvalidated_feature"]),  # §11
        ],
    )
    def test_violation_rejected(self, base_raw: dict, path: list, value) -> None:
        with pytest.raises(ValidationError):
            FirmConfig.model_validate(_mutated(base_raw, path, value))

    def test_session_ordering_enforced(self, base_raw: dict) -> None:
        raw = _mutated(base_raw, ["session", "flatten_london"], "07:00")
        with pytest.raises(ValidationError):
            FirmConfig.model_validate(raw)

    def test_unknown_keys_rejected(self, base_raw: dict) -> None:
        raw = copy.deepcopy(base_raw)
        raw["risk"]["surprise_knob"] = 1
        with pytest.raises(ValidationError):
            FirmConfig.model_validate(raw)


class TestTimingToleranceCeilings:
    """§31.1/§31.3 owner hardening: ordinary configuration may TIGHTEN a
    tolerance but may never raise a hard-boundary tolerance beyond the ratified
    maximum. A YAML edit alone must never make a grossly late hard boundary
    score clean — that requires a spec amendment, owner approval, a schema
    change, tests, and a separate reviewed PR."""

    def _session(self, **overrides):
        raw = yaml.safe_load(BASE_CONFIG_PATH.read_text())
        data = copy.deepcopy(raw)
        data["session"]["timing_tolerances_seconds"].update(overrides)
        return FirmConfig.model_validate(data)

    def test_the_ratified_baseline_validates(self) -> None:
        config = self._session()
        assert config.session.timing_tolerances_seconds.flatten == 5

    @pytest.mark.parametrize("field", ["flatten", "entry_cutoff"])
    def test_a_hard_boundary_cannot_be_widened_by_yaml(self, field) -> None:
        with pytest.raises(ValidationError, match="handler jitter, not trading authority"):
            self._session(**{field: 60})

    def test_the_aug06_breach_cannot_be_configured_clean(self) -> None:
        """4568 s of lateness must stay a breach no matter what YAML says."""
        with pytest.raises(ValidationError):
            self._session(flatten=5000)

    @pytest.mark.parametrize("field", ["flatten", "entry_cutoff", "activation"])
    def test_tightening_is_always_allowed(self, field) -> None:
        config = self._session(**{field: 0})
        assert getattr(config.session.timing_tolerances_seconds, field) == 0

    def test_activation_and_checkpoints_have_ceilings_too(self) -> None:
        with pytest.raises(ValidationError, match="activation tolerance"):
            self._session(activation=120)
        with pytest.raises(ValidationError, match="briefing tolerance"):
            self._session(briefing=600)

    def test_a_negative_tolerance_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="may not be negative"):
            self._session(flatten=-1)
