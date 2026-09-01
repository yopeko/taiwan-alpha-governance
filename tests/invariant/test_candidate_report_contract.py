"""ADR-0002 decisions 3 and 4, checkable at last.

These two were owed from the day the ADR was accepted and could not be
written: they describe a candidate report, and no candidate report existed.
The contract was drafted on 2026-08-25 and the producer landed on 2026-08-26,
so the debt closes here.

Decision 3: every report carries both scales and the cost gap between them.
Decision 4, as amended 2026-08-26: the verdict is whether selection followed a
declared ranking, not how many candidates were turned away.

The rules are checked against a real report rather than a fixture. A contract
test that invents its own input proves the test can construct a passing case,
which is not the question being asked.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

from conftest import TAIWAN_CORE, require_local_environment  # noqa: E402
from warehouse import CANDIDATE_REPORT  # noqa: E402

# Every test in this module reads the operator's warehouse or archives, so all
# of them skip on a machine without them -- and on a machine with them, they
# are where the suite's 25 minutes go. The marker was declared in
# tests/conftest.py on 2026-08-17 and nothing used it until 2026-09-01.
#
# `pytest -m "not needs_local_data"` is the lane the pre-commit hook runs. A
# hook slow enough to be bypassed is a hook that gets bypassed, and the value
# of these checks is zero on the commits where someone passes --no-verify.
pytestmark = pytest.mark.needs_local_data

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
    "ranking_function",
    "rank_violations_scarcity",
    "rank_violations_sizing",
    "rank_violation_codes_json",
    "selection_logic_measured",
    "refusals_json",
}

# Contract v1.2.0 section 3. Two lists, because they answer different
# questions: scarcity decides the verdict, sizing is reported only. Repeated
# here so a silent edit to one shows up as a disagreement rather than as
# agreement by construction.
SCARCITY_REFUSALS = {
    "entry:position-slots-full",
    "entry:max-positions-reached",
    "entry:cash-reserve-floor-reached",
}

SIZING_REFUSALS = {
    "entry:cash-cannot-cover-position-and-charged-commission",
    "entry:breaches-hard-risk-cap",
    "entry:breaches-total-open-risk-cap",
    "entry:no-quantity-satisfies-every-cap",
    "entry:round-trip-cost-exceeds-planned-risk",
}

CAPACITY_REFUSALS = SCARCITY_REFUSALS | SIZING_REFUSALS

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


class TestSelectionLogicIsJudgedOnRankNotOnCounts:
    """ADR-0002 decision 4, as amended 2026-08-26.

    The rule used to be a count, and counting was wrong twice. Watching only
    `position-slots-full` reported success when raising the slot cap merely
    moved refusals into other codes; watching the total fixed that and still
    failed every broad-signal candidate on arithmetic that says nothing about
    whether its ranking was followed.
    """

    def test_the_verdict_requires_a_declared_ranking(self, report):
        for row in report:
            if not row["ranking_function"]:
                assert row["selection_logic_measured"] is False, (
                    f"{row['scale']}: no ranking function is declared, so what "
                    "the run measured was arrival order, whatever the counts say"
                )

    def test_the_verdict_requires_rank_consistent_fills(self, report):
        for row in report:
            if row["ranking_function"]:
                expected = row["rank_violations_scarcity"] == 0
                assert row["selection_logic_measured"] is expected

    def test_the_sizing_count_does_not_touch_the_verdict(self, report):
        """Contract v1.2.0 section 3.

        Pooled with scarcity until 2026-08-26, where it outvoted it and took
        the verdict along: 53 and 123 violations for the 12-1 momentum
        candidate, of which scarcity was 0 and sizing was all of them. The
        account failing to fit the top-ranked name is a property of its size,
        which is ADR-0002's subject, not a defect in the selection logic.
        """

        for row in report:
            if row["ranking_function"] and row["rank_violations_sizing"] > 0:
                assert row["selection_logic_measured"] is (
                    row["rank_violations_scarcity"] == 0
                ), (
                    f"{row['scale']}: the verdict moved with the sizing count, "
                    "which section 3 excludes from it"
                )

    def test_a_violation_count_says_which_code_caused_it(self, report):
        """A bare count cannot be acted on.

        The codes do not mean the same thing: `position-slots-full` is the
        ranking being ignored under scarcity, while a cost or quantity cap is
        the top-ranked name failing to fit. Only the first is the defect
        decision 4 is looking for.
        """

        for row in report:
            codes = json.loads(row["rank_violation_codes_json"])
            if not row["ranking_function"]:
                assert codes == {}, "no ranking, so nothing can have violated it"
                continue
            expected = row["rank_violations_scarcity"] + row["rank_violations_sizing"]
            assert sum(codes.values()) == expected, (
                f"{row['scale']}: the itemised violations do not sum to the "
                "two reported counts, so one of them is not being maintained"
            )
            unknown = set(codes) - CAPACITY_REFUSALS
            assert not unknown, (
                f"{row['scale']}: {sorted(unknown)} caused a rank violation "
                "without being a capacity refusal, which the check cannot do"
            )

    def test_violations_are_marked_not_applicable_without_a_ranking(self, report):
        """-1, never 0. Zero would read as "checked, and none found"."""

        for row in report:
            if not row["ranking_function"]:
                assert row["rank_violations_scarcity"] == -1
                assert row["rank_violations_sizing"] == -1

    def test_the_amended_path_is_actually_exercised(self, report):
        """Some row has to declare a ranking, or nothing here is being tested.

        The amendment moved the verdict from counting refusals to checking
        rank consistency, and the rank-consistency branch only runs when a
        ranking is declared. A canonical report with no ranking satisfies
        every rule in this class by taking the short way out of each one.

        This was written on 2026-08-26 to replace a test that compared the new
        verdict against the old `total <= trades * 10` rule. That comparison
        passed whenever both rules said False, which for a broad-signal
        candidate is always, so it asserted nothing.
        """

        assert any(row["ranking_function"] for row in report), (
            "no row in the canonical report declares a ranking function, so "
            "decision 4's amended path is unexercised. Build the report from a "
            "ranked candidate: `run_ledger_backtest.py --ranking ...`"
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


class TestTheCapacityListMatchesTheContract:
    """The enumeration decides what rank consistency is checked against."""

    def test_the_contract_lists_every_code_this_test_knows(self):
        contract = (
            REPO / "docs" / "contracts" / "candidate-report-contract.md"
        ).read_text(encoding="utf-8")
        missing = [code for code in CAPACITY_REFUSALS if code not in contract]
        assert not missing, (
            f"the contract no longer lists {sorted(missing)}; the two copies "
            "have to move together or the check silently narrows"
        )

    def test_the_producer_declares_the_version_the_contract_carries(self):
        """The manifest's `contract_version` is the report's own claim.

        Found stale on 2026-08-26: the producer still said v1.0.0 while the
        document had moved to v1.1.0 and the report already carried v1.1.0
        fields. Nothing was watching the pair, so a reader checking whether a
        report met a given version would have been told the wrong one.
        """

        contract = (
            REPO / "docs" / "contracts" / "candidate-report-contract.md"
        ).read_text(encoding="utf-8")
        declared = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
            encoding="utf-8"
        )
        version = re.search(
            r'CANDIDATE_REPORT_CONTRACT = "(candidate-report-v[\d.]+)"', declared
        )
        assert version, "the producer no longer declares a contract version"
        assert version.group(1) in contract, (
            f"the producer declares {version.group(1)}, which the contract "
            "document does not mention"
        )

    def test_a_security_specific_refusal_is_not_treated_as_capacity(self):
        """These say the security could not be traded, not that we were full."""

        for code in (
            "entry:not-tradable-restricted",
            "entry:no-opening-price",
            "entry:opened-below-stop",
        ):
            assert code not in CAPACITY_REFUSALS

    def test_holding_the_name_already_is_not_a_capacity_refusal(self):
        """It is the ranking being obeyed, not overruled.

        Until 2026-08-26 this was filed under `position-slots-full`, so a
        high-scoring name we already owned re-signalled, got refused, and was
        read as a better candidate turned away in favour of a worse one. The
        account's own best position was manufacturing rank violations: 70 and
        375 fell to 53 and 123 once the code was split out.
        """

        assert "entry:already-held" not in CAPACITY_REFUSALS
