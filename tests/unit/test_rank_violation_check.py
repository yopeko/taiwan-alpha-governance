"""The rank-consistency comparison, exercised where the driver cannot.

`count_rank_violation` was inline in the session loop until 2026-08-26 and
pulled out for one reason: in a real run its scarcity branch can never return
a code, so no backtest can show that the branch works.

Why it cannot. Signals are walked in descending score order, and `positions`
only grows during the entry loop -- exits ran in an earlier phase. So once the
slots fill they stay filled, nothing opens afterwards, and a scarcity refusal
is never followed by a fill. The zero the candidate report prints is arithmetic
about the loop, not a finding about the strategy.

That makes the counter a guard on the sort rather than a measurement, and a
guard nobody can see fail is a guard nobody should trust. These tests make it
fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m6"))

from run_ledger_backtest import (  # noqa: E402
    SCARCITY_REFUSALS,
    SIZING_REFUSALS,
    count_rank_violation,
)

SLOTS_FULL = "entry:position-slots-full"
TOO_EXPENSIVE = "entry:round-trip-cost-exceeds-planned-risk"


class TestItCatchesTheThingItIsFor:
    def test_a_better_name_turned_away_for_room_is_a_violation(self):
        """Arrival order, drawn as a picture: 0.9 refused, 0.2 taken."""

        assert (
            count_rank_violation([0.2], [(0.9, SLOTS_FULL)], SCARCITY_REFUSALS)
            == SLOTS_FULL
        )

    def test_it_names_the_code_rather_than_returning_a_flag(self):
        """A count says the rule broke without saying where."""

        code = count_rank_violation(
            [0.1], [(0.5, TOO_EXPENSIVE)], SIZING_REFUSALS
        )
        assert code == TOO_EXPENSIVE

    def test_the_worst_taken_is_the_one_compared_against(self):
        """0.9 refused clears 0.95, but not the 0.2 also in the book."""

        assert (
            count_rank_violation(
                [0.95, 0.2], [(0.9, SLOTS_FULL)], SCARCITY_REFUSALS
            )
            == SLOTS_FULL
        )

    def test_the_best_refused_is_the_one_that_reports(self):
        assert (
            count_rank_violation(
                [0.5], [(0.1, SLOTS_FULL), (0.9, SLOTS_FULL)], SCARCITY_REFUSALS
            )
            == SLOTS_FULL
        )


class TestItStaysQuietWhenItShould:
    def test_a_worse_name_turned_away_is_the_ranking_working(self):
        assert (
            count_rank_violation([0.9], [(0.2, SLOTS_FULL)], SCARCITY_REFUSALS)
            is None
        )

    def test_an_equal_score_is_not_a_violation(self):
        """Ties are not evidence either way, and a strict test would fabricate
        violations out of two names the ranking cannot separate."""

        assert (
            count_rank_violation([0.5], [(0.5, SLOTS_FULL)], SCARCITY_REFUSALS)
            is None
        )

    def test_nothing_opened_means_nothing_to_compare(self):
        assert (
            count_rank_violation([], [(0.9, SLOTS_FULL)], SCARCITY_REFUSALS)
            is None
        )

    def test_nothing_refused_means_nothing_to_compare(self):
        assert count_rank_violation([0.2], [], SCARCITY_REFUSALS) is None


class TestTheTwoQuestionsStaySeparate:
    """Contract v1.2.0 section 3. Pooled, the larger count decides both."""

    def test_a_sizing_refusal_is_invisible_to_the_scarcity_check(self):
        assert (
            count_rank_violation([0.2], [(0.9, TOO_EXPENSIVE)], SCARCITY_REFUSALS)
            is None
        )

    def test_a_scarcity_refusal_is_invisible_to_the_sizing_check(self):
        assert (
            count_rank_violation([0.2], [(0.9, SLOTS_FULL)], SIZING_REFUSALS)
            is None
        )

    def test_the_same_session_can_answer_the_two_differently(self):
        """The shape the 12-1 momentum candidate actually produced: the top
        name did not fit, and nothing was turned away for want of room."""

        refused = [(0.9, TOO_EXPENSIVE), (0.1, SLOTS_FULL)]
        assert count_rank_violation([0.2], refused, SCARCITY_REFUSALS) is None
        assert (
            count_rank_violation([0.2], refused, SIZING_REFUSALS) == TOO_EXPENSIVE
        )

    def test_the_two_sets_do_not_overlap(self):
        """An overlapping code would be counted twice and the itemised tally
        would stop summing to the two reported counts."""

        assert not (SCARCITY_REFUSALS & SIZING_REFUSALS)
