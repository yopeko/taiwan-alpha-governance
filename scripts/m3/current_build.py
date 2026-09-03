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

GENERATION = "2026-09-03 window extended to 2026-09-02"
WINDOW = ("2019-01-01", "2026-09-02")

STAGING = SCRATCH / "tw-alpha-m3-staging-14"
CALENDAR = SCRATCH / "tw-alpha-m3-pit-13"
PRICES = SCRATCH / "tw-alpha-m3-pit-prices-13"
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
RESEARCH_DATASET = SCRATCH / "tw-alpha-m6-dataset-09"
RESEARCH_DATASET_GENERATION = "2026-08-25 six-year build, 1,840 sessions"
RESEARCH_DATASET_PRICES = SCRATCH / "tw-alpha-m3-pit-prices-12"

# The candidate report the ADR-0002 contract tests read. Named here for the
# same reason as everything else in this file: five test files once each
# pinned their own scratch path and went on checking the previous generation.
CANDIDATE_REPORT = SCRATCH / "tw-alpha-m6-report-01"
