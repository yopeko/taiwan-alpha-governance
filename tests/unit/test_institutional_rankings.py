"""四條法人排序函式，以及讓它們讀得到資料的簽章改動。

排序函式原本只拿得到 `closes: list[float]`。四條訊號要讀
`..._prior_session` 與 `volume`，所以簽章改成拿整個 `Bar` 串列。

**為什麼是整列而不是多傳幾個平行串列**：兩個平行串列會有一天差一格，
而那一格不會報錯，只會讓結果變漂亮。傳整列之後，價格與法人數字的對齊
是結構性的——一個 `Bar` 就是一個場次，不用靠任何人維護。

定義來自[診斷計畫 005](../../docs/evidence/m6-diagnostic-plan-005-institutional-rank-quality-2026-09-05.md)，
**寫在量測之前**，這一份把它們釘住。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

import run_ledger_backtest as bt  # noqa: E402

PLAN = (
    REPO
    / "docs"
    / "evidence"
    / "m6-diagnostic-plan-005-institutional-rank-quality-2026-09-05.md"
).read_text(encoding="utf-8")

INSTITUTIONAL = (
    "investment-trust-net",
    "investment-trust-net-5",
    "foreign-net-5",
    "institutional-net-turnover",
)


def bar(**values):
    """一列，未給的欄位為 None。"""

    filled = tuple(values.get(name) for name in bt.DATASET_COLUMNS)
    return bt.Bar(filled)


def series(field: str, values, **common):
    return [bar(**{field: v}, **common) for v in values]


class TestTheFourAreTheFourThatWerePreRegistered:
    def test_exactly_these_names_exist(self):
        """多一條就是一次沒有登錄的試驗。計畫 §7 寫著四條是事先寫定的，
        不是挑出來的。"""

        found = {
            name
            for name in bt.RANKINGS
            if name and not name.startswith("random-seed-")
            and name not in ("momentum-12-1", "inverse-volatility-60")
        }
        assert found == set(INSTITUTIONAL)

    @pytest.mark.parametrize("name", INSTITUTIONAL)
    def test_the_plan_names_it(self, name):
        assert f"`{name}`" in PLAN

    def test_the_plan_points_at_its_result_and_was_not_edited_after(self):
        """計畫在 2026-09-05 執行完畢。**計畫本身不因結果修改**——只在狀態列
        指向結果文件，而四條訊號的定義、四個預期與那條判定原封不動。

        一份會被結果改寫的預先登錄，就不是預先登錄。"""

        assert "預先登錄" in PLAN
        assert "m6-diagnostic-005-result" in PLAN
        assert "本文件不因結果修改" in PLAN


class TestEveryOneReadsTheLaggedColumn:
    """同場次的數字不在資料集裡，所以沒有一個版本的這些函式能前視。
    這條是把那件事釘在排序函式這一層。"""

    @pytest.mark.parametrize("name", INSTITUTIONAL)
    def test_it_reads_no_bare_measure_name(self, name):
        import inspect

        source = inspect.getsource(bt.RANKINGS[name])
        for measure in ("investment_trust_net", "foreign_net", "total_net"):
            assert f".{measure}\n" not in source
            assert f".{measure} " not in source
            assert f'"{measure}"' not in source

    def test_the_cumulative_helper_reads_a_lagged_field(self):
        import inspect

        source = inspect.getsource(bt.investment_trust_net_5)
        assert "investment_trust_net_prior_session" in source


class TestNullIsNeverZero:
    """null 的意思是那天沒有被報價。當成「沒有法人單」會把停牌與退市的
    證券排進沒有人買的那一群裡。"""

    def test_a_single_session_signal_refuses_a_null(self):
        bars = series("investment_trust_net_prior_session", [None])
        assert bt.investment_trust_net(bars, 0) is None

    def test_zero_is_a_number_and_scores(self):
        bars = series("investment_trust_net_prior_session", [0])
        assert bt.investment_trust_net(bars, 0) == 0.0

    def test_a_cumulative_refuses_if_any_of_the_five_is_null(self):
        bars = series("investment_trust_net_prior_session", [1, 2, None, 4, 5])
        assert bt.investment_trust_net_5(bars, 4) is None

    def test_a_cumulative_sums_five_present_values(self):
        bars = series("investment_trust_net_prior_session", [1, 2, 3, 4, 5])
        assert bt.investment_trust_net_5(bars, 4) == 15.0

    def test_a_cumulative_refuses_a_short_history(self):
        """三場次的和與五場次的和不是同一個量。用可得的部分補，等於在同一個
        截面裡拿兩個不同的量互相排序。"""

        bars = series("investment_trust_net_prior_session", [1, 2, 3])
        assert bt.investment_trust_net_5(bars, 2) is None

    def test_a_cumulative_takes_the_last_five_not_the_first(self):
        bars = series("foreign_net_prior_session", [100, 1, 2, 3, 4, 5])
        assert bt.foreign_net_5(bars, 5) == 15.0


class TestDividingByTurnover:
    def test_it_divides_the_same_sessions_net_by_that_sessions_volume(self):
        bars = [bar(total_net_prior_session=500, volume=1000)]
        assert bt.institutional_net_turnover(bars, 0) == 0.5

    @pytest.mark.parametrize("volume", [0, None])
    def test_no_volume_is_none_not_a_very_large_number(self, volume):
        """沒有成交的證券沒有任何東西的佔比，除以它是從一個缺席裡發明一個排名。"""

        bars = [bar(total_net_prior_session=500, volume=volume)]
        assert bt.institutional_net_turnover(bars, 0) is None

    def test_a_null_net_is_none_even_with_volume(self):
        bars = [bar(total_net_prior_session=None, volume=1000)]
        assert bt.institutional_net_turnover(bars, 0) is None

    def test_a_ratio_above_one_is_allowed_and_the_reason_is_written_down(self):
        """TPEx 的法人數字含鉅額、零股與綜合帳戶，而它的成交量欄排除零股與
        盤後，所以比值可以合法地大於一。夾掉它會是一次沒有書面方法的調整。"""

        import inspect

        source = inspect.getsource(bt.institutional_net_turnover)
        assert "exceed one" in source
        bars = [bar(total_net_prior_session=2000, volume=1000)]
        assert bt.institutional_net_turnover(bars, 0) == 2.0


class TestTheHistoryRequirementIsDeclaredNotRemembered:
    """原本是驅動器裡的 if/elif 鏈。漏掉一條排序函式，它會拿到進場規則的
    深度——對五日累計而言那足以讓每一檔都回 None，**沒有錯誤、沒有分數、
    而執行完會產出一份什麼都沒排的報告**。"""

    def test_every_ranking_declares_its_depth(self):
        missing = set(bt.RANKINGS) - set(bt.RANKING_HISTORY_SESSIONS)
        assert not missing, missing

    def test_no_declaration_is_orphaned(self):
        extra = set(bt.RANKING_HISTORY_SESSIONS) - set(bt.RANKINGS)
        assert not extra, extra

    def test_the_cumulative_ones_ask_for_five(self):
        assert bt.RANKING_HISTORY_SESSIONS["investment-trust-net-5"] == 5
        assert bt.RANKING_HISTORY_SESSIONS["foreign-net-5"] == 5

    def test_the_driver_uses_the_declaration(self):
        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert "RANKING_HISTORY_SESSIONS[ranking_name] + 2" in source
        assert 'if ranking_name == "momentum-12-1":' not in source


class TestTheSignatureChangeKeptTheOldRankingsIntact:
    """整個改動的前提。既有兩條若動了一個小數位，所有既有比較都不可比，
    而那不會有任何錯誤訊息。

    實測：`inverse-volatility-60` 仍是 66 個截面、IC +0.0723、t +3.18、
    NDCG 0.2962；`momentum-12-1` 仍是 56 個截面、−0.0080、−0.56、0.3891
    ——與 2026-08-28 的紀錄逐位相同。回測側同組態的差異只有 `built_at`。
    """

    def test_momentum_still_reads_two_closes(self):
        bars = [bar(close=float(i + 1)) for i in range(260)]
        # 252 場次前是 index 7（值 8.0），21 場次前是 index 238（值 239.0）
        assert bt.momentum_12_1(bars, 259) == pytest.approx(239.0 / 8.0 - 1)

    def test_momentum_refuses_a_short_history(self):
        assert bt.momentum_12_1([bar(close=1.0)], 0) is None

    def test_momentum_refuses_a_null_close(self):
        """先前簽章是 `list[float]`，所以 `start <= 0` 對 None 會拋
        TypeError。改成整列之後 None 是可能到達的,要明白地擋。"""

        bars = [bar(close=float(i + 1)) for i in range(260)]
        bars[7] = bar(close=None)
        assert bt.momentum_12_1(bars, 259) is None

    def test_low_volatility_still_negates_so_the_quietest_sorts_first(self):
        calm = [bar(close=100.0 + (i % 2) * 0.1) for i in range(62)]
        wild = [bar(close=100.0 + (i % 2) * 10.0) for i in range(62)]
        assert bt.inverse_volatility_60(calm, 61) > bt.inverse_volatility_60(wild, 61)
        assert all(
            bt.inverse_volatility_60(b, 61) < 0 for b in (calm, wild)
        ), "分數應為負的實現波動"

    def test_a_random_ranking_still_depends_only_on_identity(self):
        one = bt.RANKINGS["random-seed-1"]
        a = one([bar(close=1.0)], 0, market="TWSE", symbol="2330", session="d")
        b = one([bar(close=999.0)], 0, market="TWSE", symbol="2330", session="d")
        assert a == b, "隨機對照不該看價格"


class TestTheResultIsRecordedAsMeasured:
    """判定寫在執行之前，而它落在了「結案」那一邊。

    四條訊號的最大 |t| 是 1.67，而一個隨機種子是 +1.57。依計畫 §4，
    **不會有以法人買賣超為排序函式的候選被登記**。
    """

    RESULT = (
        REPO / "docs" / "evidence"
        / "m6-diagnostic-005-result-institutional-rank-quality-2026-09-05.md"
    ).read_text(encoding="utf-8")

    def test_the_verdict_is_stated(self):
        assert "本方向結案" in self.RESULT

    def test_the_falsified_expectation_is_named_as_falsified(self):
        """預期 2 被否證的方式正好是計畫寫下的那個否證條件。把它寫成
        「結果不如預期」而不是「預期被否證」，是把一次否證變成一句感想。"""

        assert "**否證**" in self.RESULT
        assert "它反而最小" in self.RESULT

    def test_the_extra_trials_are_owned_rather_than_omitted(self):
        """計畫預估 4 筆，實際 9 筆——修掉對照缺陷之後對照組必須重量，
        而重量是執行。多出來的 5 筆記在結果裡。"""

        assert "245" in self.RESULT
        assert "而不是被略過" in self.RESULT

    def test_the_control_defect_is_recorded(self):
        """二十個隨機對照在 `rank_quality` 裡從來不是對照：它沒有傳身分
        關鍵字，所以每一檔都拿到同一個分數。"""

        assert "從來不是對照" in self.RESULT
        source = (REPO / "scripts" / "m6" / "rank_quality.py").read_text(
            encoding="utf-8"
        )
        assert "market=key[0], symbol=key[1], session=session," in source
        assert "which this call omitted until 2026-09-05" in source
