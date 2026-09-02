"""Candidate plan 006: the trailing ratchet, and the slot cap that can only tighten.

Two things this candidate could get wrong in a way that makes results better,
which is the direction that does not announce itself:

* a stop raised from **today's** high and then tested against today's low --
  intra-session look-ahead;
* a slot parameter that could ask for more names than M0 section 8 allows,
  turning a choice inside the cap into a way around it.
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

from run_ledger_backtest import (  # noqa: E402
    STOP_RULES,
    stop_distance,
    trail_stop,
)

SOURCE = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
    encoding="utf-8"
)


class TestTheRatchetOnlyEverRises:
    def test_a_higher_peak_raises_the_stop(self):
        assert trail_stop(
            Decimal("92"), Decimal("120"), Decimal("0.08")
        ) == Decimal("110.40")

    def test_a_lower_peak_cannot_lower_the_stop(self):
        """A stop that could fall would let a position give back more than the
        distance the rule advertises, which is the whole property."""

        assert trail_stop(
            Decimal("110.40"), Decimal("100"), Decimal("0.08")
        ) == Decimal("110.40")

    def test_a_flat_peak_leaves_it_alone(self):
        assert trail_stop(
            Decimal("92"), Decimal("100"), Decimal("0.08")
        ) == Decimal("92")


class TestTrailingOpensWhereFixedDoes:
    def test_the_initial_distance_is_the_same(self):
        """Only the reference point changes. A different opening distance would
        be a second variable, and candidate 004b is the record of what happens
        when a stop change moves something else at the same time."""

        closes = [100.0] * 300
        assert stop_distance(closes, 299, "trailing", Decimal("0.08")) == (
            stop_distance(closes, 299, "fixed", Decimal("0.08"))
        )

    def test_trailing_is_a_declared_rule(self):
        assert "trailing" in STOP_RULES


class TestTodaysHighCannotMoveTodaysStop:
    """The look-ahead the plan named before the code was written.

    Asserted on the source because the ordering lives in the holding loop, and
    a unit test of `trail_stop` cannot see it: the function is correct either
    way, and what matters is when the caller updates `peak_high`.
    """

    def test_the_peak_is_updated_after_the_stop_is_checked(self):
        ratchet = SOURCE.index("position.stop_price = trail_stop(")
        check = SOURCE.index("if low <= position.stop_price:")
        update = SOURCE.index("position.peak_high = high")
        assert ratchet < check < update, (
            "the ratchet must run before the stop check, and today's high must "
            "join the peak only after it. Any other order lets a stop be set "
            "from a price that had not happened when the session opened."
        )

    def test_the_peak_starts_at_the_fill_not_the_entry_sessions_high(self):
        assert "peak_high=result.fill_price or entry," in SOURCE

    def test_the_reason_is_written_down_where_it_can_be_read(self):
        assert "intra-session look-ahead" in " ".join(SOURCE.split())


class TestTheSlotCapCanOnlyTighten:
    def test_the_clamp_is_a_min_against_policy(self):
        """A candidate may be more conservative than M0 section 8, never less.
        Read from the source because the clamp sits inside `run`, whose other
        arguments need a dataset."""

        clamp = re.search(
            r"slots = \(\s*POLICY_MAX_POSITIONS\s*if max_positions is None\s*"
            r"else min\(max_positions, POLICY_MAX_POSITIONS\)\s*\)",
            SOURCE,
        )
        assert clamp, "the slot count must be min(requested, policy)"

    def test_no_remaining_use_of_the_policy_constant_as_the_live_cap(self):
        """If either use of the constant survives, one gate keeps the policy
        maximum while the other honours the request, and the two disagree."""

        assert "if len(positions) >= POLICY_MAX_POSITIONS:" not in SOURCE
        assert "][:POLICY_MAX_POSITIONS]" not in SOURCE

    def test_the_manifest_records_what_applied(self):
        """A run that asked for 12 and got 10 must not read as a 12-slot run."""

        assert '"max_positions": slots,' in SOURCE


class TestThePolicyMirrorIsUntouched:
    def test_the_ledger_still_declares_ten(self):
        """`m5/ledger.py` is a byte-identical mirror of Taiwan Core. This
        candidate works inside the cap; it does not move it."""

        ledger = (REPO / "m5" / "ledger.py").read_text(encoding="utf-8")
        assert "POLICY_MAX_POSITIONS = 10" in ledger
