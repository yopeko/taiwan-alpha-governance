"""M0 section 9.1's minimum control set, and the one column that was empty.

The section has listed six controls since 2026-08-02. One of them --
"equal-size same-pool random selection" -- was never implemented, and nothing
checked. It went unmet for a month in a project whose whole method is that
requirements are watched by something other than memory.

That is the same shape as the trial ledger counting nothing, the CI config
that had never run, and `needs_local_data` declared and unused. The cost here
was specific: candidate 003's rank-only arm returned +163.20% over a window
holding 2020-2021, and momentum's Rank IC on the same data is -0.0080
(t = -0.56). Without a random control those two facts cannot be reconciled,
and neither can be acted on.

These tests are cheap and none of them reads local data, so they run on every
commit and in CI. They check that the control exists, that its seeds are the
ones the plan fixed in advance, and that its scores are reproducible by
someone who was not there.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

from run_ledger_backtest import (  # noqa: E402
    CONTROL_SEEDS,
    RANKINGS,
)

CONTRACT = REPO / "docs" / "m0-project-contract.md"
PLAN = (
    REPO
    / "docs"
    / "evidence"
    / "m7-control-plan-001-random-selection-2026-09-01.md"
)


class TestTheContractStillAsksForIt:
    def test_section_9_1_still_lists_the_random_control(self):
        """If this line is ever deleted, the tests below stop meaning anything
        and would go on passing. Checked first for that reason."""

        text = CONTRACT.read_text(encoding="utf-8")
        assert "equal-size same-pool random selection" in text

    def test_the_other_five_controls_are_still_named(self):
        """Implementing one column is not implementing the set.

        Cash, a benchmark, the equal-weight pool and the current champion are
        still not implemented. That is a known gap, recorded in the control
        plan section 4, and this test exists so the gap keeps a name rather
        than quietly narrowing to whatever was built.
        """

        text = CONTRACT.read_text(encoding="utf-8")
        for phrase in ("現金", "ETF benchmark", "等權", "champion"):
            assert phrase in text, f"M0 9.1 no longer names {phrase}"


class TestTheControlExists:
    def test_every_pre_registered_seed_has_a_ranking(self):
        for seed in CONTROL_SEEDS:
            assert f"random-seed-{seed}" in RANKINGS

    def test_the_seeds_are_the_ones_the_plan_fixed_in_advance(self):
        """The plan named them before anything ran, so they cannot have been
        picked after seeing a result. Twenty Fibonacci numbers, chosen because
        they existed before this project did."""

        assert CONTROL_SEEDS == (
            1, 2, 3, 5, 8, 13, 21, 34, 55, 89,
            144, 233, 377, 610, 987, 1597, 2584, 4181, 6765, 10946,
        )
        assert len(CONTROL_SEEDS) == 20

    def test_the_plan_lists_the_same_seeds(self):
        """Two copies of a number is one place for them to disagree."""

        text = PLAN.read_text(encoding="utf-8")
        for seed in CONTROL_SEEDS:
            assert str(seed) in text


class TestTheScoresAreReproducibleByAnyone:
    """The property that makes it a control rather than one author's run."""

    def test_the_score_ignores_price(self):
        score = RANKINGS["random-seed-1"]
        cheap = score([1.0, 2.0], 1, market="TWSE", symbol="2330", session="2020-01-02")
        dear = score([900.0, 1.0], 1, market="TWSE", symbol="2330", session="2020-01-02")
        assert cheap == dear, (
            "a random control that reads prices is not independent of the "
            "thing it is controlling for"
        )

    def test_different_securities_score_differently(self):
        score = RANKINGS["random-seed-1"]
        a = score([1.0], 0, market="TWSE", symbol="2330", session="2020-01-02")
        b = score([1.0], 0, market="TWSE", symbol="2317", session="2020-01-02")
        assert a != b

    def test_the_same_security_scores_differently_on_another_session(self):
        """Otherwise it is one fixed ordering held all the way through, which
        is a different experiment: a constant portfolio, not random selection."""

        score = RANKINGS["random-seed-1"]
        a = score([1.0], 0, market="TWSE", symbol="2330", session="2020-01-02")
        b = score([1.0], 0, market="TWSE", symbol="2330", session="2020-01-03")
        assert a != b

    def test_seeds_do_not_agree_with_each_other(self):
        first = RANKINGS[f"random-seed-{CONTROL_SEEDS[0]}"]
        second = RANKINGS[f"random-seed-{CONTROL_SEEDS[1]}"]
        args = dict(market="TWSE", symbol="2330", session="2020-01-02")
        assert first([1.0], 0, **args) != second([1.0], 0, **args)

    def test_the_score_is_the_documented_hash_and_not_merely_deterministic(self):
        """Recomputed here from the formula the plan states, so a reader with
        the plan and no access to this machine can check any single score."""

        seed, market, symbol, session = 1, "TWSE", "2330", "2020-01-02"
        digest = hashlib.sha256(
            f"{seed}:{market}:{symbol}:{session}".encode()
        ).digest()
        expected = int.from_bytes(digest[:8], "big") / 2**64
        actual = RANKINGS["random-seed-1"](
            [1.0], 0, market=market, symbol=symbol, session=session
        )
        assert actual == expected
        assert 0.0 <= actual < 1.0


class TestThePriceRankingsStillTakeTheOldCallForm:
    """`rank_quality.py` calls them positionally with two arguments. The
    identity keywords were added for the control; breaking the other callers
    to add a control would be a poor trade."""

    @pytest.mark.parametrize("name", ["momentum-12-1", "inverse-volatility-60"])
    def test_two_positional_arguments_still_work(self, name):
        closes = [100.0 + i * 0.1 for i in range(300)]
        assert RANKINGS[name](closes, len(closes) - 1) is not None
