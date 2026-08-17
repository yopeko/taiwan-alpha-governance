"""Boundary tests for the M4 Taiwan rules reference implementation.

Band edges, the minimum commission, the NT$10,000 capital policy and the
rejection paths all get explicit cases, because those are where a cost or
rules engine silently produces plausible-looking but wrong numbers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from m4.rules import (
    BOARD_LOT,
    BrokerTerms,
    LotType,
    OrderRequest,
    OrderValidity,
    RuleError,
    Side,
    classify_lot,
    cost_drag,
    is_on_tick,
    price_limits,
    resolve_price_limits,
    round_to_tick,
    settlement_date,
    tick_size,
    trade_costs,
    validate_order,
)

D = Decimal


class TestTickSize:
    @pytest.mark.parametrize(
        "price,expected",
        [
            ("0.01", "0.01"),
            ("9.99", "0.01"),
            ("10", "0.05"),  # band edge is inclusive of the higher band
            ("49.95", "0.05"),
            ("50", "0.1"),
            ("99.9", "0.1"),
            ("100", "0.5"),
            ("499.5", "0.5"),
            ("500", "1"),
            ("999", "1"),
            ("1000", "5"),
            ("10795", "5"),
        ],
    )
    def test_bands_match_captured_official_prices(self, price, expected):
        assert tick_size(D(price)) == D(expected)

    def test_non_positive_price_rejected(self):
        with pytest.raises(RuleError):
            tick_size(D("0"))

    def test_on_tick_detection(self):
        assert is_on_tick(D("25.05"))
        assert not is_on_tick(D("25.01"))  # 0.01 is an ETF tick, not common stock


class TestRoundToTick:
    def test_buy_rounds_down_and_sell_rounds_up(self):
        assert round_to_tick(D("25.07"), side=Side.BUY) == D("25.05")
        assert round_to_tick(D("25.07"), side=Side.SELL) == D("25.10")

    def test_nearest_without_side(self):
        assert round_to_tick(D("25.07")) == D("25.05")
        assert round_to_tick(D("25.08")) == D("25.10")

    def test_already_on_tick_is_unchanged(self):
        assert round_to_tick(D("500"), side=Side.BUY) == D("500")

    def test_rounding_across_a_band_boundary_resnaps(self):
        # 99.96 sits in the 0.1 band; rounding up reaches 100.0 where the
        # tick becomes 0.5, and 100.0 is a valid multiple of 0.5.
        assert round_to_tick(D("99.96"), side=Side.SELL) == D("100.0")


class TestPriceLimits:
    def test_ten_percent_snapped_to_tick(self):
        up, down = price_limits(D("100"))
        assert up == D("110.0")
        assert down == D("90.0")

    def test_limits_never_exceed_ten_percent(self):
        for raw in ("7.77", "23.4", "56.5", "133", "612", "1225"):
            reference = D(raw)
            up, down = price_limits(reference)
            assert (up - reference) / reference <= Decimal("0.10")
            assert (reference - down) / reference <= Decimal("0.10")
            assert is_on_tick(up)
            assert is_on_tick(down)

    def test_matches_official_published_example(self):
        # From the captured TWT49U record for 2402 on 2025-08-01:
        # reference 39.12 -> limit up 43.00, limit down 35.25.
        up, down = price_limits(D("39.12"))
        assert up == D("43.00")
        assert down == D("35.25")


class TestLots:
    def test_board_lot_multiples(self):
        assert classify_lot(BOARD_LOT) is LotType.BOARD
        assert classify_lot(3000) is LotType.BOARD

    def test_odd_lot_range(self):
        assert classify_lot(1) is LotType.ODD
        assert classify_lot(999) is LotType.ODD

    def test_mixed_quantity_rejected(self):
        with pytest.raises(RuleError):
            classify_lot(1500)

    def test_zero_rejected(self):
        with pytest.raises(RuleError):
            classify_lot(0)


class TestSettlement:
    SESSIONS = [
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 6),
        date(2025, 1, 7),
        date(2025, 1, 8),
    ]

    def test_t_plus_two_counts_sessions_not_calendar_days(self):
        # Thursday 1/2 settles on Monday 1/6, skipping the weekend.
        assert settlement_date(date(2025, 1, 2), self.SESSIONS) == date(2025, 1, 6)

    def test_non_session_trade_date_rejected(self):
        with pytest.raises(RuleError):
            settlement_date(date(2025, 1, 4), self.SESSIONS)

    def test_calendar_too_short_fails_closed(self):
        with pytest.raises(RuleError):
            settlement_date(date(2025, 1, 8), self.SESSIONS)


class TestCosts:
    def test_buy_has_no_sell_tax(self):
        result = trade_costs(side=Side.BUY, price=D("50"), quantity=1000)
        assert result.tax == 0
        assert result.commission == D("71")  # 50000 * 0.001425 = 71.25 -> 71
        assert result.net_cash_delta == D("-50071")

    def test_sell_charges_tax(self):
        result = trade_costs(side=Side.SELL, price=D("50"), quantity=1000)
        assert result.tax == D("150")  # 50000 * 0.003
        assert result.net_cash_delta == D("50000") - D("71") - D("150")

    def test_minimum_commission_applies_to_small_orders(self):
        result = trade_costs(side=Side.BUY, price=D("20"), quantity=100)
        assert result.minimum_commission_applied is True
        assert result.commission == D("20")  # raw would be 2.85

    def test_minimum_commission_not_applied_when_exceeded(self):
        result = trade_costs(side=Side.BUY, price=D("100"), quantity=1000)
        assert result.minimum_commission_applied is False
        assert result.commission == D("142")

    def test_discount_is_configurable(self):
        terms = BrokerTerms(commission_discount=Decimal("0.6"))
        result = trade_costs(
            side=Side.BUY, price=D("100"), quantity=1000, terms=terms
        )
        assert result.commission == D("85")  # 142.5 * 0.6 = 85.5 -> 85

    def test_terms_carry_their_evidence_state(self):
        result = trade_costs(side=Side.BUY, price=D("100"), quantity=1000)
        assert result.terms_evidence_state == "assumption"

    def test_negative_terms_rejected(self):
        with pytest.raises(RuleError):
            BrokerTerms(commission_rate=Decimal("-0.001"))

    def test_zero_quantity_rejected(self):
        with pytest.raises(RuleError):
            trade_costs(side=Side.BUY, price=D("100"), quantity=0)


class TestCostDragAtPolicyCapital:
    """The NT$10,000 policy is where the minimum commission bites hardest."""

    def test_odd_lot_at_policy_capital_is_dominated_by_minimum_fee(self):
        # 45% of NT$10,000 is NT$4,500: about 90 shares of a NT$50 stock.
        drag = cost_drag(price=D("50"), quantity=90)
        assert drag > Decimal("0.009")  # over 0.9% round trip

    def test_drag_falls_as_notional_rises(self):
        small = cost_drag(price=D("50"), quantity=90)
        large = cost_drag(price=D("50"), quantity=1000)
        assert large < small


class TestOrderValidation:
    def _request(self, **overrides):
        base = dict(
            symbol="2330",
            side=Side.BUY,
            quantity=1000,
            limit_price=D("100.0"),
            reference_price=D("100"),
            validity=OrderValidity.ROD,
        )
        base.update(overrides)
        return OrderRequest(**base)

    def test_valid_order_accepted(self):
        assert validate_order(self._request()).accepted

    def test_price_above_limit_up_rejected(self):
        check = validate_order(self._request(limit_price=D("111.0")))
        assert not check.accepted
        assert any("limit-up" in r for r in check.reasons)

    def test_price_below_limit_down_rejected(self):
        check = validate_order(self._request(limit_price=D("89.0")))
        assert not check.accepted
        assert any("limit-down" in r for r in check.reasons)

    def test_off_tick_price_rejected(self):
        check = validate_order(self._request(limit_price=D("100.1")))
        assert not check.accepted
        assert any("tick grid" in r for r in check.reasons)

    def test_odd_lot_must_be_rod(self):
        check = validate_order(
            self._request(quantity=100, validity=OrderValidity.IOC)
        )
        assert not check.accepted
        assert any("ROD" in r for r in check.reasons)

    def test_odd_lot_rod_accepted(self):
        assert validate_order(self._request(quantity=100)).accepted

    def test_mixed_quantity_rejected(self):
        check = validate_order(self._request(quantity=1500))
        assert not check.accepted

    def test_reasons_are_reported_together(self):
        check = validate_order(self._request(quantity=1500, limit_price=D("111.1")))
        assert len(check.reasons) >= 2


class TestResolvePriceLimits:
    """Published limits win; ex-rights sessions fail closed without them."""

    def test_publisher_values_are_preferred(self):
        up, down, basis = resolve_price_limits(
            D("39.12"), official_limit_up=D("43.00"), official_limit_down=D("35.25")
        )
        assert (up, down) == (D("43.00"), D("35.25"))
        assert basis == "publisher-exact"

    def test_publisher_values_win_even_when_they_differ_from_the_formula(self):
        # 4927 on its ex-rights day: the official limit-up is +15.96%, which
        # the standard rule would never produce.
        up, _, basis = resolve_price_limits(
            D("27.38"), official_limit_up=D("31.75"), official_limit_down=D("24.65")
        )
        assert up == D("31.75")
        assert basis == "publisher-exact"

    def test_ordinary_session_falls_back_to_computation(self):
        up, down, basis = resolve_price_limits(D("100"))
        assert (up, down) == (D("110.0"), D("90.0"))
        assert basis == "computed-standard-10pct"

    def test_ex_rights_without_published_limits_is_blocked(self):
        with pytest.raises(RuleError):
            resolve_price_limits(D("100"), is_ex_rights_session=True)
