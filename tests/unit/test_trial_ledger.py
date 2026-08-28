"""The trial ledger's refusals, and the distinction it turns on.

The ledger exists because this project counted seal openings carefully and
counted development trials not at all -- the careful count was 0 and the
absent one was nine, four of them a slot sweep a decision was taken from.

The distinction that matters is not "was this a real candidate" but "did its
result change anything". These tests are mostly about that line and about the
three refusals, because a ledger that can be quietly wrong is worse than none:
it looks like a count.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m6"))

import record_trial as ledger  # noqa: E402

CONTRACT = REPO / "docs" / "contracts" / "trial-ledger-contract.md"

CONFIG = {"ranking": "momentum-12-1", "universe": "all", "lookback": 20}


def row(**overrides):
    base = dict(
        existing=[],
        config=CONFIG,
        dataset="ds",
        purpose="candidate",
        influenced=False,
        choice="",
        result_pointer="somewhere",
        basis="contemporaneous",
        commit="abc123",
        rerun_reason="",
    )
    base.update(overrides)
    return ledger.build_row(**base)


class TestTheBudgetCountsChoicesNotRuns:
    def test_a_reported_but_unselected_run_costs_nothing(self):
        """The two participation rates are reported jointly and never chosen
        between. Reading both is the contract; picking one is not."""

        rows = [row(influenced=False)]
        assert ledger.summarise(rows)["selection_budget_spent"] == 0
        assert ledger.summarise(rows)["trials_total"] == 1

    def test_a_run_a_decision_came_from_costs_one(self):
        rows = [row(influenced=True, choice="D16: slots 2 -> 10")]
        assert ledger.summarise(rows)["selection_budget_spent"] == 1

    def test_every_run_is_counted_even_when_it_costs_nothing(self):
        """Section 1 has no exceptions, because an exception becomes a place
        to put the runs one would rather not count."""

        rows = [row(influenced=False), row(influenced=True, choice="x")]
        stats = ledger.summarise(rows)
        assert stats["trials_total"] == 2
        assert stats["selection_budget_spent"] == 1


class TestTheThreeRefusals:
    def test_claiming_influence_without_naming_it_is_refused(self):
        """Saying a run changed something without saying what it changed is
        not saying anything."""

        with pytest.raises(SystemExit) as caught:
            row(influenced=True, choice="")
        assert "choice_made" in str(caught.value)

    def test_a_repeat_configuration_needs_a_reason(self):
        """Re-running is legitimate -- a fixed bug should be re-run -- but
        unexplained it turns one trial into two, or two into one."""

        first = row()
        with pytest.raises(SystemExit) as caught:
            row(existing=[first])
        assert "rerun-reason" in str(caught.value)

    def test_a_repeat_with_a_reason_is_allowed(self):
        first = row()
        second = row(existing=[first], rerun_reason="re-ran after the exit-side bug")
        assert second["trial_number"] == 2
        assert second["rerun_reason"]

    def test_an_unknown_purpose_is_refused(self):
        with pytest.raises(SystemExit):
            row(purpose="just-looking")


class TestBackfilledRowsSaySo:
    def test_record_basis_is_required_to_be_one_of_two(self):
        with pytest.raises(SystemExit):
            row(basis="probably-accurate")

    def test_reconstructed_and_contemporaneous_are_counted_apart(self):
        """Reconstruction misses runs that left no document, and the ones it
        misses are the ones most likely to have been unflattering."""

        rows = [row(basis="reconstructed"), row(existing=[row()], rerun_reason="r")]
        stats = ledger.summarise(rows)
        assert stats["reconstructed"] + stats["contemporaneous"] == 2

    def test_the_contract_explains_why_the_distinction_is_required(self):
        contract = CONTRACT.read_text(encoding="utf-8")
        assert "record_basis" in contract
        assert "事後" in contract


class TestTheLedgerAgreesWithItsContract:
    def test_the_declared_version_is_in_the_document(self):
        assert ledger.CONTRACT_VERSION in CONTRACT.read_text(encoding="utf-8")

    def test_the_purposes_match_the_contract(self):
        contract = CONTRACT.read_text(encoding="utf-8")
        for purpose in ledger.PURPOSES:
            assert purpose in contract

    def test_the_contract_refuses_to_set_a_cap(self):
        """Same reason as the seal: any cap becomes "this time is special".

        It makes the number visible instead.
        """

        contract = CONTRACT.read_text(encoding="utf-8")
        assert "不設上限" in contract

    def test_trial_numbers_are_one_based_and_consecutive(self):
        """A ledger that started at 0 would read as though nothing was spent,
        the same reason seal openings are 1-based."""

        first = row()
        second = row(existing=[first], rerun_reason="r")
        assert (first["trial_number"], second["trial_number"]) == (1, 2)
