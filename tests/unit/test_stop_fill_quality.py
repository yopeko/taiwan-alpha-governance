"""Where stops filled, against where M0 section 8's arithmetic assumed.

Diagnostic plan 003. The 7.50% total open risk cap is ten positions at 9.375%
of NAV each, all stopped at 8%. That arithmetic holds only if a stop fills at
the stop price, and the momentum run refused 152 exits, so it is worth a
check rather than a belief.

These tests watch the two ways the measurement could flatter a candidate:
counting only the bad side, and treating a position that never exited as one
that exited well.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m7"))

import measure_stop_fill_quality as fills  # noqa: E402


def run(trades, stop_pct=0.08, opening=100000.0, open_at_end=0):
    return {
        "opening_cash": opening,
        "open_at_end": open_at_end,
        "strategy": {"stop_pct": stop_pct, "ranking_function": "x"},
        "trades": trades,
    }


def trade(entry, exit_price, qty=100, reason="stop"):
    return {
        "entry_price": entry,
        "exit_price": exit_price,
        "quantity": qty,
        "exit_reason": reason,
        "entry_session": "2020-01-02",
        "exit_session": "2020-01-09",
        "market": "TWSE",
        "symbol": "2330",
    }


class TestTheStopPriceComesFromTheRun:
    def test_the_designed_exit_uses_the_manifests_own_stop(self):
        """Not a constant here. A run with a different stop must be measured
        against its own, or the number is about this file's assumption."""

        out = fills.measure(run([trade(100.0, 90.0)], stop_pct=0.05))
        # Designed exit 95.0, filled 90.0, so worse by 5% of entry.
        assert out["filled_worse_than_stop"] == 1
        assert out["median_slippage_pct"] == pytest.approx(-5.0)


class TestBothSidesAreReported:
    def test_a_fill_above_the_stop_is_counted(self):
        """Looking only at the bad side answers a different question."""

        out = fills.measure(run([trade(100.0, 95.0)]))
        assert out["filled_better_than_stop"] == 1
        assert out["filled_worse_than_stop"] == 0
        assert out["excess_loss_as_pct_of_opening_nav"] == 0.0

    def test_a_good_fill_never_offsets_a_bad_one_in_the_excess(self):
        """Excess loss is the cost of the fills that were worse. Netting a
        lucky fill against an unlucky one would understate what the cap was
        exposed to."""

        out = fills.measure(run([trade(100.0, 80.0), trade(100.0, 95.0)]))
        # Only the first contributes: (92 - 80) * 100 = 1200 on 100000.
        assert out["excess_loss_as_pct_of_opening_nav"] == pytest.approx(1.2)


class TestWhatIsLeftOut:
    def test_rebalance_exits_are_excluded_and_counted(self):
        out = fills.measure(
            run([trade(100.0, 80.0), trade(100.0, 120.0, reason="left-the-top-n")])
        )
        assert out["stops"] == 1
        assert out["rebalance_exits_excluded"] == 1

    def test_positions_still_open_are_excluded_and_counted(self):
        """They have no exit price. Treating them as filled at the stop would
        invent the very number this is measuring."""

        out = fills.measure(run([trade(100.0, 80.0)], open_at_end=5))
        assert out["open_at_end_excluded"] == 5

    def test_a_run_with_no_stops_reports_zero_rather_than_nothing(self):
        out = fills.measure(run([trade(100.0, 120.0, reason="left-the-top-n")]))
        assert out["stops"] == 0
        assert out["excess_loss_as_pct_of_opening_nav"] == 0.0
        assert out["median_slippage_pct"] is None


class TestTheExcessIsWeightedByPositionSize:
    def test_a_larger_position_contributes_more(self):
        small = fills.measure(run([trade(100.0, 80.0, qty=10)]))
        large = fills.measure(run([trade(100.0, 80.0, qty=1000)]))
        assert large["excess_loss_as_pct_of_opening_nav"] == pytest.approx(
            small["excess_loss_as_pct_of_opening_nav"] * 100
        )
