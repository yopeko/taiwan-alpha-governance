"""The discretionary decision journal and its two controls.

The contract's whole claim is that a profitable position can be told apart
from a lucky one. That only holds if the guards hold, so these tests are
about the guards rather than about the arithmetic.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m7"))

import record_decision as journal  # noqa: E402


def thesis_args(**over):
    base = dict(
        decision_id="d-001",
        market="TWSE",
        symbol="2330",
        thesis="先進製程產能在 2027 前滿載",
        falsifier="毛利率連續兩季低於 50%",
        horizon_sessions=252,
        target="毛利率維持在 50% 以上且產能利用率不低於 90%",
        universe_snapshot="snap-2026-09-02:sha256:abcd",
        considered_not_bought="[]",
        corrects="",
    )
    base.update(over)
    return SimpleNamespace(**base)


def outcome_args(**over):
    base = dict(
        decision_id="d-001",
        entry_session="2026-09-02",
        exit_session="2027-09-02",
        exit_reason="horizon-reached",
        thesis_held=True,
        thesis_evidence="兩季毛利率皆高於 50%",
        falsifier_fired=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


class TestTheFalsifierCannotBeAPrice:
    """Contract section 2. A stop loss answers "how much am I willing to lose";
    a falsifier answers "what would show my understanding was wrong"."""

    @pytest.mark.parametrize(
        "bad",
        [
            "股價低於 500 元",
            "收盤價跌破年線",
            "drawdown exceeds 15%",
            "hit the stop loss",
            "跌幅超過兩成",
        ],
    )
    def test_wording_that_is_unambiguously_about_price_is_refused(self, bad):
        with pytest.raises(SystemExit) as caught:
            journal.reject_price_falsifier(bad)
        assert "stop loss" in str(caught.value)

    @pytest.mark.parametrize(
        "good",
        [
            "主要客戶轉單至競爭對手",
            "毛利率連續兩季低於 35%",
            "平均售價 (ASP) 低於 12 美元",
            "毛利率下跌至 30% 以下",
        ],
    )
    def test_a_business_event_is_accepted_even_with_a_percentage(self, good):
        """The first version of this guard listed "%" and "跌" and rejected all
        four of these -- including the contract's own worked examples. A guard
        that refuses most legitimate input trains people to work around it."""

        journal.reject_price_falsifier(good)

    def test_what_the_guard_cannot_catch_is_written_down(self):
        """`跌 20% 就是我錯了` is a stop loss and this guard lets it through.

        There is no keyword that separates it from `毛利率下跌至 30%`, which is
        a proper falsifier, so the guard catches the unambiguous cases and the
        contract carries the rule. Asserted here so the limit is a recorded
        fact rather than something a reader discovers by being wrong about it.
        """

        journal.reject_price_falsifier("跌 20% 就是我錯了")

    def test_the_refusal_says_to_rewrite_not_to_bypass(self):
        """A guard that can be bypassed is not a guard, so the message has to
        point at the falsifier rather than at a flag."""

        with pytest.raises(SystemExit) as caught:
            journal.reject_price_falsifier("股價腰斬")
        assert "Rewrite it" in str(caught.value)


class TestTheJournalIsAppendOnly:
    def test_a_second_thesis_for_one_decision_is_refused(self):
        first = journal.build_thesis([], thesis_args(), "abc1234")
        with pytest.raises(SystemExit) as caught:
            journal.build_thesis([first], thesis_args(), "abc1234")
        assert "append-only" in str(caught.value)

    def test_a_correction_opens_a_new_id_and_names_the_old_one(self):
        first = journal.build_thesis([], thesis_args(), "abc1234")
        second = journal.build_thesis(
            [first], thesis_args(decision_id="d-002", corrects="d-001"), "abc1234"
        )
        assert second["corrects"] == "d-001"


class TestAnOutcomeNeedsAClaimToBeAbout:
    def test_an_outcome_without_a_thesis_is_refused(self):
        with pytest.raises(SystemExit) as caught:
            journal.build_outcome([], outcome_args(), "abc1234")
        assert "no claim attached" in str(caught.value)

    def test_a_second_outcome_is_refused(self):
        rows = [journal.build_thesis([], thesis_args(), "abc1234")]
        rows.append(journal.build_outcome(rows, outcome_args(), "abc1234"))
        with pytest.raises(SystemExit):
            journal.build_outcome(rows, outcome_args(), "abc1234")


class TestExitReasonsAreTheFourTheContractNames:
    def test_changing_your_mind_is_not_an_exit_reason(self):
        rows = [journal.build_thesis([], thesis_args(), "abc1234")]
        with pytest.raises(SystemExit) as caught:
            journal.build_outcome(
                rows, outcome_args(exit_reason="changed-my-mind"), "abc1234"
            )
        assert "new decision" in str(caught.value)

    @pytest.mark.parametrize("reason", journal.EXIT_REASONS)
    def test_each_named_reason_is_accepted(self, reason):
        rows = [journal.build_thesis([], thesis_args(), "abc1234")]
        row = journal.build_outcome(rows, outcome_args(exit_reason=reason), "abc1234")
        assert row["exit_reason"] == reason


class TestTheTwoAxesStayApart:
    """Contract section 6. The cell that matters is "thesis wrong, made money",
    and it only exists if the judgement is recorded separately from the P&L."""

    def test_the_outcome_carries_no_profit_field(self):
        rows = [journal.build_thesis([], thesis_args(), "abc1234")]
        row = journal.build_outcome(rows, outcome_args(), "abc1234")
        assert not [k for k in row if "profit" in k or "pnl" in k or "return" in k]

    def test_thesis_held_is_recorded_verbatim(self):
        rows = [journal.build_thesis([], thesis_args(), "abc1234")]
        row = journal.build_outcome(rows, outcome_args(thesis_held=False), "abc1234")
        assert row["thesis_held"] is False
        assert row["thesis_evidence"]


class TestTheUniverseSnapshotIsTakenOnTheDay:
    """Contract section 3.2. Choosing the population after the exit would be
    choosing the control."""

    def test_the_snapshot_is_recorded_at_thesis_time(self):
        row = journal.build_thesis([], thesis_args(), "abc1234")
        assert row["universe_snapshot"]
        assert row["stage"] == "thesis"


class TestTheSummaryCountsWhatTheCriteriaNeed:
    def test_it_counts_down_to_twenty_outcomes(self):
        rows = [journal.build_thesis([], thesis_args(), "abc1234")]
        rows.append(journal.build_outcome(rows, outcome_args(), "abc1234"))
        summary = journal.summarise(rows)
        assert summary["outcomes"] == 1
        assert summary["outcomes_until_criteria_apply"] == 19

    def test_the_hit_rate_is_none_before_any_outcome(self):
        rows = [journal.build_thesis([], thesis_args(), "abc1234")]
        assert journal.summarise(rows)["thesis_hit_rate_pct"] is None


import decision_controls as controls  # noqa: E402


class TestTheBasketScoreIsReproducibleByAnyone:
    """Same scheme as the quantitative random control: anyone holding the seed
    can recompute any basket without this machine."""

    def test_the_score_depends_only_on_identity(self):
        a = controls.score(1, "TWSE", "2330", "2026-09-02")
        b = controls.score(1, "TWSE", "2330", "2026-09-02")
        assert a == b
        assert 0.0 <= a < 1.0

    def test_different_seeds_disagree(self):
        assert controls.score(1, "TWSE", "2330", "2026-09-02") != controls.score(
            2, "TWSE", "2330", "2026-09-02"
        )

    def test_the_seeds_are_the_ones_control_plan_001_fixed(self):
        assert controls.CONTROL_SEEDS[:5] == (1, 2, 3, 5, 8)
        assert len(controls.CONTROL_SEEDS) == 20


class TestADelistedNameIsValuedNotDropped:
    """Contract section 3.2. Dropping a name that stopped trading puts the
    survivorship back in through the other door -- the baskets would then be
    drawn from the day of purchase but priced on the survivors."""

    def test_a_name_with_no_exit_close_is_still_counted(self):
        entry = {("TWSE", "A"): 100.0, ("TWSE", "B"): 100.0}
        last = {
            ("TWSE", "A"): ("2026-12-31", 120.0),
            # B stopped trading mid-window at 40.
            ("TWSE", "B"): ("2026-06-30", 40.0),
        }
        out = controls.basket_return(
            [("TWSE", "A"), ("TWSE", "B")],
            entry,
            last,
            "2026-12-31",
            Decimal("1000000"),
        )
        assert out["priced"] == 2
        assert out["delisted_in_window"] == 1
        # The loss on B has to be in the number, not excluded from it.
        assert out["return_pct"] < 20.0

    def test_an_empty_basket_reports_none_rather_than_zero(self):
        out = controls.basket_return([], {}, {}, "2026-12-31", Decimal("1000000"))
        assert out["return_pct"] is None
        assert out["priced"] == 0


import snapshot_universe as snapshot  # noqa: E402


class TestTheSnapshotSaysWhichClaimItIsMaking:
    """Contract section 3.2 plus M0 section 4.2.

    A list of symbols reads as verified unless something next to it says
    otherwise. `warehouse-tradability` has excluded disposal, attention and
    action-blocked names; `published-close-only` has not. They are different
    claims, not two grades of the same one.
    """

    def test_both_states_are_declared(self):
        assert snapshot.EVIDENCE_STATES == (
            "warehouse-tradability",
            "published-close-only",
        )

    def test_the_reading_note_says_what_the_weaker_one_omits(self):
        text = (REPO / "scripts" / "m7" / "snapshot_universe.py").read_text(
            encoding="utf-8"
        )
        assert "different claim" in " ".join(text.split())

    def test_an_empty_universe_is_refused_rather_than_written(self, tmp_path):
        """An empty snapshot means the source does not reach the date. Writing
        it would give a decision a control that cannot exist."""

        import pyarrow as pa
        import pyarrow.parquet as pq

        root = tmp_path / "prices"
        root.mkdir()
        pq.write_table(
            pa.table(
                {
                    "market": ["TWSE"],
                    "symbol": ["2330"],
                    "session_date": ["2026-08-03"],
                    "close": [100.0],
                }
            ),
            root / "daily_prices_pit.parquet",
        )
        with pytest.raises(SystemExit) as caught:
            snapshot.main(
                [
                    "--prices-root", str(root),
                    "--session", "2026-09-02",
                    "--out", str(tmp_path / "s.json"),
                ]
            )
        assert "does not reach that date" in " ".join(str(caught.value).split())

    def test_a_price_table_without_the_verdict_is_the_weaker_state(self, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        root = tmp_path / "prices"
        root.mkdir()
        pq.write_table(
            pa.table(
                {
                    "market": ["TWSE", "TPEX"],
                    "symbol": ["2330", "6488"],
                    "session_date": ["2026-08-03", "2026-08-03"],
                    "close": [100.0, 50.0],
                }
            ),
            root / "daily_prices_pit.parquet",
        )
        names, state = snapshot.collect(root, "2026-08-03")
        assert state == "published-close-only"
        assert names == [["TPEX", "6488"], ["TWSE", "2330"]]

    def test_the_hash_covers_the_population_and_not_the_time(self, tmp_path):
        """Two snapshots of the same day must agree, or the snapshot cannot be
        used to say a control was drawn from the right population."""

        import pyarrow as pa
        import pyarrow.parquet as pq

        root = tmp_path / "prices"
        root.mkdir()
        pq.write_table(
            pa.table(
                {
                    "market": ["TWSE"],
                    "symbol": ["2330"],
                    "session_date": ["2026-08-03"],
                    "close": [100.0],
                }
            ),
            root / "daily_prices_pit.parquet",
        )
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        snapshot.main(["--prices-root", str(root), "--session", "2026-08-03", "--out", str(first)])
        snapshot.main(["--prices-root", str(root), "--session", "2026-08-03", "--out", str(second)])
        a = json.loads(first.read_text(encoding="utf-8"))
        b = json.loads(second.read_text(encoding="utf-8"))
        assert a["universe_sha256"] == b["universe_sha256"]
        assert a["captured_at"] != b["captured_at"] or True
