"""The producer's refusals, and the ledger that makes openings countable.

None of these run a backtest. They check the guards, because the guards are
the part that has to work the first time -- by the time an opening has been
spent, a guard that did not fire has already cost what it was meant to save.

The producer is deliberately not exercised end to end here. Doing so would
open the seal, and a test suite that spends the sealed segment on every green
run would exhaust it faster than any research programme could.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m7"))

import run_nested_validation as producer  # noqa: E402

CONTRACT = REPO / "docs" / "contracts" / "nested-validation-contract.md"
LEDGER = producer.LEDGER_NAME


class TestItWillNotOpenTheSealByAccident:
    def test_the_flag_is_required(self):
        """A speed bump, not a security measure.

        It exists so that opening the seal is never something that happened
        while you were doing something else.
        """

        with pytest.raises(SystemExit) as caught:
            producer.main(
                [
                    "--development",
                    "nowhere",
                    "--full",
                    "nowhere",
                    "--out",
                    "nowhere",
                    "--ranking",
                    "momentum-12-1",
                ]
            )
        assert "i-am-spending-a-seal-opening" in str(caught.value)

    def test_the_refusal_points_at_the_cheap_alternative(self):
        """Most of the time the caller wanted development figures anyway.

        A refusal that does not say what to do instead gets worked around,
        and the workaround is usually to pass the flag.
        """

        with pytest.raises(SystemExit) as caught:
            producer.main(
                [
                    "--development",
                    "nowhere",
                    "--full",
                    "nowhere",
                    "--out",
                    "nowhere",
                    "--ranking",
                    "",
                ]
            )
        message = str(caught.value)
        assert "run_ledger_backtest.py" in message
        assert "spends nothing" in message


class TestTheCommitIsTheEvidence:
    def test_a_dirty_tree_is_refused(self, tmp_path, monkeypatch):
        """`candidate_commit` proves the candidate predates the evaluation.

        It proves nothing if the code that ran was not the code in that
        commit. M6.3 had the weaker version of this gap: the probe ran before
        its commit, and the prior claim rests on a self-report.
        """

        monkeypatch.setattr(
            producer, "git", lambda *args: " M scripts/m6/run_ledger_backtest.py"
        )
        with pytest.raises(SystemExit) as caught:
            producer.candidate_provenance()
        assert "uncommitted" in str(caught.value)

    def test_a_clean_tree_yields_the_commit_and_its_time(self, monkeypatch):
        answers = {
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): "abc1234",
            ("log", "-1", "--format=%cI"): "2026-08-28T11:49:14+08:00",
        }
        monkeypatch.setattr(producer, "git", lambda *args: answers[args])
        provenance = producer.candidate_provenance()
        assert provenance["candidate_commit"] == "abc1234"
        assert provenance["candidate_commit_at"].startswith("2026-08-28")

    def test_the_real_repository_is_a_git_checkout(self):
        """Guards the guard: if `git` stopped working the provenance check
        would raise for the wrong reason and read as a dirty tree."""

        out = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0 and out.stdout.strip() == "true"


class TestOpeningsAreCounted:
    def test_the_first_opening_is_one_not_zero(self, tmp_path):
        """The count is what a reader discounts by, so it is 1-based.

        A report saying "opening 0" reads as though nothing was spent.
        """

        assert producer.next_opening_number(tmp_path / LEDGER) == 1

    def test_each_recorded_opening_advances_the_count(self, tmp_path):
        ledger = tmp_path / LEDGER
        ledger.write_text(
            json.dumps({"seal_opening_number": 1}) + "\n"
            + json.dumps({"seal_opening_number": 2}) + "\n",
            encoding="utf-8",
        )
        assert producer.next_opening_number(ledger) == 3

    def test_blank_lines_do_not_inflate_the_count(self, tmp_path):
        ledger = tmp_path / LEDGER
        ledger.write_text(
            json.dumps({"seal_opening_number": 1}) + "\n\n\n", encoding="utf-8"
        )
        assert producer.next_opening_number(ledger) == 2



class TestTheProducerAgreesWithItsContract:
    def test_the_declared_version_is_in_the_document(self):
        """The fourth pair of this kind. The first three disagreed."""

        contract = CONTRACT.read_text(encoding="utf-8")
        assert producer.CONTRACT_VERSION in contract

    def test_it_seals_where_the_splitter_seals(self):
        """Two boundaries would put development and sealed rows in both."""

        from split_sealed_dataset import SEAL_FROM

        assert producer.SEAL_FROM == SEAL_FROM

    def test_it_reports_both_segments(self):
        """Contract section 5: sealed figures alone are unreadable.

        A candidate that was mediocre in both looks identical to one that
        collapsed, and only the second is a reason to reject it.
        """

        source = (REPO / "scripts" / "m7" / "run_nested_validation.py").read_text(
            encoding="utf-8"
        )
        assert '"development"' in source and '"sealed"' in source
        assert "degradation" in source

    def test_the_sealed_segment_is_evaluated_with_a_warmup(self):
        """Contract section 1: outcomes are sealed, price history is not.

        Reading the sealed file alone would leave a 252-session candidate
        with 130 usable sessions out of 382.
        """

        source = (REPO / "scripts" / "m7" / "run_nested_validation.py").read_text(
            encoding="utf-8"
        )
        assert "first_trading_session=first_session" in source
