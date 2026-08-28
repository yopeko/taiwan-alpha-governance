"""The sealed split, and the two ways it could quietly stop protecting anything.

Nested validation contract sections 1 and 2. The seal exists so that one
segment of the data never participates in choosing a candidate, and the
protection is mechanical rather than procedural: the development file does not
contain the sealed rows, so no amount of intent produces results for them.

Two failure modes are worth a test each.

The boundary could move. It is a calendar year rather than a percentage
precisely because a percentage can be re-argued once the results are in, and a
test that reads the constant from the code would move with it. This one pins
the date and names the contract that fixed it.

The split could lose or duplicate rows. A row in neither half is a security
that silently stopped existing; a row in both is a session that is
simultaneously sealed and not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m7"))

from split_sealed_dataset import SEAL_FROM, SPLIT_VERSION  # noqa: E402

CONTRACT = REPO / "docs" / "contracts" / "nested-validation-contract.md"


class TestTheBoundaryIsWhereTheContractPutIt:
    def test_the_seal_starts_on_the_calendar_year(self):
        """Not 20%, 25% or 30%.

        Each of those can be argued for, and anything that can be argued for
        can be argued again after the results are in. A year boundary cannot
        be re-derived as 24% because the number was disappointing.
        """

        assert SEAL_FROM == "2025-01-01"

    def test_the_contract_names_the_same_boundary(self):
        contract = CONTRACT.read_text(encoding="utf-8")
        assert "2025-01-01" in contract
        assert SPLIT_VERSION.startswith("sealed-split-2025-01-01/")

    def test_the_split_version_carries_the_boundary_in_its_name(self):
        """Moving the boundary must change the version string.

        Two artifacts produced under different boundaries and stamped with the
        same version cannot be told apart afterwards.
        """

        assert "2025-01-01" in SPLIT_VERSION


class TestPriceHistoryIsNotSealedOnlyOutcomesAre:
    def test_the_contract_says_warmup_may_cross_the_boundary(self):
        """Sealing the prices too would cost 252 of the 382 sealed sessions.

        A 252-session momentum score for 2025-01-02 reads 2024 prices, which
        were known on the day. Refusing them is not caution, it is throwing
        away two thirds of the evidence the seal exists to provide.
        """

        contract = CONTRACT.read_text(encoding="utf-8")
        assert "熱身" in contract
        assert "252" in contract

    def test_the_driver_can_warm_up_before_it_may_trade(self):
        """The mechanism that makes the above possible."""

        sys.path.insert(0, str(REPO / "scripts" / "m6"))
        import inspect

        from run_ledger_backtest import run

        assert "first_trading_session" in inspect.signature(run).parameters


@pytest.fixture(scope="module")
def halves():
    pq = pytest.importorskip("pyarrow.parquet")
    pc = pytest.importorskip("pyarrow.compute")
    sys.path.insert(0, str(REPO / "scripts" / "m3"))
    from current_build import RESEARCH_DATASET

    source = RESEARCH_DATASET / "research_dataset.parquet"
    if not source.is_file():
        pytest.skip("research dataset not present on this machine")
    table = pq.read_table(source, columns=["session_date"])
    sessions = table.column("session_date")
    return (
        table.filter(pc.less(sessions, SEAL_FROM)).num_rows,
        table.filter(pc.greater_equal(sessions, SEAL_FROM)).num_rows,
        table.num_rows,
    )


class TestTheSplitLosesNothingAndDuplicatesNothing:
    def test_every_row_lands_in_exactly_one_half(self, halves):
        development, sealed, total = halves
        assert development + sealed == total, (
            "the two halves do not sum to the source; a row in neither is a "
            "security that stopped existing, a row in both is a session that "
            "is sealed and not sealed at once"
        )

    def test_neither_half_is_empty(self, halves):
        """A split that seals everything or nothing is not a split."""

        development, sealed, _ = halves
        assert development > 0 and sealed > 0

    def test_the_sealed_half_is_the_minority(self, halves):
        """It is held back, not held out. Most of the data has to remain
        usable or there is nothing to develop a candidate on."""

        development, sealed, total = halves
        assert sealed / total < 0.5
        assert sealed / total > 0.1, (
            "a seal smaller than a tenth of the window cannot carry enough "
            "trades to say anything"
        )


class TestTheContractStatesItsOwnLimits:
    def test_it_admits_this_is_a_holdout_not_a_nested_cv(self):
        """The name says nested; the thing is one outer fold.

        Written down so a reader does not take the word for k folds.
        """

        contract = CONTRACT.read_text(encoding="utf-8")
        assert "留出法" in contract

    def test_it_admits_the_seal_is_consumable(self):
        """Every opening spends it, and it does not regenerate."""

        contract = CONTRACT.read_text(encoding="utf-8")
        assert "會用完" in contract

    def test_it_requires_the_opening_count_to_be_printed(self):
        """No cap, because any cap becomes "this time is special".

        A visible count works differently: the twelfth opening's report says
        twelve, and the reader discounts it themselves.
        """

        contract = CONTRACT.read_text(encoding="utf-8")
        assert "seal_opening_number" in contract

    def test_it_requires_the_candidate_commit_to_predate_the_evaluation(self):
        """The only mechanical evidence of a prior.

        M6.3 could not provide it -- the probe ran before the commit and the
        claim rests on a self-report. Here it is a required field.
        """

        contract = CONTRACT.read_text(encoding="utf-8")
        assert "candidate_commit" in contract
