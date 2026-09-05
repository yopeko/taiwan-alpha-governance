"""持股清單、持有長度，以及一個被 `open_at_end: 1` 藏了很久的東西。

Owner 拿這裡的結果去和 XQ 對，第一個問到的問題是「有沒有持股清單和持有
長度」。報告裡有 `trades`，但它只有進出價與日期——**沒有持有長度、沒有
停損／停利價、沒有單筆損益**，而期末未平倉只是一個數字 `1`。

那個 `1` 藏著這個：一檔 2020-12-23 之後就沒有再報價的證券，**在帳上又待了
977 個場次**，佔期末 NAV 的 10.88%。

它不會出場，因為出場迴圈第一行是「沒有價格就跳過」——**停損、停利、持有
上限三個出場全部需要價格**。這一份把那個行為釘住，讓它不能被安靜地改掉，
也不能被安靜地留著。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

import list_trades  # noqa: E402

DRIVER = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
    encoding="utf-8"
)


class TestTheReportCarriesWhatAReconciliationNeeds:
    def test_a_trade_records_its_holding_length(self):
        assert '"holding_sessions": index' in DRIVER

    def test_a_trade_records_the_stop_and_target_it_was_carrying(self):
        """出場價之外還要有出場的理由能被檢查。少了停損與停利價，讀者看得到
        部位結束，看不到它為什麼結束在那裡。"""

        assert '"stop_price": float(position.stop_price),' in DRIVER
        assert '"target_price": (' in DRIVER

    def test_open_positions_are_listed_not_counted(self):
        """`open_at_end` 是一個數字。一個數字說得出有一個部位活到最後，
        說不出是哪一個——而它的市值就在 `final_nav` 裡面。"""

        assert '"open_positions": [' in DRIVER
        assert "was a count" in DRIVER


class TestAPositionWithNoPriceNeverLeaves:
    """**部位確實不會出場，而那一半是對的。**

    出場迴圈仍然需要價格——停損讀 `low`、停利讀 `high`、持有上限要一個賣得
    掉的價。帳戶賣不掉一檔沒有在交易的證券，模型也不該假裝它可以。

    這個 class 原本釘的是修正前的行為：靜默跳過、以進場價標記。那兩條斷言
    在同一天被取代，因為**它們釘住的正是要被修的東西**。留下的是不變的那
    一半，加上指向新行為的斷言。

    實測（2026-09-05，週 MACD 篩選、開發側）：2448 於 2020-12-16 進場，
    2020-12-23 之後 **977 個場次沒有收盤價**，`membership_state = delisted`，
    到 2024-12-31 仍在帳上，**佔期末 NAV 的 10.88%**。
    """

    def test_the_exit_loop_still_requires_a_price(self):
        """不變的那一半，而且不打算變：偽造成交比留著部位更糟。"""

        assert "if row is None or row.close is None:" in DRIVER
        assert "cannot sell what is not trading" in DRIVER

    def test_it_is_no_longer_silent(self):
        """修正前這裡是一個裸的 `continue`，所以一個賣不掉 977 個場次的部位
        在報告裡只留下 `open_at_end: 1`。"""

        assert '"exit:no-price-cannot-sell-delisted"' in DRIVER
        assert "position.sessions_without_price += 1" in DRIVER

    def test_the_mark_is_the_last_close_not_the_entry_price(self):
        """註解一直說「以前一次的價格」，而程式碼一直用**進場價**。

        兩者不是同一件事，而差額不是一次性的：標價經由 NAV 影響風險預算，
        再影響每一次定量。實測低波動因此差 **2.75 個百分點**。
        """

        assert "It was marked at its entry price until 2026-09-05" in DRIVER
        assert "marked at its last one" in DRIVER
        assert "position.last_close" in DRIVER


class TestTheListingItself:
    REPORT = {
        "strategy": {"name": "s", "entry_rule": "e", "stop_pct": 0.08,
                     "reward_risk": 2.5, "max_holding_sessions": 20},
        "opening_cash": 10000.0, "final_nav": 9000.0,
        "return_pct": -10.0, "drawdown_pct": 12.0,
        "trades": [
            {"market": "TWSE", "symbol": "2330", "entry_session": "2020-01-02",
             "exit_session": "2020-01-10", "entry_price": 100.0,
             "exit_price": 120.0, "quantity": 1000, "exit_reason": "target",
             "holding_sessions": 6, "stop_price": 92.0, "target_price": 120.0},
            {"market": "TWSE", "symbol": "1101", "entry_session": "2020-02-03",
             "exit_session": "2020-02-05", "entry_price": 50.0,
             "exit_price": 46.0, "quantity": 2000, "exit_reason": "stop",
             "holding_sessions": 2, "stop_price": 46.0, "target_price": 60.0},
        ],
        "open_positions": [
            {"market": "TWSE", "symbol": "2448", "entry_session": "2020-12-16",
             "entry_price": 41.583, "quantity": 14, "stop_price": 37.536,
             "target_price": 51.7, "holding_sessions": 982, "last_close": None},
        ],
    }

    def test_open_positions_appear_in_the_listing(self):
        listed = list_trades.rows(self.REPORT)
        assert len(listed) == 3
        assert listed[-1]["exit_reason"] == "still-open"

    def test_a_still_open_position_with_no_close_has_no_invented_result(self):
        """沒有最後收盤就沒有損益。填一個 0 會讓它看起來打平，而它並沒有。"""

        still = list_trades.rows(self.REPORT)[-1]
        assert still["gross_pnl"] is None and still["return_pct"] is None

    def test_the_gross_result_is_labelled_gross(self):
        listed = list_trades.rows(self.REPORT)
        assert listed[0]["gross_pnl"] == pytest.approx(20000.0)
        assert listed[0]["return_pct"] == pytest.approx(20.0)
        source = (REPO / "scripts" / "m6" / "list_trades.py").read_text(
            encoding="utf-8"
        )
        assert "Gross, and the column says so" in source

    def test_a_report_with_no_positions_is_refused_rather_than_printed_empty(
        self, tmp_path
    ):
        """一份沒有部位的報告是一個結果，但不是這個工具能列的東西。
        印出一張空表會讓「沒有交易」看起來像「工具壞了」，反之亦然。"""

        empty = tmp_path / "empty.json"
        empty.write_text(
            json.dumps({**self.REPORT, "trades": [], "open_positions": []}),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as caught:
            list_trades.main([str(empty)])
        assert "records no positions" in str(caught.value)

    def test_the_csv_carries_every_column_a_diff_needs(self, tmp_path):
        report = tmp_path / "r.json"
        report.write_text(json.dumps(self.REPORT), encoding="utf-8")
        out = tmp_path / "t.csv"
        list_trades.main([str(report), "--csv", str(out), "--head", "0"])
        header = out.read_text(encoding="utf-8-sig").splitlines()[0]
        for column in ("symbol", "entry_session", "holding_sessions",
                       "stop_price", "target_price", "exit_reason"):
            assert column in header
        assert len(out.read_text(encoding="utf-8-sig").splitlines()) == 4


class TestItNamesWhatWouldNotReconcile:
    """兩個回測器對同一條規則給出不同答案是正常的，而差異通常不在規則上。
    這幾項每一項都比改一條規則的影響更大，所以它們寫在工具的說明裡而不是
    留給使用者自己發現。"""

    SOURCE = (REPO / "scripts" / "m6" / "list_trades.py").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "item",
        ["unadjusted", "the session AFTER the signal", "min(stop, open)",
         "NT$20 minimum", "participation_rate", "tradability_state",
         "risk budget"],
    )
    def test_the_difference_is_named(self, item):
        assert item in self.SOURCE
