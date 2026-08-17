"""M0 §10 prohibitions, as tests that fail when violated.

Until now every prohibition in the M0 contract lived only in prose, enforced
by whoever happened to be reading it. These turn the checkable ones into
machine-enforced invariants.

Not every prohibition is testable yet — several depend on the as-of query
interface that M3.6 has not built. Those are marked xfail with the reason, so
the gap stays visible instead of looking like coverage.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")

PROTECTED_LITERALS = ("tw_sepa.duckdb", "stock_master.csv", r"data\raw")
WRITE_CALLS = {"write_text", "write_bytes", "copytree", "copy2", "rmtree", "unlink"}

sys.path.insert(0, str(SCRIPTS / "m3"))


def python_sources() -> list[Path]:
    return sorted(
        p for p in REPO.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts
    )


class TestProhibitionOverwriteProductionStores:
    """M0 §10: research scripts must not overwrite formal artefacts."""

    def test_no_write_call_targets_a_protected_store(self):
        offenders: list[str] = []
        for path in python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None)
                if name not in WRITE_CALLS:
                    continue
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    literal = arg.value if isinstance(arg, ast.Constant) else None
                    if isinstance(literal, str) and any(
                        marker in literal for marker in PROTECTED_LITERALS
                    ):
                        offenders.append(f"{path.relative_to(REPO)}:{node.lineno}")
        assert not offenders, f"write call targets a protected store: {offenders}"

    def test_publication_guard_rejects_every_protected_path(self):
        from build_staging import PROTECTED_PATHS, StagingError, assert_publishable

        for protected in PROTECTED_PATHS:
            with pytest.raises(StagingError):
                assert_publishable(protected)

    def test_publication_guard_rejects_a_parent_of_a_protected_path(self):
        from build_staging import StagingError, assert_publishable

        with pytest.raises(StagingError):
            assert_publishable(Path(r"C:\project\tw-sepa-screener\data"))


class TestProhibitionAiInTheDecisionPath:
    """M0 §10: AI analysis must not alter scores, positions or orders."""

    AI_MARKERS = ("openai", "anthropic", "llm", "chatgpt", "gpt-4", "deepseek")

    def test_no_model_call_in_any_pipeline_module(self):
        offenders: list[str] = []
        for path in python_sources():
            text = path.read_text(encoding="utf-8").lower()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or ""]
                    )
                    for name in names:
                        if any(m in name.lower() for m in self.AI_MARKERS):
                            offenders.append(f"{path.relative_to(REPO)}:{name}")
            del text
        assert not offenders, f"model client imported into the pipeline: {offenders}"


class TestProhibitionAlphaMasterWholesaleMerge:
    """M0 §10 / M1: the A-share PR must not be merged wholesale."""

    def test_no_alphamaster_module_is_vendored(self):
        markers = ("model_core", "alphamaster", "alpha_master")
        offenders = [
            str(p.relative_to(REPO))
            for p in python_sources()
            if any(m in p.read_text(encoding="utf-8").lower() for m in markers)
            and "test_m0_prohibitions" not in p.name
        ]
        assert not offenders, f"AlphaMaster code appears vendored: {offenders}"


class TestProhibitionLicensedVendorPassedOffAsOfficial:
    """G0 v2.0.0 D9 condition 1: TEJ evidence must keep its own state."""

    LANE = RAW / "m3_tej_licensed_2026-08-16"

    def test_every_tej_row_is_labelled_licensed_vendor(self):
        if not self.LANE.is_dir():
            pytest.skip("TEJ lane not present on this machine")
        import pyarrow.parquet as pq

        checked = 0
        for parquet in self.LANE.rglob("normalized/rows.parquet"):
            table = pq.read_table(parquet)
            assert "evidence_state" in table.column_names
            states = set(table["evidence_state"].to_pylist())
            assert states == {"licensed-vendor-snapshot"}, states
            checked += 1
        assert checked, "no TEJ normalized table found"

    def test_tej_import_manifests_never_claim_the_canonical_lane(self):
        if not self.LANE.is_dir():
            pytest.skip("TEJ lane not present on this machine")
        for manifest in self.LANE.rglob("import_manifest.json"):
            payload = json.loads(manifest.read_bytes())
            assert payload.get("canonical_lane") is False
            assert payload.get("evidence_state") == "licensed-vendor-snapshot"


class TestProhibitionSurvivorshipBias:
    """M0 §10: today's security list must not be used to backtest the past."""

    LANE = RAW / "m3_tej_licensed_2026-08-16"

    def test_lifecycle_lane_contains_delisted_securities(self):
        if not self.LANE.is_dir():
            pytest.skip("TEJ lane not present on this machine")
        import pyarrow.parquet as pq

        delisted = 0
        for manifest in self.LANE.rglob("import_manifest.json"):
            payload = json.loads(manifest.read_bytes())
            if payload.get("module") != "security-listing":
                continue
            table = pq.read_table(manifest.parent / "normalized" / "rows.parquet")
            if "delisting_date" not in table.column_names:
                continue
            delisted = sum(1 for v in table["delisting_date"].to_pylist() if v)
        assert delisted > 0, (
            "the lifecycle lane has no delisted securities, which means the "
            "universe is a current-only snapshot and would be survivorship-biased"
        )


class TestProhibitionSilentlyFilledGaps:
    """M0 §10: missing / suspended / delisted must not become tradable."""

    LEDGER = REPO / "docs" / "evidence" / "m3-coverage-summary-2026-08-16-v4.json"

    def test_coverage_ledger_has_no_silently_dropped_market_dates(self):
        if not self.LEDGER.is_file():
            pytest.skip("coverage summary not present")
        summary = json.loads(self.LEDGER.read_bytes())
        window = summary["window"]
        expected = window["calendar_dates"] * len(("TWSE", "TPEX"))
        assert summary["row_count"] == expected

    def test_strict_scoring_never_reports_supported_from_vendor_evidence(self):
        if not self.LEDGER.is_file():
            pytest.skip("coverage summary not present")
        summary = json.loads(self.LEDGER.read_bytes())
        assert summary["strict_counts"].get("supported", 0) == 0, (
            "strict scoring must count official evidence only; a non-zero "
            "supported count here means vendor evidence leaked into it"
        )


class TestProhibitionCostModelShortcuts:
    """M0 §10: minimum commission, sell tax and slippage must not be ignored."""

    def test_minimum_commission_is_applied_below_the_threshold(self):
        sys.path.insert(0, str(REPO))
        from decimal import Decimal

        from m4.rules import Side, trade_costs

        result = trade_costs(side=Side.BUY, price=Decimal("20"), quantity=100)
        assert result.minimum_commission_applied is True
        assert result.commission == Decimal("20")

    def test_sell_tax_is_never_charged_on_a_buy(self):
        sys.path.insert(0, str(REPO))
        from decimal import Decimal

        from m4.rules import Side, trade_costs

        assert trade_costs(side=Side.BUY, price=Decimal("50"), quantity=1000).tax == 0

    def test_broker_terms_carry_an_assumption_label(self):
        sys.path.insert(0, str(REPO))
        from m4.rules import BrokerTerms

        assert BrokerTerms().evidence_state == "assumption"


class TestProhibitionUndocumentedAdjustedPrices:
    """M0 §10: adjusted prices must not replace raw official prices."""

    def test_no_adjusted_price_artefact_exists_without_a_documented_method(self):
        # No adjustment layer has been built yet. This guards against one
        # appearing without the documented method M0 requires.
        offenders = [
            str(p.relative_to(RAW))
            for p in (RAW.glob("*adjusted*") if RAW.is_dir() else [])
        ]
        assert not offenders, (
            f"adjusted-price artefacts appeared without a documented method: {offenders}"
        )


@pytest.mark.xfail(
    reason="requires the M3.6 as-of query interface, which is not built yet",
    strict=True,
)
def test_no_future_information_leaks_into_an_earlier_cutoff():
    from m3_asof import reconstruct  # noqa: F401

    raise AssertionError("unreachable until M3.6 exists")


@pytest.mark.xfail(
    reason="requires the M5 cash ledger, which is not built yet", strict=True
)
def test_no_impossible_trade_can_settle():
    from m5_ledger import settle  # noqa: F401

    raise AssertionError("unreachable until M5 exists")
