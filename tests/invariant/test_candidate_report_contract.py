"""ADR-0002 decisions 3 and 4, checkable at last.

These two were owed from the day the ADR was accepted and could not be
written: they describe a candidate report, and no candidate report existed.
The contract was drafted on 2026-08-25 and the producer landed on 2026-08-26,
so the debt closes here.

Decision 3: every report carries both scales and the cost gap between them.
Decision 4: a report whose refusals dwarf its trades says so, in the field a
reader would look at, and may not be used to rank candidates.

The rules are checked against a real report rather than a fixture. A contract
test that invents its own input proves the test can construct a passing case,
which is not the question being asked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

from conftest import TAIWAN_CORE, require_local_environment  # noqa: E402
from warehouse import CANDIDATE_REPORT  # noqa: E402

REQUIRED_COLUMNS = {
    "scale",
    "opening_cash",
    "return_pct",
    "drawdown_pct",
    "completed_trades",
    "cost_total",
    "cost_share_of_capital",
    "cost_share_of_turnover",
    "refusals_total",
    "selection_logic_measured",
    "refusals_json",
}

REQUIRED_SCALES = {"m0-execution", "reference-measurement"}


def _require(request) -> None:
    if not TAIWAN_CORE.is_dir():
        require_local_environment(request, "candidate report contract")
    if not CANDIDATE_REPORT.is_dir():
        pytest.fail(
            f"{CANDIDATE_REPORT} is missing. Build it with "
            "`run_ledger_backtest.py --report-root`; these rules cannot be "
            "checked against a report nobody produced."
        )


@pytest.fixture(scope="module")
def report(request):
    _require(request)
    pq = pytest.importorskip("pyarrow.parquet")
    path = CANDIDATE_REPORT / "candidate_report.parquet"
    if not path.is_file():
        pytest.fail(f"{path} is missing; the contract names it in section 1")
    return pq.read_table(path).to_pylist()


@pytest.fixture(scope="module")
def manifest(request):
    _require(request)
    path = CANDIDATE_REPORT / "report_manifest.json"
    if not path.is_file():
        pytest.fail(f"{path} is missing; the contract names it in section 1")
    return json.loads(path.read_bytes())


class TestBothScalesArePresent:
    """ADR-0002 decision 3."""

    def test_the_report_is_not_empty(self, report):
        """Guards the guard: no rows would satisfy every per-row rule below."""

        assert report, "the report has no rows"

    def test_every_required_scale_appears(self, report):
        scales = {row["scale"] for row in report}
        missing = REQUIRED_SCALES - scales
        assert not missing, (
            f"the report is missing {sorted(missing)}. A report carrying one "
            "scale is not a simpler report; decision 3 asks for the gap "
            "between them, and a gap needs two numbers."
        )

    def test_no_row_is_missing_a_required_column(self, report):
        for row in report:
            missing = REQUIRED_COLUMNS - set(row)
            assert not missing, f"{row.get('scale')} lacks {sorted(missing)}"
            for column in REQUIRED_COLUMNS:
                assert row[column] is not None, f"{row['scale']}.{column} is null"

    def test_the_cost_gap_between_the_scales_is_derivable(self, report):
        """The gap is the point, so both sides of it have to be readable."""

        by_scale = {row["scale"]: row for row in report}
        m0 = by_scale["m0-execution"]["cost_share_of_turnover"]
        reference = by_scale["reference-measurement"]["cost_share_of_turnover"]
        assert m0 > 0 and reference > 0
        assert m0 > reference, (
            "cost as a share of turnover is not higher at the execution scale, "
            "which would contradict the minimum commission binding there"
        )

    def test_the_reference_scale_is_larger_than_the_execution_scale(self, report):
        by_scale = {row["scale"]: row for row in report}
        assert (
            by_scale["reference-measurement"]["opening_cash"]
            > by_scale["m0-execution"]["opening_cash"]
        )


class TestScarcityIsReported:
    """ADR-0002 decision 4."""

    def test_the_verdict_matches_the_counts(self, report):
        for row in report:
            expected = row["refusals_total"] <= row["completed_trades"] * 10
            assert row["selection_logic_measured"] is expected, (
                f"{row['scale']}: {row['refusals_total']:,} refusals against "
                f"{row['completed_trades']} trades, but the report claims "
                f"selection_logic_measured={row['selection_logic_measured']}"
            )

    def test_the_refusal_table_is_complete_not_a_top_n(self, report):
        """Contract section 2.2. A truncated table hides the codes that moved.

        Raising the slot cap on 2026-08-25 moved 277,777 slots-full refusals
        into other codes while the total barely changed. A report listing only
        the largest few would have shown that as a fix.
        """

        for row in report:
            refusals = json.loads(row["refusals_json"])
            assert sum(refusals.values()) == row["refusals_total"], (
                f"{row['scale']}: the itemised refusals do not sum to the "
                "reported total, so the table is partial"
            )

    def test_the_total_is_counted_not_one_reason_code(self, report):
        """The rule must not be satisfiable by draining a single code."""

        for row in report:
            refusals = json.loads(row["refusals_json"])
            if len(refusals) < 2:
                continue
            largest = max(refusals.values())
            assert row["refusals_total"] > largest, (
                f"{row['scale']}: the reported total equals its largest single "
                "reason code, which is how a scarcity check gets fooled"
            )


class TestTheReportSaysWhatItWasBuiltFrom:
    """Contract section 2.3. A number with no lineage cannot be re-checked."""

    @pytest.mark.parametrize(
        "field",
        [
            "dataset_sha256",
            "warehouse_dataset_id",
            "strategy_version",
            "rules_version",
            "ledger_version",
            "broker_terms",
            "built_at",
            "contract_version",
        ],
    )
    def test_the_manifest_carries_its_lineage(self, manifest, field):
        assert manifest.get(field), f"report_manifest.json lacks {field}"

    def test_the_broker_terms_declare_their_evidence_state(self, manifest):
        """M0 section 4.2: an assumption must not read as a verified fact."""

        assert manifest["broker_terms"].get("evidence_state")

    def test_the_reading_note_carries_the_adr_s_restriction(self, manifest):
        """Decision 1 travels with the artifact, not only in a document."""

        note = manifest.get("reading_note", "")
        assert "decision 1" in note.lower()
        assert "rank" in note.lower()
