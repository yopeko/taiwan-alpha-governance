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

GENERATION = "2026-08-25 six-year rebuild"
WINDOW = ("2019-01-01", "2026-08-03")

STAGING = SCRATCH / "tw-alpha-m3-staging-13"
CALENDAR = SCRATCH / "tw-alpha-m3-pit-12"
PRICES = SCRATCH / "tw-alpha-m3-pit-prices-12"
STATUS = SCRATCH / "tw-alpha-m3-pit-status-11"

WAREHOUSE_ROOTS = {
    "calendar and lifecycle": CALENDAR,
    "prices and corporate actions": PRICES,
    "market status and fundamentals": STATUS,
}

# Not rebuilt for the six-year window. M6 has not been re-run, so this dataset
# and the warehouse it was derived from are a matched pair; pointing its tests
# at the new prices table would compare 382 sessions against 1,840 and read
# the difference as a defect.
RESEARCH_DATASET = SCRATCH / "tw-alpha-m6-dataset-08"
RESEARCH_DATASET_GENERATION = "2026-08-20 382-session build, not yet rebuilt"
RESEARCH_DATASET_PRICES = SCRATCH / "tw-alpha-m3-pit-prices-09"

# The candidate report the ADR-0002 contract tests read. Named here for the
# same reason as everything else in this file: five test files once each
# pinned their own scratch path and went on checking the previous generation.
CANDIDATE_REPORT = SCRATCH / "tw-alpha-m6-report-01"
