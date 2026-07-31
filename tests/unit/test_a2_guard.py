"""The A-2 pressure-invariance guard, applied to every module that classifies.

§5.1 requires classification to be a pure function of the market. §21 requires
that to be tested. This is the single place that test lives, so strengthening
the guard strengthens every module at once — the previous arrangement copied a
weaker check into five test files and multiplied the blind spot instead.

`test_the_guard_catches_what_defeated_its_predecessor` is the important one: it
pins the specific mutation an adversarial review used to walk firm state into a
significance threshold with all 65 experiment tests still green.
"""

import importlib
import textwrap

import pytest
from a2_guard import FIRM_STATE_FIELDS, FIRM_STATE_TYPES, assert_pressure_blind

# Every module that decides what the evidence supports.
PRESSURE_BLIND_MODULES = [
    "trading_firm.classification",
    "trading_firm.arbiter",
    "trading_firm.agents.bench",
    "trading_firm.research.experiments",
    "trading_firm.research.analogs",
    # §30 surveillance, market side: everything that observes, classifies, or
    # sets a significance threshold is a pure function of the market (§5.1).
    # The post-entry side (surveillance.monitoring, surveillance.positions.*)
    # is deliberately NOT here — it reads position state by design (§30.10)
    # and is fenced by TestContradictionStaysOutOfTheMarketSide instead.
    "trading_firm.surveillance.schemas",
    "trading_firm.surveillance.freshness",
    "trading_firm.surveillance.state_builder",
    "trading_firm.surveillance.materiality",
    "trading_firm.surveillance.technical.structure",
    "trading_firm.surveillance.technical.indicators",
    "trading_firm.surveillance.technical.liquidity",
    "trading_firm.surveillance.technical.regime",
]


@pytest.mark.parametrize("module_name", PRESSURE_BLIND_MODULES)
def test_module_cannot_reach_firm_state(module_name: str) -> None:
    assert_pressure_blind(importlib.import_module(module_name))


class TestTheGuardItself:
    """A guard nobody has attacked is a guard nobody knows the strength of."""

    @staticmethod
    def _module_from(source: str, tmp_path, name: str):
        path = tmp_path / f"{name}.py"
        path.write_text(textwrap.dedent(source))
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_clean_module_passes(self, tmp_path) -> None:
        m = self._module_from(
            '''
            """Classifies things."""
            def classify(market):
                return market
            ''',
            tmp_path,
            "clean_mod",
        )
        assert_pressure_blind(m)

    def test_the_guard_catches_what_defeated_its_predecessor(self, tmp_path) -> None:
        """The exact escape: import AccountState, not FirmSnapshot, and let a
        session loss loosen the significance bar. The old guard matched only the
        literal 'FirmSnapshot' and passed this."""
        m = self._module_from(
            '''
            """Innocent-looking."""
            from trading_firm.models import AccountState

            def required_p_value(alpha, account: AccountState):
                if account.session_realized_loss > 0:
                    return alpha * 3
                return alpha
            ''',
            tmp_path,
            "escaping_mod",
        )
        with pytest.raises(AssertionError, match="AccountState"):
            assert_pressure_blind(m)

    def test_an_aliased_import_does_not_hide_firm_state(self, tmp_path) -> None:
        m = self._module_from(
            '''
            """Aliased."""
            from trading_firm.models import AccountState as _A

            def score(x, a: _A):
                return a.closed_equity
            ''',
            tmp_path,
            "aliased_mod",
        )
        with pytest.raises(AssertionError):
            assert_pressure_blind(m)

    def test_a_bare_field_reference_is_caught_without_any_import(self, tmp_path) -> None:
        """The subtler escape — pass the values individually rather than the
        object, so no forbidden type is ever imported."""
        m = self._module_from(
            '''
            """No imports at all."""
            def ceiling(market, session_realized_loss):
                return 0 if session_realized_loss else 5
            ''',
            tmp_path,
            "bare_field_mod",
        )
        with pytest.raises(AssertionError, match="session_realized_loss"):
            assert_pressure_blind(m)

    def test_prose_may_discuss_firm_state(self, tmp_path) -> None:
        """A docstring explaining the rule must not trip the rule. This module's
        own docstring names every forbidden term."""
        m = self._module_from(
            '''
            """This module must never read closed_equity or AccountState.

            Firm state such as session_realized_loss reaches the risk gate only.
            """
            def classify(market):
                return market
            ''',
            tmp_path,
            "prose_mod",
        )
        assert_pressure_blind(m)

    def test_the_vocabulary_covers_more_than_one_type(self) -> None:
        # The original guard's whole failure was checking a single name.
        assert len(FIRM_STATE_TYPES) >= 5
        assert {"closed_equity", "session_realized_loss"} <= FIRM_STATE_FIELDS
