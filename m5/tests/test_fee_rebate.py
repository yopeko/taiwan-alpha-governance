"""The nine checks the M5 fee-rebate change spec owed.

The published schedule does not discount at execution. It charges the
full commission and returns the difference to the settlement account on the
15th of the following month, so one fill has two costs: 42 NTD leaves on a 900
NTD position, and 4 NTD is what it finally cost.

The ledger used to deduct a single number. Whichever one it held was wrong
somewhere -- the net overstates cash and buying power by 38 NTD a round trip
and breaks M0 invariant 6.5; the charged understates NAV and inflates every
drawdown by the receivable, around 1% to 1.5% of a NT$10,000 account at the
measured trade rate.

Owner decision, 2026-08-25: `plan_position` uses the charged amount in both
places. An account this size cannot spend a refund that arrives in six weeks.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from m4.rules import BrokerTerms, RuleError, Side, rebate_due_on, trade_costs  # noqa: E402
from m5.ledger import (  # noqa: E402
    Ledger,
    MarketConditions,
    OrderRequest,
    every_entry_traces_to_a_fill,
    journal_is_balanced,
    plan_position,
)

# The 2026 promotion as published: charged at the standard rate with a
# NT$20 floor, rebated to the 2-tenths rate with a NT$1 floor on the 15th.
PROMOTIONAL_2026 = BrokerTerms(
    rebate_commission_rate=Decimal("0.000285"),
    rebate_minimum_commission=Decimal("1"),
    rebate_payment_day=15,
)

PRICE = Decimal("50")
SESSIONS = [date(2026, 1, 5) + timedelta(days=i) for i in range(120)]


def buy(ledger: Ledger, session: date, quantity: int, fill: str = "f1") -> None:
    ledger.execute(
        OrderRequest(
            order_id=f"o-{fill}",
            fill_id=fill,
            session=session,
            symbol="2330",
            side=Side.BUY,
            quantity=quantity,
            limit_price=PRICE,
        ),
        MarketConditions(
            session=session, session_is_open=True, tradability_state="eligible"
        ),
    )


class TestTheTermsRefuseToBeHalfDeclared:
    def test_a_rebate_needs_all_three_of_its_fields(self):
        with pytest.raises(RuleError):
            BrokerTerms(rebate_minimum_commission=Decimal("1"))

    def test_a_rebate_may_not_exceed_what_was_charged(self):
        with pytest.raises(RuleError):
            BrokerTerms(
                rebate_commission_rate=Decimal("0.000285"),
                rebate_minimum_commission=Decimal("50"),
                rebate_payment_day=15,
            )

    def test_the_statutory_tax_is_out_of_a_rebate_s_reach(self):
        with pytest.raises(RuleError):
            BrokerTerms(rebate_scope="commission-and-tax")


class TestTwoCostsNotOne:
    def test_the_charged_amount_is_what_leaves_at_execution(self):
        costs = trade_costs(
            side=Side.BUY, price=PRICE, quantity=18, terms=PROMOTIONAL_2026
        )
        assert costs.commission_charged == 20
        assert costs.commission_net == 1
        assert costs.commission_rebate == 19
        # `total_cost` and `net_cash_delta` follow the charged amount: the
        # refund has not arrived and cannot be spent.
        assert costs.total_cost == 20
        assert costs.commission == costs.commission_charged

    def test_the_tax_is_never_rebated(self):
        costs = trade_costs(
            side=Side.SELL, price=PRICE, quantity=18, terms=PROMOTIONAL_2026
        )
        assert costs.tax == 2
        assert costs.commission_rebate == 19

    def test_terms_without_a_rebate_are_unchanged(self):
        """Regression guard: a broker that does not rebate needs no changes."""

        plain = trade_costs(side=Side.SELL, price=PRICE, quantity=18)
        assert plain.commission_rebate == 0
        assert plain.commission_net == plain.commission_charged == plain.commission
        assert plain.rebate_due_on is None


class TestTheDueDateIsTheLatestItCouldBe:
    def test_it_lands_on_the_fifteenth_of_the_following_month(self):
        assert rebate_due_on(date(2026, 1, 5), PROMOTIONAL_2026) == date(2026, 2, 15)

    def test_december_rolls_into_the_next_year(self):
        assert rebate_due_on(date(2026, 12, 31), PROMOTIONAL_2026) == date(2027, 1, 15)

    def test_terms_without_a_rebate_have_no_due_date(self):
        assert rebate_due_on(date(2026, 1, 5), BrokerTerms()) is None


class TestTheReceivableCountsForNavAndNotForBuyingPower:
    def test_nav_reflects_the_net_cost_not_the_charged_one(self):
        ledger = Ledger(
            opening_cash=Decimal("10000"),
            sessions=SESSIONS,
            terms=PROMOTIONAL_2026,
            # Zero, so these assertions isolate the rebate. With the default
            # 20 bps the fill price differs from the mark and NAV moves for a
            # reason that has nothing to do with what is being tested.
            slippage_rate=Decimal("0"),
        )
        before = ledger.nav({"2330": PRICE})
        buy(ledger, SESSIONS[0], 18)
        after = ledger.nav({"2330": PRICE})
        # 20 charged, 19 receivable, so NAV falls by the 1 it really cost.
        assert before - after == 1

    def test_buying_power_reflects_the_charged_one(self):
        ledger = Ledger(
            opening_cash=Decimal("10000"),
            sessions=SESSIONS,
            terms=PROMOTIONAL_2026,
            # Zero, so these assertions isolate the rebate. With the default
            # 20 bps the fill price differs from the mark and NAV moves for a
            # reason that has nothing to do with what is being tested.
            slippage_rate=Decimal("0"),
        )
        before = ledger.buying_power
        buy(ledger, SESSIONS[0], 18)
        # Principal is committed and the full 20 has gone; the 19 has not.
        assert before - ledger.buying_power == PRICE * 18 + 20
        assert ledger.rebate_receivable == 19

    def test_the_journal_still_balances_with_a_receivable_outstanding(self):
        ledger = Ledger(
            opening_cash=Decimal("10000"),
            sessions=SESSIONS,
            terms=PROMOTIONAL_2026,
            # Zero, so these assertions isolate the rebate. With the default
            # 20 bps the fill price differs from the mark and NAV moves for a
            # reason that has nothing to do with what is being tested.
            slippage_rate=Decimal("0"),
        )
        buy(ledger, SESSIONS[0], 18)
        assert journal_is_balanced(ledger, {"2330": PRICE})


class TestPayingItIn:
    def test_nothing_is_credited_before_its_due_date(self):
        ledger = Ledger(
            opening_cash=Decimal("10000"),
            sessions=SESSIONS,
            terms=PROMOTIONAL_2026,
            # Zero, so these assertions isolate the rebate. With the default
            # 20 bps the fill price differs from the mark and NAV moves for a
            # reason that has nothing to do with what is being tested.
            slippage_rate=Decimal("0"),
        )
        buy(ledger, SESSIONS[0], 18)
        assert ledger.credit_rebates_through(date(2026, 2, 14)) == []
        assert ledger.rebate_receivable == 19

    def test_it_is_credited_on_the_due_date_and_traces_to_its_fill(self):
        ledger = Ledger(
            opening_cash=Decimal("10000"),
            sessions=SESSIONS,
            terms=PROMOTIONAL_2026,
            # Zero, so these assertions isolate the rebate. With the default
            # 20 bps the fill price differs from the mark and NAV moves for a
            # reason that has nothing to do with what is being tested.
            slippage_rate=Decimal("0"),
        )
        buy(ledger, SESSIONS[0], 18, fill="f-trace")
        paid = ledger.credit_rebates_through(date(2026, 2, 15))
        assert len(paid) == 1
        assert ledger.rebate_receivable == 0
        entry = [e for e in ledger.journal if e.kind == "commission-rebate"][0]
        assert entry.amount == 19
        # M0 invariant 6.4: an aggregated payment that named no fill would
        # satisfy the bank statement and break the audit trail.
        assert entry.fill_id == "f-trace"
        assert every_entry_traces_to_a_fill(ledger.journal)

    def test_the_same_rebate_cannot_be_paid_twice(self):
        """M0 invariant 6.6."""

        ledger = Ledger(
            opening_cash=Decimal("10000"),
            sessions=SESSIONS,
            terms=PROMOTIONAL_2026,
            # Zero, so these assertions isolate the rebate. With the default
            # 20 bps the fill price differs from the mark and NAV moves for a
            # reason that has nothing to do with what is being tested.
            slippage_rate=Decimal("0"),
        )
        buy(ledger, SESSIONS[0], 18)
        first = ledger.credit_rebates_through(date(2026, 2, 15))
        cash = ledger.settled_cash
        second = ledger.credit_rebates_through(date(2026, 3, 15))
        assert first and not second
        assert ledger.settled_cash == cash


class TestSizingUsesTheChargedAmount:
    """Owner decision 2026-08-25, and the reason it is the safe direction."""

    # NAV 1,200 sizes one share at 100 under the 0.75% risk cap over an 8%
    # stop. Cash of 230 leaves 110 spendable after the 10% reserve: enough for
    # the share, not for the share plus the 20 the broker takes.
    NAV = Decimal("1200")
    CASH = Decimal("230")
    PRICE = Decimal("100")
    STOP = Decimal("92")

    def test_cash_must_cover_the_position_and_the_charged_commission(self):
        plan = plan_position(
            nav=self.NAV,
            price=self.PRICE,
            stop_price=self.STOP,
            open_positions=0,
            settled_cash=self.CASH,
            terms=PROMOTIONAL_2026,
        )
        assert not plan.is_trade
        assert plan.reason == "cash-cannot-cover-position-and-charged-commission"

    def test_the_net_amount_would_have_let_it_through(self):
        """Names the difference the decision turns on.

        The spendable 110 covers one share at 100 plus the 1 NTD the fill
        finally costs, and does not cover the 20 the broker takes on the day.
        Sizing on the net would have opened a position the account could not
        pay for, and the shortfall would have surfaced at execution.
        """

        spendable = self.CASH - self.NAV * Decimal("0.10")
        costs = trade_costs(
            side=Side.BUY, price=self.PRICE, quantity=1, terms=PROMOTIONAL_2026
        )
        assert self.PRICE + costs.commission_net <= spendable
        assert self.PRICE + costs.commission_charged > spendable

    def test_a_broker_without_a_rebate_sizes_the_same_way(self):
        """The charged amount is the rule, not a rebate-only special case."""

        plan = plan_position(
            nav=self.NAV,
            price=self.PRICE,
            stop_price=self.STOP,
            open_positions=0,
            settled_cash=self.CASH,
        )
        assert plan.reason == "cash-cannot-cover-position-and-charged-commission"
