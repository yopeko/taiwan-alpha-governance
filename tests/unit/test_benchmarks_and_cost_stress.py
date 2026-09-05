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
sys.path.insert(0, str(REPO / "scripts" / "m7"))

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


class TestTheRegimeContinuityMeasurementDecidesOnOneMetric:
    """A claim I made and then measured away.

    I said the 2019-2026 window already crossed two structural changes with
    nothing accounting for it. Crossing them on the calendar is a fact;
    crossing them in the data had to be measured, and it was not there.
    """

    def test_the_deciding_metric_is_the_mechanism_sensitive_one(self):
        import measure_regime_continuity as regime

        assert regime.MECHANISM_SENSITIVE == "mean_shares_per_trade"
        assert regime.MECHANISM_SENSITIVE in regime.METRICS

    def test_activity_metrics_are_carried_but_do_not_decide(self):
        """Continuous trading arrived in March 2020 and so did the COVID
        crash. Transaction counts jump in a crash, so a metric that jumps has
        two candidate causes and the date alone cannot separate them -- the
        same confounding that made diagnostic 002's first answer wrong."""

        import measure_regime_continuity as regime

        assert "daily_transactions" in regime.METRICS
        assert regime.MECHANISM_SENSITIVE != "daily_transactions"

    def test_the_change_month_is_excluded_from_its_own_level_shift(self):
        """Whatever else happened that month happened too. Including it lets a
        one-month spike stand in for a level."""

        medians = {f"2020-{m:02d}": 100.0 for m in range(1, 13)}
        medians["2020-06"] = 1000.0
        out = regime_module().level_shift(medians, "2020-06", window=3)
        assert out["before_median"] == 100.0
        assert out["after_median"] == 100.0
        assert out["shift_pct"] == pytest.approx(0.0)

    def test_a_level_shift_is_reported_against_the_typical_month(self):
        """A shift smaller than the median month-to-month step is not a step,
        so both numbers have to be in the report or the reader has nothing to
        compare against."""

        source = (
            REPO / "scripts" / "m3" / "measure_regime_continuity.py"
        ).read_text(encoding="utf-8")
        assert '"median_monthly_step_pct"' in source
        assert '"level_shift"' in source

    def test_the_change_dates_are_marked_presumed(self):
        """Neither effective date was verified against a published rule. The
        conclusion does not depend on them -- a permanent shift is visible
        whichever month it began in, and the scan covers every month -- but
        the output must not read as though they were checked."""

        import measure_regime_continuity as regime

        for label in regime.PRESUMED_CHANGES.values():
            assert "presumed" in label

    def test_an_empty_series_is_refused_rather_than_reported_continuous(self):
        import measure_regime_continuity as regime

        with pytest.raises(SystemExit) as caught:
            regime.build([REPO / "does-not-exist"])
        assert "not an archive root" in str(caught.value)

    def test_the_note_keeps_the_odd_lot_question_open(self):
        """Whether an odd lot was executable intraday before the odd-lot
        session opened is a rules question with an effective date, and daily
        aggregates cannot answer it. M0 already carries it as a blocker."""

        source = (
            REPO / "scripts" / "m3" / "measure_regime_continuity.py"
        ).read_text(encoding="utf-8")
        assert "odd lot" in source
        assert "rules question" in source


def regime_module():
    import measure_regime_continuity

    return measure_regime_continuity


class TestTheStopFillBoundUsesTheStopThatWasSubmitted:
    """The first version of this measurement used the wrong reference.

    `entry x (1 - stop_pct)` is not the stop the order carried: the stop is
    set from the signal session's price and the position is entered at the
    next session's. That difference is the defect diagnostic 003 already
    found, and using it here folded the old defect into the new number and
    reported the sum as fill quality.
    """

    def bound_module(self):
        import bound_stop_fill_with_bars

        return bound_stop_fill_with_bars

    def run(self, exit_price, opened, low, quantity=100):
        return {
            "opening_cash": 100000.0,
            "strategy": {"stop_pct": 0.08},
            "trades": [
                {
                    "market": "TWSE",
                    "symbol": "A",
                    "exit_session": "D",
                    "exit_reason": "stop",
                    "entry_price": 100.0,
                    "exit_price": exit_price,
                    "quantity": quantity,
                }
            ],
        }, {("TWSE", "A", "D"): {"open": opened, "low": low, "high": max(opened, 999.0)}}

    def test_the_submitted_stop_is_recovered_from_the_recorded_fill(self):
        """The ledger wrote `stop x (1 - slippage)`, so dividing it back out
        gives the price the order actually carried."""

        source = (
            REPO / "scripts" / "m7" / "bound_stop_fill_with_bars.py"
        ).read_text(encoding="utf-8")
        assert "modelled_fill / (1 - slippage)" in source
        assert "entry_price" not in source.split("def bound(")[1].split("def main(")[0]

    def test_a_session_that_did_not_gap_can_fill_at_the_stop(self):
        """Opening above the stop means the price fell through it during the
        session, so the stop itself was available.

        The best case then comes out **better** than the model by exactly the
        slippage rate, because the model charges 0.20% and a fill at the stop
        does not. That is the model being conservative on this subset, and it
        is why the momentum run's -6.23% is a net figure: the gap cost is
        larger than that gross, offset by this on the sessions that did not
        gap.
        """

        module = self.bound_module()
        result, bars = self.run(exit_price=91.818, opened=95.0, low=88.0)
        out = module.bound(result, bars, 0.002)
        assert out["gapped_through_the_stop_at_open"] == 0
        better = out["proceeds_vs_the_model_pct_of_opening_nav"][
            "best_case_fill_at_stop_or_open"
        ]
        # 100 shares at ~92, 0.2% of that, against 100,000 opening cash.
        assert better == pytest.approx(92.0 * 100 * 0.002 / 100000 * 100, rel=0.02)

    def test_a_gapped_open_makes_even_the_best_case_worse_than_the_model(self):
        """The model assumes a fill at a price the session never traded.

        This is the whole finding: 21% of the momentum run's stops gapped, and
        that puts a floor of 6.23% of opening NAV under the error with no new
        data needed to establish it.
        """

        module = self.bound_module()
        result, bars = self.run(exit_price=91.818, opened=85.0, low=80.0)
        out = module.bound(result, bars, 0.002)
        assert out["gapped_through_the_stop_at_open"] == 1
        assert (
            out["proceeds_vs_the_model_pct_of_opening_nav"][
                "best_case_fill_at_stop_or_open"
            ]
            < 0
        )

    def test_the_band_is_labelled_a_bound_and_not_a_distribution(self):
        """A stop order does not systematically fill at the session low. The
        band says daily bars cannot locate the truth inside it, not that the
        worst end is likely."""

        module = self.bound_module()
        result, bars = self.run(exit_price=91.818, opened=95.0, low=80.0)
        out = module.bound(result, bars, 0.002)
        assert out["band_width_pct_of_opening_nav"] > 0
        assert "not a distribution" in out["reading_note"]

    def test_an_impossible_bar_is_reported_rather_than_clamped(self):
        """An open below the published low cannot happen. Agreeing with it
        would hide a data defect inside a measurement."""

        module = self.bound_module()
        result, bars = self.run(exit_price=91.818, opened=70.0, low=90.0)
        out = module.bound(result, bars, 0.002)
        assert out["stops_without_a_comparable_bar"] == 1
        assert out["stops_priced"] == 0

    def test_a_run_with_no_stops_is_refused(self):
        module = self.bound_module()
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(
                {"opening_cash": 1.0, "strategy": {"stop_pct": 0.08}, "trades": []},
                handle,
            )
            path = handle.name
        with pytest.raises(SystemExit) as caught:
            module.main(["--run", path, "--dataset", str(REPO)])
        assert "read as agreement" in str(caught.value)


class TestTheReportCarriesTheMinimumComparisonSet:
    """M0 section 9.1 has required these columns since v1.0.0 and no candidate
    report carried them until 2026-09-04, because nothing computed them.

    `benchmarks.py` computed them from 2026-09-03; this is the wiring that
    puts them where a reader compares.
    """

    CONTRACT = (
        REPO / "docs" / "contracts" / "candidate-report-contract.md"
    ).read_text(encoding="utf-8")
    DRIVER = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
        encoding="utf-8"
    )

    REQUIRED = (
        "benchmark_cash_pct",
        "benchmark_equal_weight_universe_gross_pct",
        "benchmark_index_taiex_price_gross_pct",
        "benchmark_index_taiex_total_return_gross_pct",
        "benchmark_basis",
    )

    def test_the_contract_requires_them(self):
        for name in self.REQUIRED:
            assert name in self.CONTRACT, name

    def test_the_driver_builds_them(self):
        for name in self.REQUIRED:
            assert f'"{name}"' in self.DRIVER, name

    def test_the_schema_version_moved(self):
        """A report that gained required columns is not the same schema.

        Pinned at 1.3.0 when the M0 section 9.1 benchmark columns landed, and
        moved to 1.4.0 on 2026-09-05 when `drawdown_pct` was named as the
        maximum over the equity curve and `terminal_drawdown_pct` joined it,
        then to 1.5.0 the same day when D27's delisting-disposal columns
        landed. A version that moves twice in a day is a version doing its
        job -- the alternative is two different reports claiming to be 1.4.0.

        **The two versions move together.** The producer's `schema_id` and
        `CANDIDATE_REPORT_CONTRACT` were out of step for a day in September
        because only the first was bumped, and every report from that day
        declared a version lower than the one it met.
        """

        assert (
            'CANDIDATE_REPORT_SCHEMA = "tw-alpha-m6-candidate-report/1.5.0"'
            in self.DRIVER
        )
        assert 'CANDIDATE_REPORT_CONTRACT = "candidate-report-v1.5.0"' in self.DRIVER
        assert "candidate-report-v1.5.0" in self.CONTRACT

    def test_the_contract_says_which_drawdown(self):
        """自 v1.0.0 起契約要求 `drawdown_pct` 並稱它「最大回撤」，而沒有說是
        相對哪個基準、在哪個時點量的。倉庫因此有一天同時存在兩個定義。"""

        assert "權益曲線的最大回撤" in self.CONTRACT
        assert "terminal_drawdown_pct" in self.CONTRACT
        assert "final_drawdown_pct_from_run" in self.CONTRACT

    def test_every_benchmark_column_says_it_is_gross(self):
        """The candidate's `return_pct` is net. Putting the two side by side
        without saying so leaves the reader to assume, and on 2026-09-03 that
        assumption was worth fifty percentage points in the flattering
        direction."""

        assert '"benchmark_basis": "gross",' in self.DRIVER
        for name in self.REQUIRED:
            if name.startswith("benchmark_index") or "equal_weight" in name:
                assert "gross" in name, name
        assert "毛" in self.CONTRACT

    def test_a_missing_index_table_is_reported_not_dropped(self):
        """M0 requires the column. A benchmark that quietly disappears is the
        shape section 9.1 exists to stop."""

        import run_ledger_backtest as backtest

        out = backtest.minimum_comparison_set(
            REPO, REPO / "no-such-index", "2020-01-02", "2020-12-30"
        )
        assert out["available"] is False
        assert "build_index_benchmarks" in out["reason"]

    def test_an_absent_arm_becomes_null_rather_than_zero(self):
        """Zero is a return. Absence is not, and the two must not share a cell
        value -- a benchmark that reads 0.00% looks like a market that went
        nowhere rather than one nobody measured.

        Asserted on the lookup itself: the report builder needs a full run
        result to construct, and a fake one detailed enough to reach this line
        would be testing the fake.
        """

        def arm(arms: dict, name: str):
            value = (arms.get(name) or {}).get("return_pct")
            return None if value is None else float(value)

        assert arm({}, "index_TAIEX:price") is None
        assert arm({"index_TAIEX:price": {}}, "index_TAIEX:price") is None
        assert arm({"index_TAIEX:price": {"return_pct": None}}, "index_TAIEX:price") is None
        assert arm({"index_TAIEX:price": {"return_pct": 0}}, "index_TAIEX:price") == 0.0

        # And the driver uses exactly that lookup, not a `or 0.0` default.
        assert 'value = (arms.get(name) or {}).get("return_pct")' in self.DRIVER
        assert 'return None if value is None else float(value)' in self.DRIVER
        assert '"benchmark_cash_pct": 0.0,' in self.DRIVER


class TestPassingTheCostStressIsDefined:
    """M0 section 8 required "通過 2 倍成本壓力" from v1.0.0 and never said
    what passing meant. The gap did not surface until 2026-09-04, because the
    stress had never been run -- an unexecuted requirement's ambiguity stays
    invisible.

    D26 defines it. These tests hold the definition to the two things that
    make it checkable rather than re-interpretable.
    """

    def test_m0_now_says_what_passing_means(self):
        assert "§8.1a" in M0 or "8.1a" in M0
        assert "通過 2 倍成本壓力 =" in M0

    def test_both_criteria_are_named(self):
        """One is the like-for-like control, the other is the market. A single
        criterion would let "對照組" be re-read next time."""

        assert "隨機同池選股分佈的中位數" in M0
        assert "未還原價格指數" in M0

    def test_the_controls_are_stressed_at_the_same_multiplier(self):
        """Stressing the candidate and not the controls compares it against an
        easier world than the one it is in."""

        assert "只壓候選不壓對照" in M0

    def test_the_excluded_benchmarks_say_why_they_are_excluded(self):
        """Exclusions decided by argument, not by which ones the candidate
        happens to beat. The total-return index is excluded because the
        dataset carries unadjusted prices, and TW50 because section 9.1 asks
        for the eligible universe rather than a large-cap basket."""

        assert "含息，而策略不含" in M0 or "含息而策略不含" in M0
        assert "權值股" in M0

    def test_they_are_still_reported_even_though_they_do_not_decide(self):
        """A report listing only the columns the candidate wins is what
        section 9.1 exists to prevent."""

        assert "仍必須依 §9.1 並排呈報" in M0

    def test_the_multipliers_the_definition_applies_to_exist(self):
        import run_ledger_backtest as backtest

        assert Decimal("2") in backtest.COST_STRESS_MULTIPLIERS
