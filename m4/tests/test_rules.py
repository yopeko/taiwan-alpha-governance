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
    has_price_limit,
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


class TestCapitalReductionResumption:
    """Every published limit of every reduction in the M3 window.

    Captured from the exchange's own 股票減資恢復買賣參考價格 announcements so
    the check does not need the warehouse to be built. Each row is
    (symbol, prior close before the halt, resumption reference, limit up,
    limit down).
    """

    OFFICIAL = [
        ("2025", "10.50", "17.09", "18.75", "15.40"),
        ("2371", "40.15", "41.73", "45.90", "37.60"),
        ("4414", "3.17", "12.03", "13.20", "10.85"),
        ("2101", "40.00", "44.08", "48.45", "39.70"),
        ("3321", "7.62", "13.93", "15.30", "12.55"),
        ("6120", "10.90", "11.00", "12.10", "9.90"),
        ("2352", "30.15", "34.57", "38.00", "31.15"),
        ("2489", "13.35", "13.73", "15.10", "12.40"),
        ("2607", "35.00", "60.00", "66.00", "54.00"),
        ("3057", "9.32", "14.31", "15.70", "12.90"),
        ("9924", "44.80", "53.50", "58.80", "48.15"),
        ("2314", "10.30", "24.46", "26.90", "22.05"),
        ("2832", "36.00", "47.14", "51.80", "42.45"),
        ("1808", "34.45", "37.16", "40.85", "33.45"),
        ("9927", "52.40", "69.11", "76.00", "62.20"),
        ("8103", "74.70", "86.11", "94.70", "77.50"),
        ("3593", "8.10", "13.50", "14.85", "12.15"),
        ("1414", "17.45", "18.27", "20.05", "16.45"),
        ("2380", "6.60", "23.86", "26.20", "21.50"),
        ("1459", "11.85", "12.46", "13.70", "11.25"),
    ]

    @pytest.mark.parametrize("symbol,prior,reference,up,down", OFFICIAL)
    def test_the_standard_rule_reproduces_every_official_limit(
        self, symbol, prior, reference, up, down
    ):
        got_up, got_down, basis = resolve_price_limits(
            D(prior),
            is_reduction_resumption_session=True,
            resumption_reference_price=D(reference),
        )
        assert (got_up, got_down) == (D(up), D(down)), symbol
        assert basis == "computed-from-publisher-resumption-reference"

    @pytest.mark.parametrize("symbol,prior,reference,up,down", OFFICIAL)
    def test_the_prior_close_would_have_been_wrong_every_time(
        self, symbol, prior, reference, up, down
    ):
        """Why the resumption reference is required rather than optional.

        If the prior close were an acceptable base, this rule could quietly
        default to it. It never once produces the published limit, so a caller
        that supplies the wrong one must be stopped rather than served.
        """

        wrong_up, wrong_down = price_limits(D(prior))
        assert (wrong_up, wrong_down) != (D(up), D(down)), symbol

    def test_a_resumption_without_the_reference_price_is_blocked(self):
        with pytest.raises(RuleError):
            resolve_price_limits(D("30.15"), is_reduction_resumption_session=True)

    def test_published_limits_still_win_over_the_computation(self):
        up, down, basis = resolve_price_limits(
            D("30.15"),
            official_limit_up=D("38.00"),
            official_limit_down=D("31.15"),
            is_reduction_resumption_session=True,
        )
        assert (up, down) == (D("38.00"), D("31.15"))
        assert basis == "publisher-exact"


class TestNewListingExemption:
    """A newly listed security trades without a price limit for five sessions."""

    SESSIONS = [date(2025, 1, d) for d in (2, 3, 6, 7, 8, 9, 10, 13, 14)]

    def test_no_limit_on_the_listing_day(self):
        applies, basis = has_price_limit(
            listing_date=date(2025, 1, 2),
            as_of_session=date(2025, 1, 2),
            sessions=self.SESSIONS,
        )
        assert applies is False
        assert basis == "exempt-new-listing-first-five-sessions"

    def test_no_limit_on_the_fifth_session(self):
        applies, _ = has_price_limit(
            listing_date=date(2025, 1, 2),
            as_of_session=date(2025, 1, 8),
            sessions=self.SESSIONS,
        )
        assert applies is False

    def test_limit_returns_on_the_sixth_session(self):
        applies, basis = has_price_limit(
            listing_date=date(2025, 1, 2),
            as_of_session=date(2025, 1, 9),
            sessions=self.SESSIONS,
        )
        assert applies is True
        assert basis == "ordinary-ten-percent-limit"

    def test_a_long_listed_security_has_the_ordinary_limit(self):
        applies, _ = has_price_limit(
            listing_date=date(2025, 1, 2),
            as_of_session=date(2025, 1, 14),
            sessions=self.SESSIONS,
        )
        assert applies is True

    def test_unknown_listing_date_is_blocked_not_guessed(self):
        applies, basis = has_price_limit(
            listing_date=None,
            as_of_session=date(2025, 1, 8),
            sessions=self.SESSIONS,
        )
        assert applies is False
        assert basis == "blocked-unknown-listing-date"

    def test_a_session_outside_the_calendar_is_blocked(self):
        applies, basis = has_price_limit(
            listing_date=date(2025, 1, 2),
            as_of_session=date(2025, 1, 4),
            sessions=self.SESSIONS,
        )
        assert applies is False
        assert basis == "blocked-session-not-in-calendar"

    def test_exemption_counts_sessions_not_calendar_days(self):
        # 1/2 to 1/9 is seven calendar days but five sessions.
        from m4.rules import sessions_since_listing

        assert sessions_since_listing(
            date(2025, 1, 2), date(2025, 1, 9), self.SESSIONS
        ) == 5
