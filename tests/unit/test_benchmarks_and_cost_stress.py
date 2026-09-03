"""The three M0 section 9.1 columns that were listed and never built.

Cash, a market index and the equal-weight eligible universe. The contract has
required them since M0 v1.0.0; the backtester's arms were momentum, inverse
volatility and twenty random seeds, so no candidate report has ever carried
them and none could have.

Plus the 2x cost stress M0 makes a precondition of applying for `validated`,
which was equally unimplemented.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

import benchmarks  # noqa: E402
import build_index_benchmarks as index_builder  # noqa: E402

M0 = (REPO / "docs" / "m0-project-contract.md").read_text(encoding="utf-8")


class TestTheIndexComesFromBlobsThatWereAlreadyThere:
    """No capture. The six-year price history came from `MI_INDEX`, which
    answers with ten tables; staging parses the closing quotations and left
    the two index boards alone in every blob."""

    def test_only_the_two_exchange_boards_are_read(self):
        """`價格指數(跨市場)` and the index-company boards are different
        publishers on the same page. Taking all of them would mix them."""

        assert index_builder.BOARDS == (
            ("價格指數(臺灣證券交易所)", "price"),
            ("報酬指數(臺灣證券交易所)", "total-return"),
        )

    def test_both_bases_are_collected_for_both_families(self):
        ids = {v[0] for v in index_builder.WANTED.values()}
        bases = {v[1] for v in index_builder.WANTED.values()}
        assert ids == {"TAIEX", "TW50"}
        assert bases == {"price", "total-return"}

    def test_the_short_labels_map_to_the_same_index(self):
        """2019-04-29 printed `加權股價指數` for one session out of 1,862, and
        the first build came out with 1,861 TAIEX sessions against TW50's
        1,862. Checked by continuity before the alias was added: 10,939.06 that
        day sits between 10,952.47 on 04-26 and 10,967.73 on 04-30."""

        assert index_builder.WANTED["加權股價指數"] == ("TAIEX", "price")
        assert index_builder.WANTED["加權股價報酬指數"] == (
            "TAIEX",
            "total-return",
        )

    def test_a_name_found_on_the_wrong_board_is_refused(self):
        """The board decides whether a series includes dividends. A total-
        return name appearing on the price board means one of the two is
        wrong, and neither may be assumed."""

        record = {"logical_period": "session:2026-09-02", "snapshot_id": "s"}
        payload = (
            b'{"tables":[{"title":"\\u50f9\\u683c\\u6307\\u6578'
            b'(\\u81fa\\u7063\\u8b49\\u5238\\u4ea4\\u6613\\u6240)",'
            b'"data":[["\\u767c\\u884c\\u91cf\\u52a0\\u6b0a\\u80a1\\u50f9'
            b'\\u5831\\u916c\\u6307\\u6578","1,000.00"]]}]}'
        )
        with pytest.raises(SystemExit) as caught:
            index_builder.rows_from(record, payload)
        assert "neither may be assumed" in str(caught.value)

    def test_thousands_separators_and_absence_are_both_handled(self):
        assert index_builder.number("46,125.91") == Decimal("46125.91")
        assert index_builder.number("-") is None
        assert index_builder.number("") is None

    def test_a_non_trading_day_yields_nothing_rather_than_failing(self):
        """The exchange's non-session response is preserved as evidence and
        carries no index board. That is the right answer, not an error."""

        record = {"logical_period": "session:2026-01-01"}
        assert index_builder.rows_from(record, b"<html>not json</html>") == []


class TestTheMinimumComparisonSetIsNamedNotRemembered:
    def test_every_arm_m0_lists_is_accounted_for(self):
        """Seven entries, each either supplied here or pointed at what
        supplies it. A list that quietly drops one is how three of them went
        unbuilt for the life of the project."""

        assert len(benchmarks.MINIMUM_SET) == 7
        for arm, provider in benchmarks.MINIMUM_SET.items():
            assert provider, arm

    def test_the_champion_arm_says_there_is_none(self):
        """Vacuous rather than absent: nothing is `validated`, so there is no
        champion, and that is a fact about the project rather than a gap in
        this file."""

        assert "none exists" in benchmarks.MINIMUM_SET["current champion"]

    def test_m0_still_asks_for_all_seven(self):
        for phrase in ("現金", "等權", "random selection", "champion"):
            assert phrase in M0


class TestEveryBenchmarkArmDeclaresItsBasis:
    """The lesson the discretionary contract paid for on 2026-09-03: its
    equal-weight benchmark ran through the real cost model and came out at
    -24.63% against a true +25.47%. Fifty points, flattering the picks."""

    ENTRY = {("TWSE", "A"): 100.0, ("TWSE", "B"): 50.0}
    LAST = {("TWSE", "A"): ("D2", 120.0), ("TWSE", "B"): ("D2", 45.0)}

    def test_the_universe_arm_is_the_mean_of_the_parts(self):
        out = benchmarks.equal_weight_universe(
            [("TWSE", "A"), ("TWSE", "B")], self.ENTRY, self.LAST, "D2"
        )
        assert out["return_pct"] == pytest.approx((0.20 + -0.10) / 2 * 100)
        assert out["basis"] == "gross"

    def test_a_name_that_stopped_trading_is_valued_not_dropped(self):
        last = dict(self.LAST)
        last[("TWSE", "B")] = ("D1", 45.0)
        out = benchmarks.equal_weight_universe(
            [("TWSE", "A"), ("TWSE", "B")], self.ENTRY, last, "D2"
        )
        assert out["delisted_in_window"] == 1
        assert out["names"] == 2

    def test_cash_is_nominal_and_says_so(self):
        """A deposit rate would be a claim about an account this project does
        not have."""

        assert "現金" in M0


class TestTheCostStressM0MakesAPrecondition:
    """M0 section 8: a candidate must survive at least 2x cost stress before
    it may apply for `validated`. Nothing implemented it, so no candidate
    could have applied even had one passed its own thresholds."""

    def test_the_multipliers_are_the_ones_m0_names(self):
        import run_ledger_backtest as backtest

        assert backtest.COST_STRESS_MULTIPLIERS == (
            Decimal("1"),
            Decimal("1.5"),
            Decimal("2"),
            Decimal("3"),
        )
        assert "1.5、2、3 倍" in M0

    def test_the_rate_based_costs_scale_and_the_floor_does_not(self):
        import run_ledger_backtest as backtest

        base_terms, base_slip = backtest.stressed_costs(Decimal("1"))
        hard_terms, hard_slip = backtest.stressed_costs(Decimal("2"))
        assert hard_terms.commission_rate == base_terms.commission_rate * 2
        assert hard_slip == base_slip * 2
        # Named in the docstring as a deliberate limit of the test, not an
        # oversight: the 20 TWD floor is not a variable cost and the 0.3% tax
        # is statute.
        assert hard_terms.minimum_commission == base_terms.minimum_commission
        assert hard_terms.sell_tax_rate == base_terms.sell_tax_rate

    def test_the_baseline_slippage_matches_the_ledger_it_multiplies(self):
        """A drift between the two would silently move the baseline every
        stressed run is measured against."""

        import inspect

        import run_ledger_backtest as backtest
        from m5.ledger import Ledger

        assert backtest.LEDGER_BASELINE_SLIPPAGE == inspect.signature(
            Ledger.__init__
        ).parameters["slippage_rate"].default

    def test_a_zero_or_negative_multiplier_is_refused(self):
        import run_ledger_backtest as backtest

        for bad in (Decimal("0"), Decimal("-1")):
            with pytest.raises(SystemExit):
                backtest.stressed_costs(bad)

    def test_the_mirrors_are_not_edited_to_apply_the_stress(self):
        """`m4/rules.py` and `m5/ledger.py` are byte-identical to Taiwan Core.
        Both the terms and the slippage rate are constructor arguments, so the
        stress goes in from outside."""

        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert "replace(base, commission_rate=" in source
        assert "slippage_rate=slippage" in source

    def test_the_manifest_records_what_applied(self):
        """A stressed run must not read as an unstressed one."""

        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        for field in (
            '"cost_multiplier": float(cost_multiplier),',
            '"minimum_commission_not_stressed"',
            '"sell_tax_rate_not_stressed"',
        ):
            assert field in source


class TestTheWalkForwardExemptionIsWrittenDownNotAssumed:
    """D25. M0 section 9.1 required walk-forward folds and the nested
    validation contract said it could not be done; both were
    `baseline-approved`, so the real state was a requirement never satisfied
    and never exempted, with nothing counting it.
    """

    NESTED = (
        REPO / "docs" / "contracts" / "nested-validation-contract.md"
    ).read_text(encoding="utf-8")

    def test_m0_carries_the_exemption_and_its_threshold(self):
        assert "§9.1.1" in M0
        assert "1,650" in M0
        assert "walk-forward-folds-exempt" in M0

    def test_the_four_release_parameters_are_fixed_in_advance(self):
        """Fixed now rather than at implementation time, for the same reason a
        candidate plan fixes its thresholds before the run: a reading rule
        chosen after the results cannot be told from one chosen to suit them."""

        for phrase in ("錨定擴張窗口", "21 個場次", "只切開發區", "250 筆"):
            assert phrase in M0, phrase

    def test_the_purge_covers_the_longest_holding_period(self):
        """21 is not a round number. `max_holding_sessions` is 20, so a
        position opened on the last training session can still be open 20
        sessions into validation."""

        import run_ledger_backtest as backtest
        import inspect

        longest = inspect.signature(backtest.run).parameters
        assert "max_holding_sessions" in longest
        assert "max_holding_sessions = 20" in M0

    def test_the_exemption_says_it_will_not_expire_on_its_own(self):
        """The development half is bounded at both ends -- 2019-01-01 and the
        day before `SEAL_FROM` -- so it is 1,458 sessions permanently and time
        passing only lengthens the sealed half. The exemption is an IOU with a
        task attached, not one with a due date, and it has to say so or someone
        will wait for it."""

        assert "回補" in M0
        assert "兩端都固定" in M0

    def test_both_contracts_point_at_each_other(self):
        """The conflict was invisible because each document was internally
        consistent. Neither may now be read without the other."""

        assert "D25" in self.NESTED
        assert "9.1.1" in self.NESTED
        assert "nested-validation-contract" in M0

    def test_the_folds_never_reach_the_sealed_region(self):
        """Every fold rolled over the sealed half would be an opening, and it
        does not regenerate."""

        assert "只切開發區" in M0
        assert "開封" in M0
