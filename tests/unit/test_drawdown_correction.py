"""修正既有產物的回撤，以及那個工具自己的兩條規矩。

102 份既有報告全部帶權益曲線，所以真正的最大回撤**由每份檔案自己就算得
出來**——修正是一次計算，不是一次數小時的重跑。這和 2026-09-04 的停損成交價
修正性質不同：那一次改的是成交，所有下游數字都變了。

兩條規矩：
    不改寫產物   一份存下的報告就是那次執行產出的東西。就地改寫會讓
                 「修正過的」與「本來就對的」再也分不出來。
    不跳過       一份沒有權益曲線的報告要被報成「無法修正」，而不是從
                 掃描結果裡消失——一份工具檢查不到的產物，正是讀者會以為
                 它檢查過的那一份。
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

import correct_drawdown as tool  # noqa: E402

SOURCE = (REPO / "scripts" / "m6" / "correct_drawdown.py").read_text(encoding="utf-8")


def report(navs, reported, **extra):
    return {
        "drawdown_pct": reported,
        "equity": [{"session": f"d{i}", "nav": n} for i, n in enumerate(navs)],
        "opening_cash": 100.0,
        "return_pct": 0.0,
        "strategy": {"name": "s", "ranking_function": ""},
        **extra,
    }


class TestItCorrectsFromTheStoredCurve:
    def test_a_recovered_run_is_corrected(self, tmp_path):
        """報告值 0、真值 60——這就是缺陷本身的形狀。"""

        (tmp_path / "a.json").write_text(
            json.dumps(report([100, 40, 100], 0.0)), encoding="utf-8"
        )
        rows = tool.corrections([tmp_path])
        assert len(rows) == 1
        assert rows[0]["true_max_drawdown_pct"] == pytest.approx(60.0)
        assert rows[0]["understated_by_pp"] == pytest.approx(60.0)

    def test_a_run_that_ended_at_its_low_needs_no_correction(self, tmp_path):
        (tmp_path / "a.json").write_text(
            json.dumps(report([100, 150, 50], 100 * (150 - 50) / 150)),
            encoding="utf-8",
        )
        assert tool.corrections([tmp_path])[0]["understated_by_pp"] == pytest.approx(0.0)


class TestItDoesNotHideWhatItCannotCheck:
    def test_a_report_without_an_equity_curve_is_reported_not_skipped(self, tmp_path):
        """跳過它，讀者會以為它被檢查過了。"""

        (tmp_path / "a.json").write_text(
            json.dumps({"drawdown_pct": 12.0}), encoding="utf-8"
        )
        rows = tool.corrections([tmp_path])
        assert len(rows) == 1
        assert rows[0]["true_max_drawdown_pct"] is None
        assert "cannot be corrected" in rows[0]["note"]

    def test_a_file_that_is_not_a_report_is_ignored(self, tmp_path):
        (tmp_path / "other.json").write_text(json.dumps({"hello": 1}), encoding="utf-8")
        assert tool.corrections([tmp_path]) == []

    def test_an_empty_sweep_is_refused_rather_than_reported_as_clean(self, tmp_path):
        """「掃到 0 份、全部沒問題」與「路徑打錯了」長得一模一樣。"""

        with pytest.raises(SystemExit) as caught:
            tool.main([str(tmp_path)])
        assert "usually a wrong path" in str(caught.value)


class TestItDoesNotRewriteTheArtefacts:
    def test_the_stored_report_is_untouched(self, tmp_path):
        path = tmp_path / "a.json"
        original = json.dumps(report([100, 40, 100], 0.0))
        path.write_text(original, encoding="utf-8")
        tool.corrections([tmp_path])
        assert path.read_text(encoding="utf-8") == original

    def test_the_reason_is_written_down(self):
        assert "It does not rewrite the artefacts" in SOURCE
        assert "no way to tell a corrected file from one" in SOURCE


class TestTheRepositoryHadTwoDefinitionsOfDrawdown:
    """比 bug 本身更值得記的那件事。

    `compare_candidates.py` 與 `measure_halt_events.py` 各自從權益曲線正確地
    算最大回撤，而後者把回測報告那個欄位命名為 `final_drawdown_pct_from_run`
    ——**有人早就知道它是期末值**，在那裡命名正確，而驅動器仍然把它印在
    「最大回撤」底下。

    同一個名字兩個定義，比一個統一的錯誤更難發現。
    """

    def test_the_comparison_tool_computes_the_maximum(self):
        source = (REPO / "scripts" / "m6" / "compare_candidates.py").read_text(
            encoding="utf-8"
        )
        assert "drawdown = max(drawdown, (peak - row[\"nav\"]) / peak)" in source
        assert "drawdown_pct_in_window" in source

    def test_the_halt_tool_already_named_the_run_field_correctly(self):
        source = (REPO / "scripts" / "m7" / "measure_halt_events.py").read_text(
            encoding="utf-8"
        )
        assert "final_drawdown_pct_from_run" in source

    def test_the_evidence_records_that_it_was_two_definitions(self):
        evidence = (
            REPO / "docs" / "evidence"
            / "m6-drawdown-was-terminal-not-maximum-2026-09-05.md"
        ).read_text(encoding="utf-8")
        assert "final_drawdown_pct_from_run" in evidence
        assert "同一個名字有兩個定義" in evidence
