"""A shared resource someone else writes must not decide our exit code.

Every capture and build fingerprints the protected production stores before
and after itself. That is worth doing: it detects a writer nobody expected.
What it must not do is fail the run, because the writer it usually detects is
the legacy daily pipeline updating its own stores on its own schedule.

The cost of getting this wrong was paid twice.

* 2026-08-25, the TPEx capture: the pipeline wrote at 15:40-16:03, the capture
  exited 1 after eleven and a half successful hours, a supervisor treated the
  non-zero code as a crash and relaunched, and the second run overwrote the
  manifest with the zeroes of a no-op resume. The lane's real totals survived
  only because the ledger beside it was append-only.

* 2026-08-26, `test_two_builds_agree`: red at 16:02 for the same reason, with
  nothing whatsoever wrong with the staging build it names.

What actually keeps these scripts out of production is structural and checked
before a byte is written: `assert_publishable` for builds and
`require_daily_price_output_root` for captures both refuse an output root
inside a protected path. The fingerprints are a detector, not the guarantee,
and a detector wired to an exit code reports someone else's activity as our
failure.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = sorted((REPO / "scripts" / "m3").glob("*.py"))


def _mentions_the_flag(node: ast.AST) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Constant) and inner.value == "production_unchanged":
            return True
        if isinstance(inner, ast.Name) and inner.id == "production_unchanged":
            return True
    return False


def returns_gated_on_the_flag(path: Path) -> list[int]:
    """Lines where the *choice* of return value depends on the flag.

    Only conditional positions count. Putting `production_unchanged` in a
    summary dict is the reporting this file asks for, and an earlier version
    of this check flagged `archive_96_session` and `verify_96_archive` for
    doing exactly that -- returning a dict that carries the key. Reporting is
    the remedy, not the defect.

    Read from the AST rather than matched as text, so moving the condition
    into a variable or reversing the ternary cannot slip past.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        conditions: list[ast.AST] = []
        for inner in ast.walk(node.value):
            if isinstance(inner, ast.IfExp):
                conditions.append(inner.test)
            elif isinstance(inner, (ast.BoolOp, ast.UnaryOp, ast.Compare)):
                conditions.append(inner)
        if any(_mentions_the_flag(c) for c in conditions):
            offenders.append(node.lineno)
    return offenders


def test_there_are_scripts_to_check():
    """Guards the guard: an empty glob would make the rule vacuous."""

    assert len(SCRIPTS) > 10, f"only {len(SCRIPTS)} scripts swept; this proves nothing"


def test_some_script_still_records_the_flag():
    """The detector must not be deleted in the course of un-wiring it.

    Removing the fingerprint check would also make this file pass, and that is
    the opposite of what it is asking for.
    """

    recorded = [
        p.name
        for p in SCRIPTS
        if "protected_before" in p.read_text(encoding="utf-8")
    ]
    assert recorded, (
        "no script fingerprints the protected stores any more; the check is "
        "meant to be reported, not removed"
    )


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_no_exit_code_depends_on_the_protected_store_flag(path: Path):
    offenders = returns_gated_on_the_flag(path)
    assert not offenders, (
        f"{path.relative_to(REPO)} returns a value derived from "
        f"`production_unchanged` at line(s) {offenders}. That flag moves when "
        "the legacy daily pipeline writes its own stores, which is not this "
        "script's failure. Report it -- `protected_changed` names what moved "
        "-- and let the exit code reflect the work."
    )
