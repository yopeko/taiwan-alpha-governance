"""M0 section 8.1's halts, measured without inventing a resumption rule.

Diagnostic plan 002. The rules have existed since 2026-08-02 and no backtest
has ever applied them, so the drawdowns every candidate report carries are
numbers this account could not experience -- a canary hard-stops at 8%.

These tests are about the two things the measurement could get wrong in a way
that flatters a candidate: where the clock starts, and quietly acquiring a
free parameter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m7"))

import measure_halt_events as halts  # noqa: E402


def result(navs, opening=100.0, start=0):
    return {
        "opening_cash": opening,
        "drawdown_pct": 0.0,
        "strategy": {"ranking_function": "x"},
        "equity": [
            {"session": f"2020-01-{i + 1:02d}", "nav": nav}
            for i, nav in enumerate(navs)
        ],
    }


class TestTheThresholdsAreM0s:
    def test_the_constants_match_the_contract(self):
        """5% and 8% predate every dataset here. If either is ever edited to
        fit a result, that is a policy change needing an Owner decision and an
        OOS protocol -- section 8.1 says so itself."""

        assert halts.WATCHLIST_DRAWDOWN == 0.05
        assert halts.HARD_STOP_DRAWDOWN == 0.08
        assert halts.CANARY_MINIMUM_SESSIONS == 60


class TestTheClockStartsWhenMoneyMoves:
    def test_a_flat_warmup_is_not_counted(self):
        """Momentum needs 252 sessions before it can trade and a control needs
        none. Counting from session zero would give the candidate a 252-session
        head start on a question about what happens once it is trading."""

        navs = [100.0] * 10 + [100.0, 99.0, 91.0]
        out = halts.measure(result(navs))
        assert out["anchor_session"] == "2020-01-12"
        assert out["sessions_after_anchor"] == 2
        assert out["sessions_until_first_8pct"] == 1

    def test_a_run_that_never_trades_says_so(self):
        """Rather than reporting None for the halts, which in a summary table
        reads as "never halted"."""

        out = halts.measure(result([100.0] * 5))
        assert out["traded"] is False
        assert out["sessions_until_first_8pct"] is None


class TestTheCrossings:
    def test_a_drawdown_past_five_but_not_eight_hits_only_the_first_line(self):
        """Written as "exactly 5%" first, with 95.95 against a 101 high water.
        That is 0.049999999999999975 in binary and the test failed. The
        threshold is a policy line at a resolution where 1e-17 cannot matter,
        so the fix is the test, not a tolerance in the measurement."""

        out = halts.measure(result([100.0, 101.0, 95.0]))
        assert out["sessions_until_first_5pct"] == 1
        assert out["sessions_until_first_8pct"] is None

    def test_the_drawdown_is_from_the_high_water_not_the_start(self):
        """A run that doubles and then gives back 8% has hard-stopped, even
        though it is far above where it started."""

        out = halts.measure(result([100.0, 200.0, 184.0]))
        assert out["sessions_until_first_8pct"] == 1
        assert out["return_at_first_8pct"] == pytest.approx(84.0)

    def test_share_of_sessions_counts_every_session_not_only_the_first(self):
        out = halts.measure(result([100.0, 90.0, 90.0, 100.0]))
        assert out["share_of_sessions_below_8pct"] == pytest.approx(2 / 3 * 100)


class TestItNeverAcquiresAResumptionRule:
    def test_no_halt_count_is_reported(self):
        """Counting halts needs a rule for when one ended, and section 8.1
        ends a halt with a person's decision. Inventing that rule now would be
        choosing a free parameter after seeing the results."""

        out = halts.measure(result([100.0, 90.0, 100.0, 90.0]))
        assert not [k for k in out if "count" in k or "times" in k]

    def test_no_post_halt_return_is_reported(self):
        out = halts.measure(result([100.0, 90.0, 120.0]))
        assert not [k for k in out if "after_halt" in k or "resumed" in k]

    def test_the_source_docstring_states_the_reason(self):
        text = (REPO / "scripts" / "m7" / "measure_halt_events.py").read_text(
            encoding="utf-8"
        )
        # Whitespace-normalised: the sentence is line-wrapped in the source,
        # and a first version of this test looked for it unwrapped.
        assert "resumption rule does not exist" in " ".join(text.split())


class TestTheCanaryFlag:
    def test_a_halt_before_session_60_is_flagged(self):
        out = halts.measure(result([100.0] + [100.0 - i for i in range(12)]))
        assert out["first_8pct_before_session_60"] is True

    def test_no_halt_at_all_is_none_not_false(self):
        """False would read as "it survived 60 sessions", which is a different
        claim from "it never came close"."""

        out = halts.measure(result([100.0, 101.0, 102.0]))
        assert out["first_8pct_before_session_60"] is None
