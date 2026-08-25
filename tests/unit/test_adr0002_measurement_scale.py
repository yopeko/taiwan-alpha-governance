"""ADR-0002's first three claims, made checkable.

The ADR was accepted on 2026-08-25 and its verification table listed six tests
owed. Three could be written immediately; the other three describe candidate
reports that do not exist yet.

A rule with no test watching it is a rule nobody will notice breaking, which
is the same reason M2's documented exceptions each carry one.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from m4.rules import BrokerTerms, Side, trade_costs  # noqa: E402

# Phase 0's measured median: NAV 10,000 at 0.75% planned risk over an 8% stop
# gives roughly 904. Used as the position the ADR's numbers describe.
BASELINE_POSITION = 904
PRICE = Decimal("50")


def reference_scale(terms: BrokerTerms) -> int:
    """Smallest turnover at which the minimum commission stops binding.

    Derived by asking `trade_costs`, never written down. ADR-0002 decision 2
    requires exactly this: the reference scale is a function of the terms in
    force, so it moves when they do instead of becoming a stale constant.
    """

    low, high = 1, 5_000_000
    while low < high:
        mid = (low + high) // 2
        charged = trade_costs(
            side=Side.BUY, price=Decimal(1), quantity=mid, terms=terms
        )
        if charged.minimum_commission_applied:
            low = mid + 1
        else:
            high = mid
    return low


def round_trip_pct(terms: BrokerTerms, notional: int = BASELINE_POSITION) -> float:
    buy = trade_costs(side=Side.BUY, price=Decimal(1), quantity=notional, terms=terms)
    sell = trade_costs(side=Side.SELL, price=Decimal(1), quantity=notional, terms=terms)
    return float(buy.total_cost + sell.total_cost) / notional * 100


class TestTheReferenceScaleIsDerivedNotStored:
    """ADR-0002 decision 2."""

    def test_it_matches_the_value_the_adr_quotes(self):
        assert reference_scale(BrokerTerms()) == 14036

    def test_it_moves_when_the_minimum_moves(self):
        """A stored constant would not, which is the whole point."""

        base = reference_scale(BrokerTerms())
        lower = reference_scale(BrokerTerms(minimum_commission=Decimal("1")))
        assert lower < base

    def test_it_moves_when_the_discount_moves(self):
        """Upwards. A smaller proportional fee lets the floor bind further.

        This is the counter-intuitive result the ADR records: an electronic
        discount alone saves nothing at these sizes and raises the turnover
        needed to escape the fixed cost.
        """

        base = reference_scale(BrokerTerms())
        discounted = reference_scale(
            BrokerTerms(commission_discount=Decimal("0.6"))
        )
        assert discounted > base


class TestTheDecidingTermIsTheMinimumNotTheRate:
    """ADR-0002 background 2, and the reason alternative B waits on one term."""

    def test_a_discount_alone_does_not_lower_the_cost_of_a_baseline_position(self):
        base = round_trip_pct(BrokerTerms())
        discounted = round_trip_pct(BrokerTerms(commission_discount=Decimal("0.6")))
        assert discounted >= base, (
            "a rate discount reduced the cost of a 904 position; the ADR's "
            "reasoning that the minimum decides everything would not hold"
        )

    def test_a_lower_minimum_does_lower_it(self):
        base = round_trip_pct(BrokerTerms())
        floored = round_trip_pct(BrokerTerms(minimum_commission=Decimal("1")))
        assert floored < base
        assert base / floored > 5, (
            "the ADR records this as a tenfold difference; a change small "
            "enough to argue about would undercut the decision resting on it"
        )


class TestTheStatutoryTaxIsAFloor:
    """ADR-0002 background 2: the negotiable part is the gap, not the whole."""

    # The truncation to whole NTD can cost at most one dollar on the sell.
    TRUNCATION = 100 / BASELINE_POSITION

    @pytest.mark.parametrize("discount", ["1", "0.6", "0.28"])
    @pytest.mark.parametrize("minimum", ["20", "1", "0"])
    def test_no_terms_can_take_the_sell_tax_below_the_statutory_rate(
        self, discount, minimum
    ):
        terms = BrokerTerms(
            commission_discount=Decimal(discount),
            minimum_commission=Decimal(minimum),
        )
        sell = trade_costs(
            side=Side.SELL, price=Decimal(1), quantity=BASELINE_POSITION, terms=terms
        )
        pct = float(sell.tax) / BASELINE_POSITION * 100
        assert pct >= 0.3 - self.TRUNCATION, (
            f"sell tax fell to {pct:.3f}% under {discount}/{minimum}; the tax "
            "is statutory and no broker term may reduce it"
        )

    def test_the_tax_is_charged_on_the_sell_only(self):
        terms = BrokerTerms()
        buy = trade_costs(
            side=Side.BUY, price=PRICE, quantity=BASELINE_POSITION, terms=terms
        )
        assert buy.tax == 0
