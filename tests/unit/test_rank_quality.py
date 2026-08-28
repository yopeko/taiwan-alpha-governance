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
    stability,
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


class TestStabilityAnswersWhatTheTStatCannot:
    """Walk-forward, adapted. Every ranking here has zero parameters, so the
    paper's training discipline has nothing to train -- what carries over is
    the other half: is the number stable, or is a pooled average hiding a few
    periods that carry it?

    The t statistic cannot separate those when cross-sections overlap, and
    these overlap heavily. A per-year series can.
    """

    def sections(self, ics):
        return [
            {"session": session, "rank_ic": ic} for session, ic in ics
        ]

    def test_a_consistently_positive_ranking_is_sign_stable(self):
        result = stability(
            self.sections(
                [("2020-01-01", 0.05), ("2021-01-01", 0.06), ("2022-01-01", 0.04)]
            )
        )
        assert result["sign_stable_across_years"] is True
        assert result["ic_hit_rate"] == 1.0

    def test_a_sign_flip_between_years_is_reported(self):
        """momentum-12-1's actual shape: negative 2020-2022, positive after.

        A pooled mean of -0.008 says "no effect"; the yearly series says
        "no effect, and not even a stable no-effect".
        """

        result = stability(
            self.sections(
                [("2020-01-01", -0.02), ("2021-01-01", -0.03), ("2023-01-01", 0.01)]
            )
        )
        assert result["sign_stable_across_years"] is False

    def test_one_carrying_period_shows_in_the_yearly_breakdown(self):
        """A mean of +0.05 from one +0.30 year and four zeros is not the same
        finding as +0.05 every year, and the pooled number cannot say which."""

        result = stability(
            self.sections(
                [
                    ("2019-01-01", 0.0),
                    ("2020-01-01", 0.0),
                    ("2021-01-01", 0.30),
                    ("2022-01-01", 0.0),
                ]
            )
        )
        assert result["best_year"] == "2021"
        assert result["ic_by_year"]["2021"]["mean_ic"] == pytest.approx(0.30)
        assert result["ic_hit_rate"] == 0.25

    def test_the_expanding_mean_is_in_order_and_ends_at_the_pooled_mean(self):
        ics = [("2020-01-01", 0.1), ("2020-02-01", 0.3), ("2020-03-01", 0.2)]
        result = stability(self.sections(ics))
        running = result["expanding_mean_ic"]
        assert [r["session"] for r in running] == [s for s, _ in ics]
        assert running[-1]["expanding_mean_ic"] == pytest.approx(0.2)

    def test_sections_without_an_ic_are_left_out_rather_than_counted_as_zero(self):
        result = stability(
            self.sections([("2020-01-01", 0.1), ("2020-02-01", None)])
        )
        assert result["ic_hit_rate"] == 1.0


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
