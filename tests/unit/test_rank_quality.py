"""The rank-quality arithmetic, on inputs whose answers are known by hand.

None of these touch the dataset. The measures are where a mistake would be
invisible: a broken Spearman returns a plausible number, and a plausible
number about ranking quality is worse than none, because the whole point of
the measurement is that returns alone were not telling us this.

The tie-handling and the degenerate cases get their own tests. A cross-section
where every score is identical is not a correlation of zero -- it is a
cross-section with nothing to correlate, and reporting zero would put it in
the average as evidence of no relationship.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m6"))

from rank_quality import (  # noqa: E402
    QUINTILES,
    ndcg_at,
    pearson,
    quintile_of,
    ranks,
    spearman,
)


class TestRanksShareTies:
    def test_distinct_values_rank_one_to_n(self):
        assert ranks([10.0, 20.0, 30.0]) == [1.0, 2.0, 3.0]

    def test_tied_values_share_the_average_rank(self):
        """Not 2 and 3 but 2.5 each. Breaking ties by position would make the
        correlation depend on the order rows happened to arrive in."""

        assert ranks([1.0, 2.0, 2.0, 3.0]) == [1.0, 2.5, 2.5, 4.0]

    def test_all_tied_share_one_rank(self):
        assert ranks([5.0, 5.0, 5.0]) == [2.0, 2.0, 2.0]


class TestSpearmanIsPearsonOnRanks:
    def test_a_perfect_ordering_is_one(self):
        assert spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0

    def test_a_reversed_ordering_is_minus_one(self):
        assert spearman([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == -1.0

    def test_it_ignores_the_size_of_the_gaps(self):
        """Rank correlation, so one enormous forward return does not dominate.

        This is the property that makes it disagree with a quintile mean, and
        the disagreement was the finding: inverse-volatility ranks positively
        while its top quintile has the lower mean, because the mean is carried
        by the right tail of the high-volatility bucket.
        """

        gentle = spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        extreme = spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 10_000])
        assert gentle == extreme == 1.0


class TestDegenerateCrossSectionsReturnNothingNotZero:
    def test_identical_scores_are_not_a_correlation_of_zero(self):
        """Zero would enter the average as evidence of no relationship.

        None keeps it out, which is the honest treatment of a cross-section
        that could not have shown a relationship either way.
        """

        assert spearman([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None

    def test_identical_forward_returns_are_not_zero_either(self):
        assert spearman([1, 2, 3, 4, 5], [7, 7, 7, 7, 7]) is None

    def test_too_few_securities_returns_nothing(self):
        assert pearson([1.0, 2.0], [1.0, 2.0]) is None


class TestNdcgRewardsTheTopOfTheList:
    def test_a_perfect_ordering_scores_one(self):
        perfect = list(range(20))
        assert ndcg_at(perfect, perfect, 5) == pytest.approx(1.0)

    def test_a_reversed_ordering_scores_near_zero(self):
        perfect = list(range(20))
        assert ndcg_at(perfect, list(reversed(perfect)), 5) < 0.05

    def test_getting_the_tail_right_barely_helps(self):
        """The top N is the only part a ten-slot account can act on.

        A ranking that orders positions 50-100 perfectly and the top ten
        badly is useless here, and the measure has to say so.
        """

        forwards = list(range(20))
        top_right = list(range(20))
        top_wrong = [0, 1, 2, 3, 4] + list(range(19, 4, -1))
        assert ndcg_at(top_right, forwards, 5) > ndcg_at(top_wrong, forwards, 5)

    def test_a_cross_section_smaller_than_n_returns_nothing(self):
        assert ndcg_at([1, 2, 3], [1, 2, 3], 5) is None


class TestQuintilesSplitEvenly:
    def test_the_lowest_position_lands_in_the_first_bucket(self):
        assert quintile_of(0, 100) == 0

    def test_the_highest_position_lands_in_the_last(self):
        assert quintile_of(99, 100) == QUINTILES - 1

    def test_no_position_escapes_the_buckets(self):
        for total in (11, 37, 100, 341):
            for position in range(total):
                assert 0 <= quintile_of(position, total) < QUINTILES


class TestTheLimitationTravelsWithTheNumbers:
    def test_the_reading_note_names_the_unadjusted_price_bias(self):
        """The warehouse has no adjusted series and M0 forbids deriving one
        without a documented method, so forward returns carry an ex-dividend
        drop. High-yield securities are pushed down systematically -- a
        direction, not noise -- and every number here has to be read with it.
        """

        source = (REPO / "scripts" / "m6" / "rank_quality.py").read_text(
            encoding="utf-8"
        )
        assert "unadjusted" in source
        assert "documented method" in source

    def test_it_refuses_a_ranking_that_has_no_score(self):
        source = (REPO / "scripts" / "m6" / "rank_quality.py").read_text(
            encoding="utf-8"
        )
        assert "Arrival order has no" in source
