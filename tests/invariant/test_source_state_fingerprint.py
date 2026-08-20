"""The recorded source-state fingerprint must describe the code that exists.

Every capture stamps its output with the Taiwan Core state it ran against.
That stamp is only worth anything if it is true, and it stops being true the
moment someone edits Taiwan Core without updating the constant here.

Before M4 was upstreamed the value was copied into eight scripts. Nothing
would have caught them going out of step with each other, let alone with the
code they claim to describe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))
CORE = Path(r"C:\project\tw-sepa-screener")


@pytest.fixture(scope="module")
def source_state():
    return pytest.importorskip("source_state")


def test_the_fingerprint_is_written_down_once(source_state):
    """Eight copies of a value that must move together is a drift waiting."""

    literal = source_state.SOURCE_STATE_FINGERPRINT
    offenders = []
    for path in sorted((REPO / "scripts").rglob("*.py")):
        if path.name in {"source_state.py", "final_m2_audit.py"}:
            # One holds the history; the other is the frozen M2 release audit,
            # which must keep quoting the state M2 was released under.
            continue
        if literal in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(REPO).as_posix())
    assert not offenders, (
        f"these scripts hard-code the fingerprint instead of importing it: {offenders}"
    )


def test_the_recorded_fingerprint_matches_the_actual_checkout(source_state):
    if not CORE.is_dir():
        pytest.skip("Taiwan Core checkout not present on this machine")
    actual = source_state.current_fingerprint()
    assert actual == source_state.SOURCE_STATE_FINGERPRINT, (
        "Taiwan Core has changed since the fingerprint was recorded. Every "
        "capture run from now on would stamp a state that no longer exists. "
        f"Recompute and record it: actual={actual}"
    )


def test_the_history_keeps_every_state_a_capture_could_have_recorded(source_state):
    """A stamp is unreadable if its value cannot be resolved back to a state."""

    history = dict(source_state.SOURCE_STATE_HISTORY)
    assert source_state.SOURCE_STATE_FINGERPRINT in history
    assert (
        "d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9" in history
    ), "the state every archive up to 2026-08-19 recorded must stay resolvable"


def test_the_current_value_is_the_last_entry(source_state):
    latest, _ = source_state.SOURCE_STATE_HISTORY[-1]
    assert latest == source_state.SOURCE_STATE_FINGERPRINT


def test_producer_metadata_uses_the_recorded_state(source_state):
    produced = source_state.producer()
    assert produced["dirty_fingerprint"] == source_state.SOURCE_STATE_FINGERPRINT
    assert produced["commit"] == source_state.PRODUCER_COMMIT
    # Overridable, so reproducing an older run can stamp what it really ran on.
    older = source_state.producer(fingerprint="d4ef6c0f")
    assert older["dirty_fingerprint"] == "d4ef6c0f"
