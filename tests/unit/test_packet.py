"""Market State Packet determinism and checksums (§6A, §21, §10.3).

§21 requires "independent-context packet checksum" as a unit test: §6.2's
independence protocol is worthless if the two traders can be handed different
data under the same name, and §6A requires both to receive "the exact same
packet checksum".
"""

import datetime as dt
from decimal import Decimal

import pytest

from trading_firm.models import AccountState, DrawdownState
from trading_firm.packet import FirmSnapshot, MarketSnapshot, MarketStatePacket

UTC = dt.UTC


def market(**overrides) -> MarketSnapshot:
    base = dict(
        instrument="GBP_USD",
        observed_at=dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC),
        session_date=dt.date(2026, 7, 30),
        session_phase="briefing",
        regime="compression",
        volatility_state="low",
        bid=Decimal("1.28450"),
        ask=Decimal("1.28462"),
        spread_pips=Decimal("1.2"),
        feature_version="session_features_v1",
        features={"session_features_v1.asian_width_pips": Decimal("38")},
        analog_sample_size=40,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def firm(**overrides) -> FirmSnapshot:
    base = dict(
        closed_equity=Decimal("250"),
        tier_anchor=Decimal("250"),
        drawdown_state=DrawdownState.NORMAL,
    )
    base.update(overrides)
    return FirmSnapshot(**base)


class TestDeterminism:
    def test_identical_inputs_give_identical_checksums(self) -> None:
        assert market().checksum == market().checksum
        assert MarketStatePacket(market(), firm()).packet_id == (
            MarketStatePacket(market(), firm()).packet_id
        )

    def test_checksum_is_stable_under_decimal_spelling(self) -> None:
        # Decimal("38") and Decimal("38.00") are the same observation; a packet
        # that hashed them differently would make two traders' identical data
        # look divergent in the audit trail.
        a = market(features={"session_features_v1.asian_width_pips": Decimal("38")})
        b = market(features={"session_features_v1.asian_width_pips": Decimal("38.00")})
        assert a.checksum == b.checksum

    def test_checksum_is_stable_under_feature_insertion_order(self) -> None:
        keys = ["session_features_v1.asian_high", "session_features_v1.asian_low"]
        forward = market(features={keys[0]: Decimal("1.2860"), keys[1]: Decimal("1.2820")})
        reverse = market(features={keys[1]: Decimal("1.2820"), keys[0]: Decimal("1.2860")})
        assert forward.checksum == reverse.checksum

    def test_timezone_representation_does_not_change_the_checksum(self) -> None:
        london = dt.datetime(2026, 7, 30, 8, 40, tzinfo=dt.timezone(dt.timedelta(hours=1)))
        assert market(observed_at=london).checksum == market().checksum

    @pytest.mark.parametrize(
        "override",
        [
            {"bid": Decimal("1.28451")},
            {"spread_pips": Decimal("1.3")},
            {"regime": "expansion"},
            {"analog_sample_size": 41},
            {"data_fresh": False},
            {"high_impact_event_active": True},
            {"features": {"session_features_v1.asian_width_pips": Decimal("39")}},
        ],
    )
    def test_any_material_change_moves_the_checksum(self, override) -> None:
        assert market(**override).checksum != market().checksum


class TestPacketIdentity:
    def test_market_id_ignores_firm_state(self) -> None:
        rich = firm(closed_equity=Decimal("9000"))
        poor = firm(closed_equity=Decimal("201"), drawdown_state=DrawdownState.RESTRICTED)
        assert MarketStatePacket(market(), rich).market_id == (
            MarketStatePacket(market(), poor).market_id
        )

    def test_packet_id_covers_both_halves(self) -> None:
        rich = firm(closed_equity=Decimal("9000"))
        assert MarketStatePacket(market(), rich).packet_id != (
            MarketStatePacket(market(), firm()).packet_id
        )

    def test_verify_accepts_the_issued_id(self) -> None:
        packet = MarketStatePacket(market(), firm())
        packet.verify(packet.packet_id)  # does not raise

    def test_verify_fails_closed_on_mutation(self) -> None:
        issued = MarketStatePacket(market(), firm()).packet_id
        # A whole-quote move, so the mutation is detected by the checksum rather
        # than incidentally by the malformed-quote guard.
        mutated = MarketStatePacket(
            market(bid=Decimal("1.29000"), ask=Decimal("1.29012")), firm()
        )
        with pytest.raises(ValueError, match="checksum mismatch"):
            mutated.verify(issued)


class TestSeparation:
    def test_firm_snapshot_has_no_target_or_progress_field(self) -> None:
        """§3.5 / A-2: the firm cannot represent a target, so no field can carry
        one into the packet. Named fields, so a future addition trips this."""
        forbidden = {
            "profit_target",
            "target",
            "goal",
            "days_elapsed",
            "days_remaining",
            "deadline",
            "cumulative_return",
            "progress_to_target",
            "return_to_date",
        }
        present = set(FirmSnapshot.__dataclass_fields__)
        assert not (present & forbidden), (
            f"FirmSnapshot gained a target/progress field {sorted(present & forbidden)}: "
            f"§3.5 forbids the firm from representing a target at all"
        )

    def test_market_snapshot_carries_no_account_field(self) -> None:
        forbidden = {"closed_equity", "tier_anchor", "session_realized_loss", "open_positions"}
        assert not (set(MarketSnapshot.__dataclass_fields__) & forbidden)

    def test_from_account_round_trips_the_reconciled_facts(self) -> None:
        account = AccountState(
            closed_equity=Decimal("241.50"),
            tier_anchor=Decimal("250"),
            session_realized_loss=Decimal("8.50"),
            trades_this_session=1,
            open_positions=1,
            reconciled=True,
        )
        snapshot = FirmSnapshot.from_account(account, DrawdownState.CAUTION)
        assert snapshot.closed_equity == Decimal("241.50")
        assert snapshot.session_realized_loss == Decimal("8.50")
        assert snapshot.drawdown_state is DrawdownState.CAUTION


class TestFailClosed:
    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            market(observed_at=dt.datetime(2026, 7, 30, 7, 40))

    def test_inverted_quote_rejected(self) -> None:
        with pytest.raises(ValueError, match="malformed quote"):
            market(bid=Decimal("1.2850"), ask=Decimal("1.2840"))

    def test_negative_analog_sample_rejected(self) -> None:
        with pytest.raises(ValueError, match="analog_sample_size"):
            market(analog_sample_size=-1)
