"""The index documents must not drift away from the evidence they index.

A stale index fails no other test: the code is right, the evidence is right,
and only the summary a reader sees first is wrong. For a project whose value
rests on being auditable, an index that lies is an audit that failed.

This was written after exactly that happened — several work packages were
complete and committed while the plan table still showed them pending.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
EVIDENCE = DOCS / "evidence"
PLAN = DOCS / "m3-point-in-time-warehouse-plan.md"
REGISTER = DOCS / "milestone-register.md"
README = REPO / "README.md"

# Data exports that accompany a narrative document rather than standing alone.
EVIDENCE_EXEMPT = {".csv", ".json", ".txt"}


def index_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (README, PLAN, REGISTER)
        if path.is_file()
    )


def test_every_evidence_document_is_referenced_by_an_index():
    """An unreferenced evidence file is one nobody will ever find."""

    text = index_text()
    orphans = [
        path.name
        for path in sorted(EVIDENCE.glob("*.md"))
        if path.name not in text
    ]
    assert not orphans, f"evidence not referenced from any index: {orphans}"


def test_every_contract_document_is_referenced_by_an_index():
    text = index_text()
    orphans = [
        path.name
        for path in sorted((DOCS / "contracts").glob("*.md"))
        if path.name not in text
    ]
    assert not orphans, f"contract not referenced from any index: {orphans}"


def test_every_completed_work_package_cites_evidence():
    """`complete` without a link is a claim, not a record."""

    if not PLAN.is_file():
        pytest.skip("plan not present")
    offenders: list[str] = []
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| M3."):
            continue
        if "`complete`" not in line:
            continue
        if "](" not in line:
            offenders.append(line.split("|")[1].strip())
    assert not offenders, f"work packages marked complete with no evidence link: {offenders}"


def test_no_index_link_points_at_a_missing_file():
    """A broken link in an index is silent rot."""

    broken: list[str] = []
    for source in (README, PLAN, REGISTER):
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        for match in re.finditer(r"\]\(([^)#]+\.(?:md|csv|json|py))\)", text):
            target = (source.parent / match.group(1)).resolve()
            if not target.is_file():
                broken.append(f"{source.name} -> {match.group(1)}")
    assert not broken, f"index links point at missing files: {broken}"


def test_plan_and_register_agree_on_which_milestone_is_active():
    """Two indexes disagreeing is how a reader ends up trusting the wrong one."""

    if not (PLAN.is_file() and REGISTER.is_file()):
        pytest.skip("indexes not present")
    register = REGISTER.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    # The register's M3 row and the plan header must not contradict each other
    # about whether the capture phase is still running.
    if "抓取階段全部結束" in register or "抓取階段結束" in register:
        assert "待啟動" not in plan, (
            "the register says capture finished while the plan still calls a "
            "work package pending start"
        )


def test_no_index_still_advertises_a_resolved_blocker():
    """Resolved blockers must be removed, not left for a reader to trip over."""

    resolved_phrases = (
        "無任何已批准來源",
        "需要券商費率決定",
        "M3.2 起為 `blocked`",
    )
    text = index_text()
    stale = [phrase for phrase in resolved_phrases if phrase in text]
    assert not stale, f"index still advertises a resolved blocker: {stale}"


def test_no_index_narrative_contradicts_a_completed_milestone():
    """A finished milestone must not still be described as unfinished.

    The status table and the narrative section are edited separately, so they
    drift apart exactly when a milestone lands. This caught README describing
    M3 conditions 4-5 as "not yet started" after they had both passed.
    """

    if not README.is_file():
        pytest.skip("README not present")
    text = README.read_text(encoding="utf-8")
    if "| M3 Point-in-time warehouse | complete" not in text:
        pytest.skip("M3 not marked complete")
    stale = [
        phrase
        for phrase in ("條件 4–5 尚未開始", "尚未開始", "倉庫未驗", "抓取階段結束")
        if phrase in text
    ]
    assert not stale, f"README still describes finished M3 work as pending: {stale}"
