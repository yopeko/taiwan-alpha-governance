"""Which build of the point-in-time warehouse is the current one.

One place, because there have now been three separate incidents of the same
shape and the third one was found by the fix for the second.

`tests/warehouse.py` fixed five test files that each hardcoded a scratch path
and therefore validated the previous generation. `validate_m3_7.py` was not a
test file, so it was not looked at, and it carried the identical defect: it
rebuilt from `tw-alpha-m3-staging-10` and reported `verdict: passed` for a
warehouse nobody had asked it about. 828,736 price rows against the six-year
table's 3,316,101.

The rule these paths exist to enforce: **no module outside this one may name
a warehouse directory**. `test_no_module_hardcodes_a_warehouse_path` checks
it, because the failure mode is silent and produces green.

Generations are additive. An old root is left on disk so an old report can be
re-read, which is exactly why a stale pointer keeps working and keeps lying.
"""

from __future__ import annotations

from pathlib import Path

SCRATCH = Path(r"C:\tmp")

GENERATION = "2026-09-04 transactions restored to daily_prices_pit"
WINDOW = ("2019-01-01", "2026-09-02")

STAGING = SCRATCH / "tw-alpha-m3-staging-14"
CALENDAR = SCRATCH / "tw-alpha-m3-pit-13"
PRICES = SCRATCH / "tw-alpha-m3-pit-prices-14"
STATUS = SCRATCH / "tw-alpha-m3-pit-status-12"

WAREHOUSE_ROOTS = {
    "calendar and lifecycle": CALENDAR,
    "prices and corporate actions": PRICES,
    "market status and fundamentals": STATUS,
}

# The six-year build, and the warehouse it came from. Its own manifest names
# that warehouse, so this pair is checked rather than asserted.
#
# Pointed at the 382-session dataset-08 until 2026-08-27, with a comment
# saying M6 had not been re-run. M6 was re-run on 2026-08-25 and every
# candidate report since has used dataset-09, so the invariant tests were
# validating a dataset nothing else touched -- the same shape this file was
# created to stop, one generation later.
RESEARCH_DATASET = SCRATCH / "tw-alpha-m6-dataset-10"
RESEARCH_DATASET_GENERATION = "2026-09-03 window extended, 1,862 sessions"
# Still 13, and deliberately. dataset-10 was built from it, so the pair has
# to move together or a test comparing them reads a generation gap as a
# defect. pit-prices-14 adds `transactions` and changes nothing else -- the
# other 22 columns are identical row by row -- so the frozen dataset loses
# nothing by staying where it is until something needs the new column.
RESEARCH_DATASET_PRICES = SCRATCH / "tw-alpha-m3-pit-prices-13"

# The sealed split derived from RESEARCH_DATASET. Named here for the reason
# everything else in this file is: it was passed as `--out-root` at call time
# and then referred to by name in five evidence documents, which is the same
# shape as the five test files that each pinned their own warehouse path.
#
# split-01 came from dataset-09 and stays on disk, because every candidate
# result so far was run on it. Moving the pointer without regenerating would
# have left the sealed half at 382 sessions while this file said 404.
SEALED_SPLIT = SCRATCH / "tw-alpha-m7-split-02"
SEALED_SPLIT_GENERATION = "2026-09-03 from dataset-10, 1,458 development / 404 sealed"

# The candidate report the ADR-0002 contract tests read. Named here for the
# same reason as everything else in this file: five test files once each
# pinned their own scratch path and went on checking the previous generation.
CANDIDATE_REPORT = SCRATCH / "tw-alpha-m6-report-01"
