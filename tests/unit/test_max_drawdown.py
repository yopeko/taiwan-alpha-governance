"""「最大回撤」必須是最大回撤。

`ledger.drawdown` 算的是 `(高水位 − 最新) / 高水位`——**此刻的回撤**。驅動器
從第一版起就把它當成 `drawdown_pct` 報出，並印在「最大回撤」標題下。

兩者只有在執行結束於最低點時相等。而那正是它活這麼久的原因：M0 規模的動能
候選結束在低點附近（報 65.93%，權益曲線也是 65.93%），所以每一個看過它的人
都看到一個對的數字。

參考規模的同一條策略結束在**歷史高點**，報 **0.00%**，權益曲線是 **59.27%**。

M0 §8.1 的 8% 硬停止是一個**回撤**門檻，所以每一個沒有結束在谷底的候選，
被拿去比的都是錯的那個數字。
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

DRIVER = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
    encoding="utf-8"
)


def curve(*navs: float) -> list[dict]:
    return [{"session": f"d{i}", "nav": nav} for i, nav in enumerate(navs)]


class TestItIsTheDeepestFallNotTheLastOne:
    def test_a_run_that_recovers_still_reports_its_fall(self):
        """這一條就是缺陷本身。100 → 40 → 100 的最大回撤是 60%，
        而期末回撤是 0%。"""

        assert bt.max_drawdown_pct(curve(100, 40, 100)) == pytest.approx(60.0)

    def test_a_run_that_ends_at_its_low_agrees_with_the_terminal_figure(self):
        """兩者相等的那個情形——而它就是讓這個缺陷活下來的那個情形。"""

        assert bt.max_drawdown_pct(curve(100, 150, 50)) == pytest.approx(
            100 * (150 - 50) / 150
        )

    def test_the_peak_is_the_running_peak_not_the_first_value(self):
        assert bt.max_drawdown_pct(curve(50, 200, 100)) == pytest.approx(50.0)

    def test_a_monotonic_rise_has_no_drawdown(self):
        assert bt.max_drawdown_pct(curve(100, 110, 120)) == 0.0

    def test_an_empty_curve_is_zero_not_an_error(self):
        assert bt.max_drawdown_pct([]) == 0.0

    def test_two_separate_falls_report_the_deeper_one(self):
        """第二個谷比較淺，但它比較近。報比較近的那個，就是這個缺陷。"""

        assert bt.max_drawdown_pct(curve(100, 30, 90, 60, 90)) == pytest.approx(70.0)


class TestBothNumbersAreReported:
    def test_drawdown_pct_is_the_maximum(self):
        assert '"drawdown_pct": max_drawdown_pct(equity),' in DRIVER

    def test_the_terminal_figure_is_kept_and_named(self):
        """期末回撤是一個關於真實帳戶的真實數字，它只是不叫最大回撤。
        拿掉它會讓一個既有欄位無聲消失。"""

        assert '"terminal_drawdown_pct": float(ledger.drawdown) * 100,' in DRIVER

    def test_the_measurement_that_found_it_is_written_down(self):
        assert "reported **0.00%** and its equity curve says **59.27%**" in DRIVER
        assert "which is why this survived every eye that looked at it" in DRIVER

    def test_it_can_correct_an_old_artefact_without_a_rerun(self):
        """每一份報告都帶 `equity`，所以修正不需要重跑。這句話寫在函式旁邊，
        因為它決定了這個缺陷的代價是一次計算還是一次數小時的重跑。"""

        assert "without being re-run" in DRIVER
