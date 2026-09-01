"""A backfill is only as long as its shortest lane.

The six-year rebuild extended five families to 2019 and left the sixth where
it was. The TEJ dividend-announcement lane held 5,010 rows covering 2025-01-02
to 2026-08-18, so 55% of every pre-2025 corporate action had no announcement
date and fell to `first-observed-only` -- present in the table, correct, and
unusable point in time.

Nothing caught it. The coverage ledger scores `corporate_action` on whether
the action was *captured*, not on whether it can be made *knowable*, so it
reported 3,680 supported market-dates while more than half the actions in six
of those eight years could never inform a decision.

D15 closed it on 2026-08-25: two exports covering 2019-01-16 to 2024-12-31
were imported, and `first-observed-only` fell from 5,292 to 530.

## What this test asserts, and what it learned not to

The first version compared the lane's earliest ex-date against the window's
first day and demanded the lane start no later. That was wrong in a way worth
recording: after the backfill landed, the lane's earliest row was 2019-01-16,
because no security went ex-dividend in the first two weeks of January 2019.
The lane covered the window completely and the assertion still failed.

An event lane's earliest *event* is not its coverage *start*. So the check is
per-year presence: every year the prices cover must have vendor rows. That is
the property the gap actually violated -- six years with none at all -- and it
does not depend on when the first event happened to fall.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

from conftest import ARCHIVE_ROOT, require_local_environment  # noqa: E402
from warehouse import WINDOW  # noqa: E402

# Every test in this module reads the operator's warehouse or archives, so all
# of them skip on a machine without them -- and on a machine with them, they
# are where the suite's 25 minutes go. The marker was declared in
# tests/conftest.py on 2026-08-17 and nothing used it until 2026-09-01.
#
# `pytest -m "not needs_local_data"` is the lane the pre-commit hook runs. A
# hook slow enough to be bypassed is a hook that gets bypassed, and the value
# of these checks is zero on the commits where someone passes --no-verify.
pytestmark = pytest.mark.needs_local_data

DIVIDEND_LANE = ARCHIVE_ROOT / "m3_tej_dividends_2026-08-19"


def lane_years(request) -> set[str]:
    """Every calendar year the vendor announcement lane carries rows for."""

    if not ARCHIVE_ROOT.is_dir():
        require_local_environment(request, "vendor lane parity")
    if not DIVIDEND_LANE.is_dir():
        pytest.fail(f"{DIVIDEND_LANE} is missing; announcement dates come from it")
    pq = pytest.importorskip("pyarrow.parquet")
    years: set[str] = set()
    for rows in DIVIDEND_LANE.rglob("rows.parquet"):
        table = pq.read_table(rows)
        if "ex_date" not in table.schema.names:
            continue
        years.update(str(v)[:4] for v in table.column("ex_date").to_pylist() if v)
    if not years:
        pytest.fail("the dividend lane carries no ex-dates at all")
    return years


def window_years() -> list[str]:
    return [str(y) for y in range(int(WINDOW[0][:4]), int(WINDOW[1][:4]) + 1)]


class TestTheAnnouncementLaneCoversThePriceWindow:
    def test_the_lane_is_not_empty(self, request):
        """Guards the guard: an empty lane would satisfy any subset check."""

        assert lane_years(request)

    def test_there_are_window_years_to_check(self):
        assert len(window_years()) > 1, "a single-year window would prove little"

    def test_every_year_the_prices_cover_has_vendor_rows(self, request):
        present = lane_years(request)
        missing = [year for year in window_years() if year not in present]
        assert not missing, (
            f"the vendor announcement lane carries nothing for {missing} while "
            f"prices cover {WINDOW[0]} to {WINDOW[1]}. Corporate actions in "
            "those years fall to `first-observed-only`: kept and correct, but "
            "never knowable at the time, so they cannot inform a backtest "
            "decision. Export the missing years from TEJ and import them with "
            "`tej_import.py --module dividend-announcement`."
        )
