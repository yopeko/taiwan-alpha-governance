"""A backfill is only as long as its shortest lane.

The six-year rebuild extended five families to 2019 and left the sixth where
it was. The TEJ dividend-announcement lane still holds 5,010 rows covering
2025-01-02 to 2026-08-18, so 55% of every pre-2025 corporate action has no
announcement date and falls to `first-observed-only` -- present in the table,
correct, and unusable point in time.

Nothing caught it. The coverage ledger scores `corporate_action` on whether
the action was *captured*, not on whether it can be made *knowable*, so it
reported 3,680 supported market-dates while more than half the actions in six
of those eight years could never inform a decision.

The gap is not TEJ's. The vendor has the data; the lane was imported for the
old window and never re-exported for the new one. What was missing is a check
that the lanes agree about how far back they reach.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

from conftest import ARCHIVE_ROOT, require_local_environment  # noqa: E402
from warehouse import WINDOW  # noqa: E402

DIVIDEND_LANE = ARCHIVE_ROOT / "m3_tej_dividends_2026-08-19"


def lane_span(request) -> tuple[str, str]:
    """The ex-date range the vendor announcement lane actually carries."""

    if not ARCHIVE_ROOT.is_dir():
        require_local_environment(request, "vendor lane parity")
    if not DIVIDEND_LANE.is_dir():
        pytest.fail(f"{DIVIDEND_LANE} is missing; announcement dates come from it")
    pq = pytest.importorskip("pyarrow.parquet")
    dates: list[str] = []
    for rows in DIVIDEND_LANE.rglob("rows.parquet"):
        table = pq.read_table(rows)
        if "ex_date" not in table.schema.names:
            continue
        dates.extend(str(v) for v in table.column("ex_date").to_pylist() if v)
    if not dates:
        pytest.fail("the dividend lane carries no ex-dates at all")
    return min(dates), max(dates)


class TestTheAnnouncementLaneReachesAsFarBackAsThePrices:
    def test_the_lane_is_not_empty(self, request):
        """Guards the guard: an empty lane would satisfy any range check."""

        low, high = lane_span(request)
        assert low <= high

    @pytest.mark.xfail(
        reason=(
            "known gap, 2026-08-25: the dividend lane covers 2025-01-02 to "
            "2026-08-18 while prices reach 2019-01-01. Closing it needs a new "
            "TEJ PRO export for 2019-2024, which is a manual vendor download. "
            "Recorded as a failing test rather than a note so it cannot be "
            "forgotten, and so the day the export lands this turns green."
        ),
        strict=True,
    )
    def test_the_lane_starts_no_later_than_the_price_window(self, request):
        low, _ = lane_span(request)
        assert low <= WINDOW[0], (
            f"the vendor announcement lane starts {low} but prices start "
            f"{WINDOW[0]}. Every corporate action before {low} falls to "
            "`first-observed-only`: kept and correct, but never knowable at "
            "the time, so it cannot inform a backtest decision."
        )
