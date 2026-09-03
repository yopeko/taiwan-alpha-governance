"""The distribution report has to decompose the rule, not guess at it.

`measure_tradability` splits `unknown` into the inputs that caused it. That
split is only meaningful while it matches `asof.py`: a third path to `unknown`
added there would be counted in the total and in none of the causes, and the
report would still print a tidy breakdown that no longer adds up.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))

ASOF = (REPO / "scripts" / "m3" / "asof.py").read_text(encoding="utf-8")
SOURCE = (REPO / "scripts" / "m3" / "measure_tradability.py").read_text(
    encoding="utf-8"
)


def test_the_five_states_are_the_ones_asof_can_produce():
    """A state the report does not name would be counted nowhere."""

    import measure_tradability as m

    produced = {
        line.split('tradability = "')[1].split('"')[0]
        for line in ASOF.splitlines()
        if 'tradability = "' in line
    }
    assert produced == set(m.STATES), produced.symmetric_difference(set(m.STATES))


def test_unknown_still_has_exactly_two_causes_in_asof():
    """The decomposition is two-way because the rule is.

    Membership that could not be established, or a status/action window that
    does not cover the session. If this count moves, `why_unknown` is short by
    however many rows the new path produces.
    """

    branches = [
        line for line in ASOF.splitlines() if 'tradability = "unknown"' in line
    ]
    assert len(branches) == 2, branches
    assert 'elif membership == "unknown":' in ASOF
    assert (
        'elif status_state == "no-coverage" or action_state == "no-coverage":'
        in ASOF
    )


def test_the_report_reads_both_causes():
    import measure_tradability as m

    assert m.UNKNOWN_CAUSES["membership"] == "membership_state"
    assert m.UNKNOWN_CAUSES["coverage"] == (
        "market_status_state",
        "corporate_action_state",
    )


def test_an_empty_day_is_refused_rather_than_reported_clean():
    """Asking for a session the build never reached must not answer 0% unknown.

    That is the same shape as the window defect this dataset was rebuilt for:
    a missing month read as a successful run.
    """

    import measure_tradability as m
    import pytest

    rows = [
        {
            "market": "TWSE",
            "session_date": "2026-09-01",
            "symbol": "2330",
            "membership_state": "listed",
            "session_state": "official-open",
            "market_status_state": "no-event-in-covered-window",
            "corporate_action_state": "no-action-in-covered-window",
            "price_state": "complete",
            "tradability_state": "eligible",
            "reason_codes": "",
        }
    ]
    with pytest.raises(SystemExit):
        m.per_session(rows, "2026-09-02")


def test_a_state_the_script_does_not_know_is_reported_not_dropped():
    import measure_tradability as m

    rows = [
        {"market": "TWSE", "session_date": "d", "tradability_state": s}
        for s in ("eligible", "something-new")
    ]
    out = m.distribution(rows)
    assert out["states_not_in_this_script"] == ["something-new"]
    assert out["rows"] == 2
