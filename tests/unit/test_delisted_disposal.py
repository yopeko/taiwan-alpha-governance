"""下市持股的強制處分——Owner 決定，[提案 003](../../docs/evidence/m7-proposal-003-positions-that-cannot-be-sold-2026-09-05.md) 選項乙。

**這筆成交沒有發生過。** 證券沒有在交易，倉庫這麼說，帳戶不可能賣得掉它。
`MarketConditions` 的 docstring 寫著「沒有查過狀態的呼叫端必須說出來，不能
拿到一個它沒有選擇的寬鬆預設」——這個呼叫端查過了，狀態拒絕這筆交易，而決定
是照做。

**我在提案 §3 建議的是甲（不做處分）。Owner 選了乙。** 這一份不重提那個建議，
它做兩件事：把「哪些條件被編造了」釘死，以及把那個建議賴以成立的訊號釘死
——低波動系統性挑到會停止交易的股票，這件事原本是靠帳戶明顯凍住才被看見的，
現在只能靠 `fill_basis` 這個標記被看見。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

DRIVER = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
    encoding="utf-8"
)
PROPOSAL = (
    REPO / "docs" / "evidence"
    / "m7-proposal-003-positions-that-cannot-be-sold-2026-09-05.md"
).read_text(encoding="utf-8")


class TestTheDecisionIsRecordedWithItsAuthor:
    def test_the_code_names_the_decision_it_implements(self):
        """一段編造市場條件的程式碼，必須指得出是誰決定的、在哪一份文件裡。"""

        assert "proposal 003, option" in DRIVER
        assert "Owner decision" in DRIVER

    def test_the_proposal_recommended_otherwise_and_says_so(self):
        """建議與決定不同，兩者都留著。把建議刪掉會讓這份紀錄看起來像
        「大家都同意」。"""

        assert "建議採甲" in PROPOSAL
        assert "Recommended against" in DRIVER


class TestEveryFabricatedConditionIsNamed:
    """四個欄位被編造，而它們各自違反倉庫說的哪一件事，逐條寫下來。"""

    def test_the_four_are_listed_in_the_code(self):
        for fabricated in (
            "session_is_open",
            "tradability_state",
            "available_quantity",
            "limit_up/limit_down",
        ):
            assert fabricated in DRIVER, fabricated

    def test_the_market_conditions_docstring_is_quoted_where_it_is_broken(self):
        assert "has not looked up the\n                # state" in DRIVER
        assert "the decision was to trade anyway" in DRIVER

    def test_costs_are_charged_rather_than_waived(self):
        """下市不是賣出，本來不會有交易成本。但**編造一筆成交又免掉它的成本，
        是讓帳戶佔兩次便宜**。"""

        assert "would flatter the account twice" in DRIVER


class TestTheDisposalIsDistinguishableFromARealFill:
    def test_the_marker_is_named_once(self):
        """一個打錯的字串會讓一筆編造的成交看起來像市場成交，而沒有東西會
        報錯。所以它是一個常數，不是三處字面值。"""

        import run_ledger_backtest as bt

        assert bt.DISPOSAL_FILL_BASIS == "fabricated-delisting-disposal"
        assert DRIVER.count('"fabricated-delisting-disposal"') == 1

    def test_the_report_carries_the_three_required_columns(self):
        """契約 v1.5.0 §2.4。處分筆數為 0 時仍必須在場——一份沒有這些欄位的
        報告與一份處分為零的報告，讀起來必須不一樣。"""

        assert '"delisted_disposals": sum(' in DRIVER
        assert '"nav_in_delisted_disposals": float(' in DRIVER
        contract = (
            REPO / "docs" / "contracts" / "candidate-report-contract.md"
        ).read_text(encoding="utf-8")
        assert "candidate-report-v1.5.0" in contract
        assert "不是省略" in contract

    def test_the_trade_carries_a_fill_basis(self):
        """`trades` 裡其他每一列都是真的成交。少了這個欄位，讀者無法把它們
        分開，而任何一份彙總都會把編造的成交當成市場證據。"""

        assert '"fill_basis": DISPOSAL_FILL_BASIS,' in DRIVER

    def test_the_exit_reason_is_its_own(self):
        assert '"exit_reason": "delisted-disposal",' in DRIVER

    def test_a_refused_disposal_is_recorded_under_its_own_prefix(self):
        """帳本仍然可能拒絕——例如接近日曆末端無法交割。那要記在 `disposal:`
        底下而不是混進一般的 `exit:`。"""

        assert 'refusals[f"disposal:{result.reason}"] += 1' in DRIVER


class TestItFiresOnTheLifecycleSourceNotOnAGuess:
    def test_the_trigger_is_membership_state(self):
        """「多久沒報價」是猜，`membership_state` 是紀錄。實測的停牌長度分佈
        說猜不準：98.9% 的停牌在 7 個場次內，但也有 203、194、144 個場次之後
        又恢復報價的。"""

        assert 'row.membership_state == "delisted"' in DRIVER

    def test_it_needs_a_price_it_actually_saw(self):
        """處分價是這個部位持有期間市場真的印過的最後一個價格。沒有看過任何
        價格就不處分——那會是憑空造一個數字，而不是用一個舊的。"""

        assert "position.last_close is not None" in DRIVER
        assert "disposal_price = position.last_close" in DRIVER


class TestTheSignalTheDecisionCostsMustStillBeReadable:
    """提案 §3 反對乙的核心理由：低波動系統性挑到會停止交易的股票，
    **是靠帳戶明顯凍住才被看見的**——十個名額全滿、完成交易 103 對 281。

    處分之後那個現象不再自己浮出來（低波動的完成交易變成 306），所以它現在
    只剩下 `fill_basis` 這一個入口。這一組測試存在，是為了讓那個入口不會在
    某次重構裡被當成雜訊清掉。
    """

    RESULT = (
        REPO / "docs" / "evidence"
        / "m7-low-volatility-selects-securities-that-stop-trading-2026-09-05.md"
    ).read_text(encoding="utf-8")

    def test_the_finding_is_recorded_independently_of_the_backtest(self):
        """那個 15.8% 對隨機 2.0% 是從進場清單算的，不是從報酬算的，
        所以它不隨這次決定改變。"""

        assert "15.8%" in self.RESULT
        assert "高於 20/20 個隨機種子" in self.RESULT

    def test_the_code_says_what_now_carries_it(self):
        assert "carried by `delisted_disposals`" in DRIVER or (
            "That signal is now carried by" in DRIVER
        )
