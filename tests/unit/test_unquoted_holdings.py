"""持股停止報價之後會發生什麼，以及不會發生什麼。

**帳戶賣不掉一檔沒有在交易的證券，而那是對的。** 每一個出場都要價格：
停損讀 `low`、停利讀 `high`、持有上限要一個賣得掉的價。所以部位留著。

錯的是它**安靜地**留著，而且被以**進場價**標記——那既不是註解說的「前一次
的價格」，也不是任何一個市場印過的數字。實測一筆持有 983 個場次、其中 977
個場次沒有報價的部位，被以 2020 年的買價一路帶到 2024 年底，佔那次執行期末
NAV 的 10.88%。

修正沒有偽造成交。`MarketConditions` 自己寫著「沒有查過狀態的呼叫端必須說
出來，不能拿到一個它沒有選擇的寬鬆預設」——替一檔下市股編造市場條件，正是
那句話擋的事。所以改的是三件：標價改用**最後看到的收盤價**、跳過的出場改成
**記錄拒絕**、以及把**賣不掉的部位市值**報出來。
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

import run_ledger_backtest as bt  # noqa: E402

DRIVER = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
    encoding="utf-8"
)


class TestThePositionCarriesWhatItLastSaw:
    def test_the_fields_exist_and_start_empty(self):
        position = bt.OpenPosition(
            market="TWSE", symbol="2448", entry_session="d",
            entry_price=Decimal("42"), stop_price=Decimal("38"), quantity=14,
        )
        assert position.last_close is None
        assert position.sessions_without_price == 0

    def test_the_mark_prefers_the_last_close_over_the_entry_price(self):
        """兩者不是同一個數字，而註解從一開始就說的是前者。"""

        assert "position.last_close\n                        if position.last_close" in DRIVER
        assert "It was marked at its entry price until 2026-09-05" in DRIVER

    def test_the_entry_price_is_still_the_fallback(self):
        """一個從未看過收盤價的部位不存在（進場要開盤價），但真的發生時，
        編一個數字比用買價更糟。"""

        assert "else position.entry_price" in DRIVER


class TestASkippedExitIsRecorded:
    def test_the_refusal_distinguishes_a_halt_from_a_delisting(self):
        """生命週期來源知道哪一個是哪一個。用「多久沒報價」去猜，是在猜一件
        已經被記錄下來的事——2448 的 `membership_state` 明確寫著 `delisted`。"""

        assert '"exit:no-price-cannot-sell-delisted"' in DRIVER
        assert '"exit:no-price-cannot-sell"' in DRIVER
        assert 'row.membership_state == "delisted"' in DRIVER

    def test_membership_state_is_projected(self):
        """讀不到的欄位會是 None，而 None 與「不是 delisted」分不出來。"""

        assert "membership_state" in bt.DATASET_COLUMNS

    def test_it_counts_the_sessions_rather_than_only_the_refusals(self):
        assert "position.sessions_without_price += 1" in DRIVER
        assert "position.sessions_without_price = 0" in DRIVER

    def test_no_fill_is_invented(self):
        """這是整個修正裡最重要的一句：不偽造成交。"""

        assert "Faking a fill would be worse" in DRIVER
        assert "permissive default it\n                # never chose" in DRIVER


class TestTheExposureIsReported:
    def test_the_report_carries_the_value_nobody_quoted(self):
        assert '"nav_in_unquoted_positions"' in DRIVER

    def test_each_open_position_says_how_long_and_what_state(self):
        assert '"sessions_without_price": position.sessions_without_price,' in DRIVER
        assert '"membership_state": (' in DRIVER
        assert '"mark": float(' in DRIVER


class TestTheMeasuredScope:
    """修正改的是「持股沒有報價時如何標價」，所以只有真的發生過的執行會變。

    2026-09-05 以 HEAD 的驅動器逐一對照（開發側，split-03，參與率 0.01）：

        動能 12-1 rank-only        逐位相同        未報價持倉 0
        候選 006 臂 D              逐位相同        未報價持倉 0
        診斷 004 最佳格            逐位相同        未報價持倉 0
        隨機種子 1                 −45.41 → −45.34  未報價持倉 824.60
        低波動 60                  −38.74 → −35.99  未報價持倉 5,345.35

    **低波動差 2.75 個百分點**，因為它抱得久，而抱得久才會抱到停牌。
    這個數字寫在這裡，是為了讓「哪些產物需要重跑」有一個依據而不是一個判斷。
    """

    def test_the_scope_is_written_down_next_to_the_change(self):
        evidence = (
            REPO / "docs" / "evidence" / "m6-weekly-macd-screen-2026-09-05.md"
        ).read_text(encoding="utf-8")
        assert "2.75" in evidence
        assert "nav_in_unquoted_positions" in evidence
