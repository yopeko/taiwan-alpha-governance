"""Capture scripts must default to a polite request interval.

On 2026-08-22 a six-year price backfill ran at the 0.7s default that had been
written for a much smaller capture. About 4,900 requests in ninety minutes got
this IP blocked from **the whole of www.twse.com.tw** -- not the endpoint being
hammered, the entire host, prices included -- and the block outlasted a day.
openapi.twse.com.tw and every TPEx host were unaffected, which is how the
block was identified as host-level rather than endpoint-level.

The defaults were not wrong when they were written. They were never
re-examined when the same scripts were pointed at six years instead of one,
which is the failure worth guarding: an assumption that holds at small volume
and is never restated when the volume changes.

A floor rather than an exact value, so a future capture may be slower but not
quietly faster. Owner instruction, 2026-08-23: six seconds or more.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CAPTURES = sorted((REPO / "scripts" / "m3").glob("capture_*.py"))
FLOOR = 6.0


def interval_default(path: Path) -> float | None:
    """The `--interval` default this script declares, read from its AST.

    Parsed rather than pattern-matched so a value written as an expression,
    or moved to a constant, cannot slip past by not looking like the string
    this test expects.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None)
        if name != "add_argument":
            continue
        flags = [a.value for a in node.args if isinstance(a, ast.Constant)]
        if "--interval" not in flags:
            continue
        for keyword in node.keywords:
            if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                return float(keyword.value.value)
    return None


def test_there_are_capture_scripts_to_check():
    """A glob that matches nothing would make every test below vacuous."""

    assert CAPTURES, "no capture scripts found; the guard would pass on nothing"


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_capture_waits_at_least_six_seconds_between_requests(path):
    default = interval_default(path)
    if default is None:
        pytest.skip(f"{path.name} takes no --interval")
    assert default >= FLOOR, (
        f"{path.name} defaults to {default}s between requests. Anything under "
        f"{FLOOR}s is what got this IP blocked from www.twse.com.tw for over a "
        "day; if a faster run is genuinely needed, pass --interval explicitly "
        "rather than lowering the default for everyone."
    )


def test_at_least_one_script_actually_declares_an_interval():
    """Guards the guard: if the AST reader broke, every case would skip."""

    declared = [p for p in CAPTURES if interval_default(p) is not None]
    assert len(declared) >= 5, (
        f"only {len(declared)} capture scripts declare --interval; the reader "
        "is probably not finding them any more"
    )
