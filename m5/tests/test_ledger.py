"""M0 section 6 ledger invariants, one test class per invariant.

The whole point of M5 is that a strategy which is impossible in the market
should be impossible in the simulator. Each class below names the invariant it
guards and then tries to break it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from m4.rules import BrokerTerms, Side
from m5.ledger import (
    LEDGER_VERSION,
    Ledger,
    LedgerError,
    MarketConditions,
    OrderRequest,
    PositionPlan,
    POLICY_HARD_RISK_CAP,
    TRADABLE_STATE,
    every_entry_traces_to_a_fill,
    journal_is_balanced,
    plan_position,
)

D = Decimal

# Long enough that a trade on the sessions these tests use can always be
# settled; a trade the calendar cannot settle is refused, and that is checked
# on its own rather than leaking into every other case.
SESSIONS = [
    date(2025, 1, d) for d in (2, 3, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17)
]


def ledger(**overrides) -> Ledger:
    kwargs = dict(opening_cash=D("10000"), sessions=SESSIONS)
    kwargs.update(overrides)
    return Ledger(**kwargs)


def open_market(session: date, **overrides) -> MarketConditions:
    kwargs = dict(
        session=session, session_is_open=True, tradability_state=TRADABLE_STATE
    )
    kwargs.update(overrides)
    return MarketConditions(**kwargs)


def buy(session: date, quantity=100, price="50", order_id="o1", fill_id="f1"):
    return OrderRequest(
        order_id=order_id,
        fill_id=fill_id,
        session=session,
        symbol="2330",
        side=Side.BUY,
        quantity=quantity,
        limit_price=D(price),
    )


def sell(session: date, quantity=100, price="50", order_id="o2", fill_id="f2"):
    return OrderRequest(
        order_id=order_id,
        fill_id=fill_id,
        session=session,
        symbol="2330",
        side=Side.SELL,
        quantity=quantity,
        limit_price=D(price),
    )


class TestInvariantOneNavIdentity:
    """Cash plus pending plus market value must equal NAV."""

    def test_an_untouched_ledger_is_its_opening_cash(self):
        book = ledger()
        assert book.nav({}) == D("10000")

    def test_the_identity_holds_after_a_buy(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        assert journal_is_balanced(book, {"2330": D("50")})

    def test_the_identity_holds_across_settlement(self):
        """Settlement moves money between components without creating any."""

        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        before = book.nav({"2330": D("50")})
        book.settle_through(SESSIONS[2])
        assert book.pending == []
        assert book.nav({"2330": D("50")}) == before

    def test_the_identity_holds_after_a_round_trip(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        book.settle_through(SESSIONS[2])
        book.execute(sell(SESSIONS[3]), open_market(SESSIONS[3]))
        assert journal_is_balanced(book, {})
        book.settle_through(SESSIONS[5])
        assert journal_is_balanced(book, {})

    def test_costs_are_the_only_thing_that_leaves(self):
        """A flat round trip at one price loses exactly costs plus slippage.

        This is the arithmetic M0 says a naive backtest gets wrong: it would
        report zero.
        """

        book = ledger()
        book.execute(buy(SESSIONS[0], quantity=100, price="50"), open_market(SESSIONS[0]))
        book.settle_through(SESSIONS[2])
        book.execute(sell(SESSIONS[3], quantity=100, price="50"), open_market(SESSIONS[3]))
        book.settle_through(SESSIONS[5])
        # Buy at 50.10 and sell at 49.90 on 100 shares is 20 of slippage;
        # two minimum commissions of 20; tax of 14 on gross 4990.
        assert book.settled_cash == D("10000") - D("20") - D("20") - D("20") - D("14")
        assert book.nav({}) == book.settled_cash

    def test_a_held_security_without_a_mark_is_refused_not_valued_at_zero(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        with pytest.raises(LedgerError):
            book.nav({})


class TestInvariantTwoLongOnlyIntegerShares:
    """Shares may never go negative and are always whole."""

    def test_selling_without_a_position_is_refused(self):
        book = ledger()
        result = book.execute(sell(SESSIONS[0]), open_market(SESSIONS[0]))
        assert result.state == "rejected"
        assert result.reason == "no-position-to-sell"

    def test_selling_more_than_held_is_refused(self):
        book = ledger()
        book.execute(buy(SESSIONS[0], quantity=100), open_market(SESSIONS[0]))
        result = book.execute(
            sell(SESSIONS[1], quantity=200), open_market(SESSIONS[1])
        )
        assert result.state == "rejected"
        assert result.reason == "sell-exceeds-holding"
        assert book.positions["2330"].shares == 100

    def test_share_counts_stay_integers(self):
        book = ledger()
        book.execute(buy(SESSIONS[0], quantity=137), open_market(SESSIONS[0]))
        assert isinstance(book.positions["2330"].shares, int)

    def test_a_mixed_lot_is_refused_rather_than_split_silently(self):
        book = ledger()
        result = book.execute(
            buy(SESSIONS[0], quantity=1500), open_market(SESSIONS[0])
        )
        assert result.state == "rejected"
        assert result.reason == "invalid-lot-size"


class TestInvariantThreeImpossibleTradesCannotFill:
    """Not a session, not tradable, or outside the band: no fill."""

    @pytest.mark.parametrize(
        "state",
        ["blocked", "restricted", "ineligible", "unknown", "no-coverage"],
    )
    def test_every_non_eligible_warehouse_state_refuses(self, state):
        book = ledger()
        result = book.execute(
            buy(SESSIONS[0]),
            open_market(SESSIONS[0], tradability_state=state),
        )
        assert result.state == "rejected"
        assert result.reason == f"not-tradable-{state}"

    def test_a_closed_session_refuses(self):
        book = ledger()
        result = book.execute(
            buy(SESSIONS[0]), open_market(SESSIONS[0], session_is_open=False)
        )
        assert result.state == "rejected"
        assert result.reason == "not-a-trading-session"

    def test_a_price_through_the_limit_up_refuses(self):
        book = ledger()
        result = book.execute(
            buy(SESSIONS[0], price="60"),
            open_market(SESSIONS[0], limit_up=D("55")),
        )
        assert result.state == "rejected"
        assert result.reason == "limit-price-above-limit-up"

    def test_a_price_through_the_limit_down_refuses(self):
        book = ledger()
        result = book.execute(
            sell(SESSIONS[0], price="40"),
            open_market(SESSIONS[0], limit_down=D("45")),
        )
        assert result.state == "rejected"
        assert result.reason == "limit-price-below-limit-down"

    def test_no_liquidity_is_a_no_fill_not_a_free_fill(self):
        book = ledger()
        result = book.execute(
            buy(SESSIONS[0]), open_market(SESSIONS[0], available_quantity=0)
        )
        assert result.state == "rejected"
        assert result.reason == "no-liquidity-no-fill"

    def test_thin_liquidity_fills_partially(self):
        book = ledger()
        result = book.execute(
            buy(SESSIONS[0], quantity=1000, price="5"),
            open_market(SESSIONS[0], available_quantity=300),
        )
        assert result.state == "partially-filled"
        assert result.filled_quantity == 300
        assert book.positions["2330"].shares == 300

    def test_a_refusal_never_moves_cash(self):
        book = ledger()
        book.execute(
            buy(SESSIONS[0]), open_market(SESSIONS[0], tradability_state="blocked")
        )
        assert book.journal == []
        assert book.settled_cash == D("10000")
        assert book.positions == {}

    def test_selling_what_was_bought_today_is_day_trading_and_refused(self):
        """M0 section 8 prohibits 現股當沖."""

        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        result = book.execute(sell(SESSIONS[0]), open_market(SESSIONS[0]))
        assert result.state == "rejected"
        assert result.reason == "same-session-sale-is-day-trading"

    def test_selling_the_next_session_is_allowed(self):
        """The restriction is on the same session, not on settlement.

        Holding shares unsellable until T+2 would model a rule Taiwan does not
        have, and would silently make every two-day strategy untestable.
        """

        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        result = book.execute(sell(SESSIONS[1]), open_market(SESSIONS[1]))
        assert result.state == "filled"

    def test_an_order_for_another_session_is_refused(self):
        book = ledger()
        result = book.execute(buy(SESSIONS[0]), open_market(SESSIONS[1]))
        assert result.state == "rejected"
        assert result.reason == "order-session-differs-from-market-session"


class TestInvariantFourEveryFeeTracesToAFill:
    def test_each_journal_entry_names_its_order_and_fill(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        book.settle_through(SESSIONS[2])
        book.execute(sell(SESSIONS[3]), open_market(SESSIONS[3]))
        book.settle_through(SESSIONS[5])
        assert book.journal
        assert every_entry_traces_to_a_fill(book.journal)

    def test_commission_and_tax_are_separate_lines(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        book.execute(sell(SESSIONS[1]), open_market(SESSIONS[1]))
        kinds = [entry.kind for entry in book.journal]
        assert kinds.count("commission") == 2
        assert kinds.count("tax") == 1  # a buy pays no securities tax

    def test_cash_is_derived_from_the_journal_alone(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        recomputed = book.opening_cash + sum(e.amount for e in book.journal)
        assert book.settled_cash == recomputed


class TestInvariantFiveUnsettledProceedsAreNotBuyingPower:
    def test_sale_proceeds_do_not_fund_the_next_buy(self):
        book = ledger(opening_cash=D("6000"))
        book.execute(
            buy(SESSIONS[0], quantity=100, price="50"), open_market(SESSIONS[0])
        )
        book.settle_through(SESSIONS[2])
        book.execute(
            sell(SESSIONS[3], quantity=100, price="50"), open_market(SESSIONS[3])
        )
        # The proceeds exist but have not landed.
        assert book.unsettled_proceeds > 0
        power_before = book.buying_power
        assert power_before < book.nav({})
        result = book.execute(
            OrderRequest(
                order_id="o9",
                fill_id="f9",
                session=SESSIONS[3],
                symbol="2454",
                side=Side.BUY,
                quantity=100,
                limit_price=D("55"),
            ),
            open_market(SESSIONS[3]),
        )
        assert result.state == "rejected"
        assert result.reason == "insufficient-buying-power"

    def test_they_become_spendable_once_settled(self):
        book = ledger(opening_cash=D("6000"))
        book.execute(
            buy(SESSIONS[0], quantity=100, price="50"), open_market(SESSIONS[0])
        )
        book.settle_through(SESSIONS[2])
        book.execute(
            sell(SESSIONS[3], quantity=100, price="50"), open_market(SESSIONS[3])
        )
        book.settle_through(SESSIONS[5])
        result = book.execute(
            OrderRequest(
                order_id="o9",
                fill_id="f9",
                session=SESSIONS[5],
                symbol="2454",
                side=Side.BUY,
                quantity=100,
                limit_price=D("55"),
            ),
            open_market(SESSIONS[5]),
        )
        assert result.state == "filled"

    def test_committed_cash_cannot_be_spent_twice(self):
        book = ledger(opening_cash=D("6000"))
        book.execute(
            buy(SESSIONS[0], quantity=100, price="50"), open_market(SESSIONS[0])
        )
        second = book.execute(
            OrderRequest(
                order_id="o3",
                fill_id="f3",
                session=SESSIONS[0],
                symbol="2454",
                side=Side.BUY,
                quantity=100,
                limit_price=D("5"),
            ),
            open_market(SESSIONS[0]),
        )
        assert second.state == "filled"
        third = book.execute(
            OrderRequest(
                order_id="o4",
                fill_id="f4",
                session=SESSIONS[0],
                symbol="3008",
                side=Side.BUY,
                quantity=100,
                limit_price=D("50"),
            ),
            open_market(SESSIONS[0]),
        )
        assert third.state == "rejected"
        assert third.reason == "insufficient-buying-power"


class TestInvariantSixReplayCannotDoubleCount:
    def test_the_same_fill_id_is_refused_the_second_time(self):
        book = ledger()
        first = book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        assert first.state == "filled"
        again = book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        assert again.state == "rejected"
        assert again.reason == "duplicate-fill-id"

    def test_a_replay_leaves_cash_and_shares_unchanged(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        cash, shares, entries = (
            book.settled_cash,
            book.positions["2330"].shares,
            len(book.journal),
        )
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        assert book.settled_cash == cash
        assert book.positions["2330"].shares == shares
        assert len(book.journal) == entries

    def test_settlement_cannot_run_backwards(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        book.settle_through(SESSIONS[3])
        with pytest.raises(LedgerError):
            book.settle_through(SESSIONS[1])

    def test_settling_twice_does_not_post_twice(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        book.settle_through(SESSIONS[2])
        cash = book.settled_cash
        book.settle_through(SESSIONS[2])
        assert book.settled_cash == cash


class TestSettlementIsCountedInSessions:
    def test_t_plus_two_skips_the_weekend(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        # 2025-01-02 is a Thursday; two sessions later is Monday 2025-01-06.
        assert book.pending[0].settles_on == date(2025, 1, 6)

    def test_a_calendar_that_ends_too_soon_refuses_rather_than_raising(self):
        """A backtest running off the end of its calendar records a refusal.

        Raising would abort the run; filling would invent a settlement date
        that the calendar cannot supply.
        """

        book = Ledger(opening_cash=D("10000"), sessions=SESSIONS[:1])
        result = book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        assert result.state == "rejected"
        assert result.reason == "calendar-too-short-to-settle"
        assert book.journal == []

    def test_a_ledger_without_a_calendar_is_refused(self):
        with pytest.raises(LedgerError):
            Ledger(opening_cash=D("10000"), sessions=[])


class TestSlippageAlwaysWorksAgainstTheAccount:
    def test_a_buy_pays_more_than_the_limit(self):
        book = ledger()
        result = book.execute(
            buy(SESSIONS[0], price="50"), open_market(SESSIONS[0])
        )
        assert result.fill_price > D("50")

    def test_a_sale_receives_less_than_the_limit(self):
        book = ledger()
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        result = book.execute(
            sell(SESSIONS[1], price="50"), open_market(SESSIONS[1])
        )
        assert result.fill_price < D("50")


class TestNavSeriesAndDrawdown:
    def test_high_water_only_rises(self):
        book = ledger()
        book.mark_session(SESSIONS[0], {})
        book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        book.mark_session(SESSIONS[1], {"2330": D("40")})
        assert book.high_water_mark == D("10000")

    def test_drawdown_is_measured_from_the_high_water(self):
        book = ledger()
        book.mark_session(SESSIONS[0], {})
        book.execute(buy(SESSIONS[0], quantity=100), open_market(SESSIONS[0]))
        book.mark_session(SESSIONS[1], {"2330": D("40")})
        assert book.drawdown > 0

    def test_drawdown_is_zero_at_a_new_high(self):
        book = ledger()
        book.mark_session(SESSIONS[0], {})
        assert book.drawdown == 0


class TestPositionSizingRefusesRatherThanRoundsUp:
    """M0 section 8: when the caps cannot all be met, the answer is no_trade."""

    def test_a_workable_position_is_sized(self):
        plan = plan_position(
            nav=D("10000"),
            price=D("50"),
            stop_price=D("45"),
            open_positions=0,
            settled_cash=D("10000"),
        )
        assert plan.is_trade
        assert plan.planned_risk <= POLICY_HARD_RISK_CAP

    def test_a_third_position_is_refused(self):
        plan = plan_position(
            nav=D("10000"),
            price=D("50"),
            stop_price=D("45"),
            open_positions=2,
            settled_cash=D("10000"),
        )
        assert not plan.is_trade
        assert plan.reason == "max-positions-reached"

    def test_the_cash_reserve_floor_is_respected(self):
        plan = plan_position(
            nav=D("10000"),
            price=D("50"),
            stop_price=D("45"),
            open_positions=0,
            settled_cash=D("500"),
        )
        assert not plan.is_trade

    def test_a_stop_at_or_above_entry_is_refused(self):
        plan = plan_position(
            nav=D("10000"),
            price=D("50"),
            stop_price=D("50"),
            open_positions=0,
            settled_cash=D("10000"),
        )
        assert not plan.is_trade
        assert plan.reason == "stop-must-be-below-entry-for-a-long"

    def test_total_open_risk_is_capped(self):
        plan = plan_position(
            nav=D("10000"),
            price=D("50"),
            stop_price=D("45"),
            open_positions=1,
            open_risk=D("0.0195"),
            settled_cash=D("10000"),
        )
        assert not plan.is_trade
        assert plan.reason == "breaches-total-open-risk-cap"

    def test_a_price_too_high_for_a_single_share_is_no_trade(self):
        """Never round up to one share to make a position exist."""

        plan = plan_position(
            nav=D("10000"),
            price=D("6000"),
            stop_price=D("5400"),
            open_positions=0,
            settled_cash=D("10000"),
        )
        assert not plan.is_trade
        assert plan.quantity == 0

    def test_a_planned_quantity_is_always_a_lot_the_ledger_will_accept(self):
        """The planner and the ledger must not disagree about what is sendable.

        Sizing once produced 1,234 shares — two board lots plus 234 odd — and
        `execute` rejected it as a mixed lot. The signal disappeared with no
        record that any cap had refused it, because none had. Found by the M6
        driver, where it happened 156 times in one run.
        """

        from m4.rules import classify_lot

        for price in ("10", "25.5", "80", "137", "412"):
            plan = plan_position(
                nav=D("1000000"),
                price=D(price),
                stop_price=D(price) * D("0.92"),
                open_positions=0,
                settled_cash=D("1000000"),
            )
            if plan.is_trade:
                classify_lot(plan.quantity)  # raises if the ledger would refuse

    def test_snapping_to_a_lot_never_breaches_a_cap(self):
        """Snapping rounds down, so every cap already applied still holds."""

        plan = plan_position(
            nav=D("1000000"),
            price=D("50"),
            stop_price=D("46"),
            open_positions=0,
            settled_cash=D("1000000"),
        )
        assert plan.is_trade
        assert plan.planned_risk <= POLICY_HARD_RISK_CAP

    def test_a_position_whose_costs_swallow_its_risk_is_refused(self):
        """The NT$10,000 policy is where the minimum commission bites."""

        plan = plan_position(
            nav=D("10000"),
            price=D("20"),
            stop_price=D("19.9"),
            open_positions=0,
            settled_cash=D("10000"),
        )
        assert not plan.is_trade
        assert plan.reason == "round-trip-cost-exceeds-planned-risk"


class TestVersionsAreCarried:
    def test_a_result_names_the_rules_and_ledger_versions(self):
        book = ledger()
        result = book.execute(buy(SESSIONS[0]), open_market(SESSIONS[0]))
        assert result.ledger_version == LEDGER_VERSION
        assert result.rules_version.startswith("tw-alpha-m4-rules/")

    def test_broker_terms_remain_configurable(self):
        book = ledger(terms=BrokerTerms(commission_discount=D("0.6")))
        result = book.execute(
            buy(SESSIONS[0], quantity=10000, price="50"), open_market(SESSIONS[0])
        )
        assert result.state == "rejected"  # 500k exceeds the opening cash
        book2 = ledger(
            opening_cash=D("1000000"), terms=BrokerTerms(commission_discount=D("0.6"))
        )
        discounted = book2.execute(
            buy(SESSIONS[0], quantity=10000, price="50"), open_market(SESSIONS[0])
        )
        assert discounted.state == "filled"
        assert discounted.commission > 0
