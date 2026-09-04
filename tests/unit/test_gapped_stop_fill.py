"""A stop cannot fill at a price the session never traded.

A stop order is a trigger, not a limit. Once the price reaches it the order
becomes a market order, so the fill is whatever the market offers next. If the
session opened below the stop, the trigger fired before anyone could act and
the first price available is the open.

The driver filled every stop at the stop price. Measured 2026-09-04 over the
momentum candidate's 205 stops, 21.0% of which gapped: reported proceeds were
**6.23% of opening NAV** better than the best any real fill could have
achieved. That is a floor, not an estimate -- it compares against the most
favourable price the session actually printed.

The random controls gapped at the same rate, 18.6% to 23.4%, and cost 0.01%
to 1.18%. So the error is not a property of stopping out; it is a property of
holding names that gap hard, and momentum holds recent winners.
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

SOURCE = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
    encoding="utf-8"
)


def fill(stop: str, open_price: str) -> Decimal:
    """The rule, isolated: the fill is the worse of the stop and the open."""

    return min(Decimal(stop), Decimal(open_price))


class TestAGappedStopFillsAtTheOpen:
    def test_a_session_that_gapped_through_fills_at_the_open(self):
        """The stop price never traded, so it cannot be the fill."""

        assert fill("92.00", "85.00") == Decimal("85.00")

    def test_a_session_that_opened_above_fills_at_the_stop(self):
        """The price fell through the stop during the session, so the stop was
        available and the old behaviour was right for this case."""

        assert fill("92.00", "95.00") == Decimal("92.00")

    def test_an_open_exactly_at_the_stop_fills_at_the_stop(self):
        assert fill("92.00", "92.00") == Decimal("92.00")

    def test_the_rule_never_improves_on_the_old_behaviour(self):
        """`min` in one direction only. A change that could make a fill better
        than the stop would be a way to hand the account an edge, and this one
        cannot: it is bounded above by what the driver used to assume."""

        for stop, opened in (("50", "10"), ("50", "49.99"), ("50", "50.01"), ("50", "999")):
            assert fill(stop, opened) <= Decimal(stop)


class TestTheDriverImplementsIt:
    def test_the_fill_is_the_worse_of_the_stop_and_the_open(self):
        assert "price = min(position.stop_price, opened)" in SOURCE

    def test_the_open_is_read_for_the_exit_not_only_the_entry(self):
        assert (
            "opened = Decimal(str(row.open)) if row.open is not None else close"
            in SOURCE
        )

    def test_a_missing_open_falls_back_to_the_close_not_to_the_stop(self):
        """A session with no published open is rare and must not silently
        restore the old optimistic behaviour. Falling back to the close keeps
        the fill inside prices that did trade."""

        block = SOURCE.split("# --- exits first")[1].split("legs = lot_legs")[0]
        assert "else close" in block
        assert "row.open" in block

    def test_the_reason_code_is_unchanged(self):
        """The exit is still a stop. Only the price it fills at moved, and a
        renamed reason would break every report that counts them."""

        assert 'reason = "stop"' in SOURCE

    def test_the_measured_error_is_recorded_next_to_the_fix(self):
        """A correctness change with no number attached is a preference."""

        assert "6.23% of opening NAV" in SOURCE
        assert "21.0% of its stops gapped" in SOURCE


class TestTheOldBehaviourIsNotReachableByAccident:
    def test_no_remaining_site_fills_a_stop_at_the_bare_stop_price(self):
        """The defect was one expression. This is the check that it stayed
        gone, written against the source because the driver has no seam to
        inject a fill rule through."""

        offenders = [
            line.strip()
            for line in SOURCE.splitlines()
            if re.search(r'=\s*"stop",\s*position\.stop_price', line)
        ]
        assert not offenders, offenders


class TestTheFillCanNeverLandBelowTheLimitDown:
    """The worry that turned out to be impossible by construction.

    A locked limit-down session is one where only sellers remain, and the
    concern was that `min(stop, open)` might produce a price the exchange
    would refuse -- the ledger rejects a sell whose limit is below the
    session's limit-down.

    It cannot. A stop only triggers when `low <= stop_price`, and the session
    low is itself bounded below by the limit-down. So

        stop >= low >= limit_down

    and the open, being a traded price, is bounded the same way. Their minimum
    is therefore never below the floor.

    Measured on the corrected momentum run: 198 stops, **6 sessions where high
    equals low** (only one price traded all day) and **2 of those locked at
    limit-down** -- 1.01%. Both carried heavy volume (708,000 and 963,997
    shares), so a small position could plausibly have exited; the
    participation cap already decides that, and it is not this rule's job.
    """

    def test_the_trigger_condition_bounds_the_stop_from_below(self):
        """The argument, as arithmetic. If the stop had been below the floor
        the session low could never have reached it."""

        limit_down, low = Decimal("34.45"), Decimal("34.45")
        stop = Decimal("40.00")
        assert low <= stop  # the trigger fired
        assert low >= limit_down  # the exchange's floor held
        assert min(stop, low) >= limit_down

    def test_a_fully_locked_session_fills_at_the_only_price_that_traded(self):
        """high == low == open: there is one price and the fill is it."""

        stop, opened = Decimal("40.00"), Decimal("34.45")
        assert fill(str(stop), str(opened)) == opened

    def test_the_driver_triggers_only_on_the_low_reaching_the_stop(self):
        """The premise of the argument above. If this condition ever became
        something else -- the close, say -- the bound would stop holding and
        nothing else would notice."""

        assert "if low <= position.stop_price:" in SOURCE
