"""The shadow counter's refusals, and the four divergences kept apart.

The counter is the whole point and it is the easiest thing to corrupt. Every
way of making 60 arrive sooner is a way of having watched less, so most of
these tests are about the ledger refusing rather than about it computing.

None of them touch the warehouse. `reconstruct_snapshot` reads the real
tables; the comparison logic does not, and the comparison logic is where a
mistake would silently report zero divergence forever.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m9"))

import observe_session as shadow  # noqa: E402

CONTRACT = REPO / "docs" / "contracts" / "shadow-observation-contract.md"


def snapshot(**overrides):
    base = {
        "session_states": {"TWSE": "official-open", "TPEX": "official-open"},
        "universe": [["TWSE", "2330"], ["TPEX", "6488"]],
        "tradability": {
            '["TWSE", "2330"]': "eligible",
            '["TPEX", "6488"]': "eligible",
        },
        "bars": {},
    }
    base.update(overrides)
    return base


class TestTheFourDivergencesStayApart:
    def test_identical_snapshots_diverge_nowhere(self):
        assert shadow.divergence(snapshot(), snapshot()) == {
            "session_state_divergence": 0,
            "universe_divergence": 0,
            "tradability_divergence": 0,
            "price_divergence": 0,
        }

    def test_a_security_in_only_one_snapshot_is_a_universe_divergence(self):
        """The one that measures survivorship.

        A universe reconstructed later that differs from the one that existed
        on the day is exactly what a backtest can see and the day could not.
        """

        rebuilt = snapshot(
            universe=[["TWSE", "2330"], ["TPEX", "6488"], ["TWSE", "9999"]]
        )
        gaps = shadow.divergence(snapshot(), rebuilt)
        assert gaps["universe_divergence"] == 1
        assert gaps["tradability_divergence"] == 0, (
            "a security present in only one side is a universe difference, "
            "not a disagreement about its state"
        )

    def test_a_state_disagreement_is_not_a_universe_divergence(self):
        rebuilt = snapshot(
            tradability={
                '["TWSE", "2330"]': "restricted",
                '["TPEX", "6488"]': "eligible",
            }
        )
        gaps = shadow.divergence(snapshot(), rebuilt)
        assert gaps["tradability_divergence"] == 1
        assert gaps["universe_divergence"] == 0

    def test_a_closed_market_on_one_side_is_a_session_divergence(self):
        rebuilt = snapshot(
            session_states={"TWSE": "official-open", "TPEX": "official-closed"}
        )
        assert shadow.divergence(snapshot(), rebuilt)["session_state_divergence"] == 1

    def test_they_are_not_summed_into_one_score(self):
        """Merging would let one worsening hide behind another improvement.

        Same reason the candidate report keeps scarcity and sizing apart.
        """

        gaps = shadow.divergence(snapshot(), snapshot())
        assert len(gaps) == 4


class TestTheCounterCannotBeHurried:
    def test_a_capture_failure_does_not_count(self):
        """A day nobody observed cannot be counted as observed.

        Counting it would make the threshold arrive sooner by having watched
        less, which is the exact failure this contract exists to prevent.
        """

        assert not shadow.counts_towards_threshold(
            snapshot(), ("capture-failure-on-the-day",)
        )

    def test_a_day_with_no_open_market_does_not_count(self):
        assert not shadow.counts_towards_threshold(
            snapshot(session_states={"TWSE": "official-closed"}), ()
        )

    def test_an_unexplained_divergence_still_counts_the_day(self):
        """Counting days and fixing defects are different jobs.

        The contract requires every unexplained divergence closed before the
        threshold is reached, which is a separate gate from the count.
        """

        assert shadow.counts_towards_threshold(snapshot(), ("unexplained",))

    def test_the_threshold_is_the_one_m0_set(self):
        assert shadow.THRESHOLD_TRADING_DAYS == 60


class TestTheLedgerRefusesTheThingsThatWouldSpoilIt:
    def test_a_second_observation_of_the_same_day_is_refused(self, tmp_path):
        """Append-only. A re-observation is a reconstruction competing with
        the observation, not a correction of it."""

        (tmp_path / shadow.LEDGER_NAME).write_text(
            json.dumps({"session_date": "2026-08-04"}) + "\n", encoding="utf-8"
        )
        observation = tmp_path / "obs.json"
        observation.write_text(
            json.dumps({"session_date": "2026-08-04", **snapshot()}), encoding="utf-8"
        )
        with pytest.raises(SystemExit) as caught:
            shadow.observe(
                root=tmp_path,
                session="2026-08-04",
                observation_path=observation,
                decision_as_of="2026-08-04",
                reasons=(),
            )
        assert "append-only" in str(caught.value)

    def test_an_observation_for_another_day_is_refused(self, tmp_path):
        """Comparing one day's capture against another day's reconstruction
        produces a divergence that means nothing."""

        observation = tmp_path / "obs.json"
        observation.write_text(
            json.dumps({"session_date": "2026-08-03", **snapshot()}), encoding="utf-8"
        )
        with pytest.raises(SystemExit) as caught:
            shadow.observe(
                root=tmp_path,
                session="2026-08-04",
                observation_path=observation,
                decision_as_of="2026-08-04",
                reasons=(),
            )
        assert "2026-08-03" in str(caught.value)

    def test_an_unknown_reason_code_is_refused(self, tmp_path):
        observation = tmp_path / "obs.json"
        observation.write_text(
            json.dumps({"session_date": "2026-08-04", **snapshot()}), encoding="utf-8"
        )
        with pytest.raises(SystemExit) as caught:
            shadow.observe(
                root=tmp_path,
                session="2026-08-04",
                observation_path=observation,
                decision_as_of="2026-08-04",
                reasons=("it-looked-fine",),
            )
        assert "unknown reason codes" in str(caught.value)


class TestAnObservationHasToBeMadeOnTheDay:
    """The capture side, added 2026-08-29.

    Until it existed, `observe_session.py` had nothing to compare against and
    the count could not leave 0 however many days passed. What makes the file
    an observation rather than a reconstruction is only *when* it was written,
    so the refusal is the whole mechanism.
    """

    def test_a_past_session_is_refused(self, tmp_path):
        sys.path.insert(0, str(REPO / "scripts" / "m9"))
        import capture_observation

        with pytest.raises(SystemExit) as caught:
            capture_observation.main(
                ["--out", str(tmp_path / "o.json"), "--session", "2020-01-02"]
            )
        message = str(caught.value)
        assert "not today" in message
        assert "reconstruction" in message

    def test_the_refusal_explains_why_rather_than_just_refusing(self, tmp_path):
        """A reconstruction compared against the warehouse's reconstruction is
        one answer compared with itself, which would report zero divergence
        forever and look like the strongest possible validation."""

        sys.path.insert(0, str(REPO / "scripts" / "m9"))
        import capture_observation

        with pytest.raises(SystemExit) as caught:
            capture_observation.main(
                ["--out", str(tmp_path / "o.json"), "--session", "2020-01-02"]
            )
        assert "one answer with itself" in str(caught.value)

    def test_the_escape_hatch_marks_the_file_unusable(self):
        """Inspecting the format is legitimate; feeding it to the ledger is
        not, so the file says so about itself rather than relying on whoever
        finds it later to remember."""

        source = (REPO / "scripts" / "m9" / "capture_observation.py").read_text(
            encoding="utf-8"
        )
        assert "backfill-unusable" in source
        assert "Must not be passed to observe_session.py" in source

    def test_it_does_not_fill_in_tradability(self):
        """Tradability is a warehouse judgement built from status and actions,
        not something the closing table states. An observation that filled it
        would be reconstructing -- which is the side being compared against."""

        source = (REPO / "scripts" / "m9" / "capture_observation.py").read_text(
            encoding="utf-8"
        )
        assert '"tradability": {}' in source

    def test_a_missing_closing_table_is_unobserved_not_closed(self):
        """Absence of rows could be a capture that has not run yet. Calling it
        `official-closed` is a claim only the calendar can make."""

        source = (REPO / "scripts" / "m9" / "capture_observation.py").read_text(
            encoding="utf-8"
        )
        assert "unobserved" in source


class TestTheContractSaysWhatItDoesNotDo:
    def test_it_states_that_strategy_shadow_is_blocked(self):
        """M0 section 9 forbids skipping states, and no candidate is
        `validated`. A contract that let this be mistaken for strategy shadow
        would be a way of skipping one."""

        contract = CONTRACT.read_text(encoding="utf-8")
        assert "策略 shadow 走不了" in contract
        assert "validated" in contract

    def test_it_states_the_count_starts_at_zero_and_cannot_be_backfilled(self):
        contract = CONTRACT.read_text(encoding="utf-8")
        assert "不可回溯補算" in contract

    def test_the_producer_declares_the_version_the_contract_carries(self):
        """The fifth pair of this kind. Three of the first four disagreed."""

        contract = CONTRACT.read_text(encoding="utf-8")
        assert shadow.CONTRACT_VERSION in contract

    def test_the_reason_codes_match_the_contract(self):
        contract = CONTRACT.read_text(encoding="utf-8")
        for code in shadow.REASON_CODES:
            assert code in contract, f"the contract does not list {code}"
