"""Owner 指定的策略：週 MACD 黃金交叉 × 上市五日量前 30 × 上市五日法人買超前 30，
報酬／停損 = 2.5。

四個部分，每一個都有一種會安靜錯掉的方式：

    週線     用進行中的那一週，訊號會隨「今天是星期幾」而不同
    前 30    分母若是固定名單，某檔會因為鄰居有 null 而被拱上去
    黃金交叉 若寫成「在上方」而不是「剛穿上去」，長多會天天觸發
    停利     若排在停損之後判斷，跳空穿過停利再崩的那一天會記成虧損

這一份把四個都釘住。
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

import run_ledger_backtest as bt  # noqa: E402


def bar(session: str, **values):
    values["session_date"] = session
    return bt.Bar(tuple(values.get(name) for name in bt.DATASET_COLUMNS))


# V 型週線，以及它**恰好在最後一個完整週**產生黃金交叉的長度。
#
# 截斷長度由 `macd_golden_cross` 自己找出來，不是寫死一個數字。寫死的那個
# 數字會在 12/26/9 任何一個被改動的那天變成一個安靜通過的空測試——訊號不再
# 在最後一週發生，篩選回傳空清單，而「空清單」在多數斷言裡看起來像是通過。
V_SHAPE = [100.0 - i for i in range(45)] + [55.0 + i * 2 for i in range(35)]
CROSS_AT = next(n for n in range(40, 81) if bt.macd_golden_cross(V_SHAPE[:n]))


class TestOnlyCompletedWeeks:
    """進行中的那一週被丟掉。週三出現、週五消失的交叉不是週線交叉，
    而收進來會讓同一條規則因為執行日不同而選到不同的證券。"""

    def test_the_week_in_progress_is_dropped(self):
        # 2019-01-07 是週一。兩個完整週加上第三週的頭兩天。
        bars = [
            bar("2019-01-07", close=1.0), bar("2019-01-11", close=2.0),
            bar("2019-01-14", close=3.0), bar("2019-01-18", close=4.0),
            bar("2019-01-21", close=5.0), bar("2019-01-22", close=6.0),
        ]
        assert bt.weekly_closes(bars) == [2.0, 4.0]

    def test_a_week_takes_its_last_close(self):
        bars = [bar("2019-01-07", close=1.0), bar("2019-01-09", close=9.0),
                bar("2019-01-14", close=3.0)]
        assert bt.weekly_closes(bars) == [9.0]

    def test_a_holiday_shortened_week_still_counts_as_a_week(self):
        """春節那一週只有兩個場次，它仍然是一週。用「五個場次等於一週」
        會讓假期把週線推移。"""

        bars = [bar("2019-02-11", close=1.0), bar("2019-02-12", close=2.0),
                bar("2019-02-18", close=3.0)]
        assert bt.weekly_closes(bars) == [2.0]

    def test_a_null_close_is_skipped_not_treated_as_a_week(self):
        bars = [bar("2019-01-07", close=None), bar("2019-01-08", close=2.0),
                bar("2019-01-14", close=3.0)]
        assert bt.weekly_closes(bars) == [2.0]


class TestTheExponentialAverage:
    def test_it_is_seeded_with_a_simple_average(self):
        """[1, 2, 3] span 2：種子 (1+2)/2 = 1.5，然後
        (3 − 1.5) × 2/3 + 1.5 = 2.5。手算，不是拿實作跟自己比。"""

        assert bt._ema([1.0, 2.0, 3.0], 2) == pytest.approx([1.5, 2.5])

    def test_a_short_series_is_none_not_a_partial_average(self):
        assert bt._ema([1.0], 2) is None

    def test_a_flat_series_stays_flat(self):
        assert bt._ema([5.0] * 10, 3) == pytest.approx([5.0] * 8)


class TestAGoldenCrossIsAnEventNotAState:
    def test_a_monotonic_rise_does_not_cross_every_week(self):
        """長多裡 MACD 一直在訊號線上方。若寫成「在上方」，這條規則會
        每一週都觸發，而那不是黃金交叉。"""

        rising = [100.0 * (1.02 ** i) for i in range(80)]
        crosses = sum(
            1 for n in range(40, 81) if bt.macd_golden_cross(rising[:n])
        )
        assert crosses <= 1, f"單調上漲觸發了 {crosses} 次"

    def test_a_v_shape_crosses_once_on_the_way_up(self):
        weeks = [100.0 - i for i in range(45)] + [55.0 + i * 2 for i in range(35)]
        crosses = [
            n for n in range(40, 81) if bt.macd_golden_cross(weeks[:n])
        ]
        assert len(crosses) == 1, crosses

    def test_a_falling_series_never_crosses_up(self):
        falling = [100.0 * (0.98 ** i) for i in range(80)]
        assert not any(
            bt.macd_golden_cross(falling[:n]) for n in range(40, 81)
        )

    def test_too_little_history_is_false_not_an_error(self):
        assert bt.macd_golden_cross([100.0] * 10) is False
        assert bt.macd_golden_cross([]) is False

    def test_the_warmup_is_declared_and_is_enough(self):
        """26 週慢線 + 9 週訊號線 + 1 週比較 = 36 週。深度不足時每一檔都回
        False——**沒有錯誤、沒有訊號、跑完是一份空報告**。"""

        assert bt.SCREEN_HISTORY_SESSIONS == (26 + 9 + 1) * 5
        assert bt.ENTRY_HISTORY_SESSIONS["weekly-macd-screen"] == bt.SCREEN_HISTORY_SESSIONS
        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert "ENTRY_HISTORY_SESSIONS[entry_rule] + 2" in source


class TestTheScreenIsListedOnlyAndAllThree:
    def rising_history(self, market: str, symbol: str, **extra):
        """一段在最後一個完整週產生黃金交叉的日線歷史。

        每週五個場次，最後再補一天代表進行中的那一週——`weekly_closes` 會
        把它丟掉，而它在這裡的作用是證明它真的被丟掉了。
        """

        import datetime as dt

        bars = []
        day = dt.date(2019, 1, 7)
        for close in V_SHAPE[:CROSS_AT]:
            for _ in range(5):
                bars.append(
                    bar(
                        day.isoformat(), close=close, market=market,
                        symbol=symbol, **extra,
                    )
                )
                day += dt.timedelta(days=1)
            day += dt.timedelta(days=2)
        bars.append(
            bar(
                day.isoformat(), close=V_SHAPE[CROSS_AT - 1],
                market=market, symbol=symbol, **extra,
            )
        )
        return bars, bars[-1].session_date

    def test_a_tpex_security_is_never_screened(self):
        """上市是策略的一部分，不是 `--universe` 模式。"""

        bars, session = self.rising_history(
            "TPEX", "6488", volume=10_000, total_net_prior_session=10_000
        )
        signals = bt.weekly_macd_screen_signals(
            {("TPEX", "6488"): bars}, session, stop_pct=Decimal("0.08")
        )
        assert signals == []

    def test_a_null_five_session_total_drops_the_security_from_both_sides(self):
        """缺一個值就出局，而且是從分子與分母同時出局——否則它的鄰居會因為
        它缺席而被拱進前 30。"""

        bars, session = self.rising_history(
            "TWSE", "2330", volume=10_000, total_net_prior_session=None
        )
        signals = bt.weekly_macd_screen_signals(
            {("TWSE", "2330"): bars}, session, stop_pct=Decimal("0.08")
        )
        assert signals == []

    def test_all_three_conditions_together_produce_a_signal(self):
        bars, session = self.rising_history(
            "TWSE", "2330", volume=10_000, total_net_prior_session=10_000
        )
        signals = bt.weekly_macd_screen_signals(
            {("TWSE", "2330"): bars}, session, stop_pct=Decimal("0.08")
        )
        assert len(signals) == 1
        assert (signals[0].market, signals[0].symbol) == ("TWSE", "2330")

    def test_the_stop_sits_the_declared_distance_below_the_signal_close(self):
        bars, session = self.rising_history(
            "TWSE", "2330", volume=10_000, total_net_prior_session=10_000
        )
        signals = bt.weekly_macd_screen_signals(
            {("TWSE", "2330"): bars}, session, stop_pct=Decimal("0.08")
        )
        close = Decimal(str(bars[-1].close))
        assert signals[0].stop_price == close * Decimal("0.92")

    def test_the_thirty_first_by_volume_is_out(self):
        """前 30 是截面的，不是門檻。第 31 名不管多大都出局。"""

        history = {}
        for rank in range(35):
            bars, session = self.rising_history(
                "TWSE", f"{1000 + rank}",
                volume=10_000 - rank, total_net_prior_session=10_000,
            )
            history[("TWSE", f"{1000 + rank}")] = bars
        signals = bt.weekly_macd_screen_signals(
            history, session, stop_pct=Decimal("0.08")
        )
        assert len(signals) == bt.SCREEN_TOP_N
        assert "1034" not in {s.symbol for s in signals}

    def test_the_order_is_declared_rather_than_left_to_the_dict(self):
        """名額比合格者少時，是誰進場由這個順序決定。"""

        history = {}
        for rank in range(3):
            bars, session = self.rising_history(
                "TWSE", f"{2000 + rank}",
                volume=10_000, total_net_prior_session=100 * (rank + 1),
            )
            history[("TWSE", f"{2000 + rank}")] = bars
        signals = bt.weekly_macd_screen_signals(
            history, session, stop_pct=Decimal("0.08")
        )
        assert [s.symbol for s in signals] == ["2002", "2001", "2000"]


class TestTheProfitTargetComesFromTheFillNotThePlan:
    """停損由訊號場次的收盤價定，而進場發生在次日開盤，所以帳戶實際背的
    風險不是訊號規劃的風險。用規劃風險算停利，會把停利放在一個帳戶並沒有
    在承擔的距離的 2.5 倍上。"""

    def test_the_field_exists_and_defaults_to_none(self):
        position = bt.OpenPosition(
            market="TWSE", symbol="2330", entry_session="d",
            entry_price=Decimal("100"), stop_price=Decimal("92"), quantity=1000,
        )
        assert position.target_price is None

    def test_the_driver_derives_it_from_the_fill(self):
        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert "reward_risk\n                        * ((result.fill_price or entry) - signal.stop_price)" in source
        assert "Derived from the fill, not from the signal" in source

    def test_a_gap_through_the_target_exits_at_the_open_not_the_stop(self):
        """**唯一一個停損不優先的情形。** 跳空開在停利價之上，那張限價單
        在開盤集合競價就成交了，之後才崩到停損——把它記成停損，是把帳戶
        已經賣掉的部位再賠一次。"""

        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert "The one case where the stop does not come first" in source
        assert 'reason, price = "target", opened' in source
        # 順序本身：開盤穿過停利要排在停損檢查之前。
        gap = source.index("if target is not None and opened >= target:")
        stop = source.index("elif low <= position.stop_price:")
        assert gap < stop

    def test_touching_the_target_intraday_fills_at_the_target(self):
        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert 'reason, price = "target", target' in source

    def test_the_assumption_says_what_it_now_does(self):
        """`stop_assumed_to_precede_target_within_a_session` 從 True 改成一句
        帶但書的話。它在還沒有任何東西會停利時就寫成 True 了。"""

        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert "except when the session opened at or above the target" in source
        assert '"stop_assumed_to_precede_target_within_a_session": True,' not in source


class TestTheReportSaysWhatWasRun:
    def test_the_entry_rule_is_registered(self):
        assert "weekly-macd-screen" in bt.ENTRY_RULES

    def test_the_strategy_name_is_not_the_rank_only_one(self):
        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        assert "weekly-macd-cross-in-top-30-volume-and-institutional" in source

    def test_the_screen_parameters_are_reported(self):
        source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        for key in ("top_n", "cumulative_sessions", "macd_weeks", "tie_break"):
            assert f'"{key}"' in source
