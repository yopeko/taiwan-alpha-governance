"""法人買賣超進資料集時，落後一個場次必須是**資料的形狀**，不是策略的紀律。

兩個交易所都在收盤後才公布買賣超。用場次 T 自己的數字排序、在 T 的開盤
進場，是前視——而且是會產生漂亮結果的那一種前視。

所以資料集裡**根本沒有同場次的數字**。每一個法人欄位都叫
`..._prior_session`，在 T 這一列帶的是 T−1 公布的報表。沒有東西要記得，
也沒有東西要移位；照字面讀就已經是對的，而想要同場次的數字**在這裡拿不到**。

這一份盯著那句話。差一格不會壞任何東西，只會讓下游變得漂亮。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

import build_research_dataset as builder  # noqa: E402

SOURCE = (REPO / "scripts" / "m6" / "build_research_dataset.py").read_text(
    encoding="utf-8"
)


class TestTheSameSessionFiguresAreNotHere:
    def test_every_institutional_column_says_it_is_lagged(self):
        assert builder.INSTITUTIONAL_COLUMNS
        for name in builder.INSTITUTIONAL_COLUMNS:
            assert name.endswith("_prior_session"), name

    def test_no_column_carries_a_bare_measure_name(self):
        """`investment_trust_net` 出現在 schema 裡，就是一個看起來可用、
        而且會安靜地給出前視結果的欄位。"""

        schema = {field.name for field in builder.SCHEMA}
        for measure in builder.INSTITUTIONAL_MEASURES:
            assert measure not in schema, measure

    def test_the_lag_is_stated_where_a_consumer_will_read_it(self):
        assert "is look-ahead" in SOURCE
        assert "not in this dataset at all" in SOURCE


class TestZeroAndNullAreDifferentFacts:
    """報表不列出當天沒有法人單的證券，而那些系統性地是最小的那些
    ——2019-01-22 的 TPEx 缺席者成交量中位數是 20,000，在席者是 224,000。

    所以「有報價但沒進報表」是 **0**，「那天根本沒被報價」是 **null**。
    把兩者合併，不是替一檔不存在的證券發明一個零，就是丟掉「沒有法人碰過」
    這個唯一能被篩選的訊號。
    """

    REPORT = {("TWSE", "2330"): (1, 2, 3, 4)}
    QUOTED = {("TWSE", "2330", "2019-01-02"), ("TWSE", "1101", "2019-01-02")}

    def test_a_reported_security_carries_its_own_figures(self):
        values, case = builder.institutional_for(
            "TWSE", "2330", "2019-01-02", self.REPORT, self.QUOTED
        )
        assert values == (1, 2, 3, 4) and case == "reported"

    def test_quoted_and_absent_from_the_report_is_zero(self):
        values, case = builder.institutional_for(
            "TWSE", "1101", "2019-01-02", self.REPORT, self.QUOTED
        )
        assert values == (0, 0, 0, 0) and case == "zero-quoted-no-flow"

    def test_not_quoted_is_null_not_zero(self):
        values, case = builder.institutional_for(
            "TWSE", "9999", "2019-01-02", self.REPORT, self.QUOTED
        )
        assert values == (None,) * 4 and case == "null-not-quoted"

    def test_the_first_session_of_the_window_has_no_prior_report(self):
        values, case = builder.institutional_for(
            "TWSE", "2330", None, {}, self.QUOTED
        )
        assert values == (None,) * 4 and case == "null-not-quoted"

    def test_a_reported_row_of_four_zeroes_is_reported_not_no_flow(self):
        """情形由條件決定，不是從數字反推出來的。

        第一版把情形讀回自數值，於是一檔**確實被列出、四個數字都是零**的
        證券被算進「沒有法人單」那一格，manifest 會低報涵蓋率。
        """

        values, case = builder.institutional_for(
            "TWSE", "2330", "2019-01-02", {("TWSE", "2330"): (0, 0, 0, 0)}, self.QUOTED
        )
        assert values == (0, 0, 0, 0) and case == "reported"


class TestTheReportIsReadOnlyAfterTheSessionIsWritten:
    def test_the_advance_happens_after_the_rows(self):
        """讀取順序就是這整個欄位存在的理由。在場次內推進，就是前視。"""

        rows_at = SOURCE.index("rows.append(")
        advance_at = SOURCE.index("prior_report = reports.report_for(session)")
        assert rows_at < advance_at
        assert "never before" in SOURCE

    def test_a_session_the_lane_does_not_cover_returns_empty(self):
        """交易所若某天沒有報表，回傳空的比回傳鄰居的數字好。
        後者是把別的場次的資料當成這一場的，而且不會有任何錯誤。"""

        reports = builder.InstitutionalReports.__new__(builder.InstitutionalReports)
        reports._stream = iter(
            [("2019-01-02", {("TWSE", "2330"): (1, 1, 1, 1)}),
             ("2019-01-04", {("TWSE", "2330"): (2, 2, 2, 2)})]
        )
        reports._head = next(reports._stream)
        assert reports.report_for("2019-01-02") == {("TWSE", "2330"): (1, 1, 1, 1)}
        assert reports.report_for("2019-01-03") == {}
        assert reports.report_for("2019-01-04") == {("TWSE", "2330"): (2, 2, 2, 2)}
        assert reports.report_for("2019-01-07") == {}

    def test_sessions_before_the_asked_one_are_discarded(self):
        reports = builder.InstitutionalReports.__new__(builder.InstitutionalReports)
        reports._stream = iter(
            [("2019-01-03", {("TWSE", "1101"): (3, 3, 3, 3)})]
        )
        reports._head = ("2019-01-02", {("TWSE", "2330"): (1, 1, 1, 1)})
        assert reports.report_for("2019-01-03") == {("TWSE", "1101"): (3, 3, 3, 3)}

    def test_a_missing_lane_stops_the_build(self, tmp_path):
        """欄位全是 null 的資料集會通過每一條測試，然後讓每一條用到它的
        策略靜靜地什麼都選不出來。"""

        with pytest.raises(SystemExit) as caught:
            builder.InstitutionalReports(tmp_path)
        assert "silently null" in str(caught.value)


class TestTheDriverCanActuallyReadThem:
    def test_the_columns_are_projected(self):
        import run_ledger_backtest as backtest

        for name in builder.INSTITUTIONAL_COLUMNS:
            assert name in backtest.DATASET_COLUMNS, name

    def test_the_driver_says_why_it_loads_them_unconditionally(self):
        """取捨要寫下來，而且要帶實測數字。

        第一版註解寫「約省三分之一 GB」——那是估的。實測是 **0.269 GB**
        （3,076,380 列，常駐 1.235 對 1.504 GB），而條件式載入連這個都省不
        滿，因為空的 slot 本身就要約 0.09 GB。

        一個沒有標價的取捨，下次會被當成沒有代價。
        """

        driver = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        # 註解裡這句跨行，所以比對不跨行的片段。
        assert "complete and sometimes not" in driver
        assert "1.235 GB against 1.504 GB" in driver
