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

# The three-institution net-buy lane. Built 2026-09-05 from its own capture
# archive, not from the price warehouse, so it carries its own generation.
INSTITUTIONAL = SCRATCH / "tw-alpha-m3-institutional-pit-01"
INSTITUTIONAL_GENERATION = "2026-09-05 two markets, 1,862 sessions, 24,623,814 rows"

# The six-year build, and the warehouse it came from. Its own manifest names
# that warehouse, so this pair is checked rather than asserted.
#
# Pointed at the 382-session dataset-08 until 2026-08-27, with a comment
# saying M6 had not been re-run. M6 was re-run on 2026-08-25 and every
# candidate report since has used dataset-09, so the invariant tests were
# validating a dataset nothing else touched -- the same shape this file was
# created to stop, one generation later.
RESEARCH_DATASET = SCRATCH / "tw-alpha-m6-dataset-11"
RESEARCH_DATASET_GENERATION = (
    "2026-09-05 dataset-10 plus four lagged institutional columns"
)
# Moved to 14 with dataset-11, which was built from it.
#
# The claim written here while it was pinned at 13 -- that pit-prices-14 adds
# `transactions` and changes nothing else -- was checked rather than carried
# forward: dataset-11 and dataset-10 were compared column by column over all
# 3,928,820 rows and **all 22 shared columns are identical row for row**. So
# every artefact built on dataset-10 stays valid and comparable; only its
# `dataset_sha256` names a different generation.
RESEARCH_DATASET_PRICES = SCRATCH / "tw-alpha-m3-pit-prices-14"

# The sealed split derived from RESEARCH_DATASET. Named here for the reason
# everything else in this file is: it was passed as `--out-root` at call time
# and then referred to by name in five evidence documents, which is the same
# shape as the five test files that each pinned their own warehouse path.
#
# split-01 came from dataset-09 and stays on disk, because every candidate
# result so far was run on it. Moving the pointer without regenerating would
# have left the sealed half at 382 sessions while this file said 404.
SEALED_SPLIT = SCRATCH / "tw-alpha-m7-split-03"
SEALED_SPLIT_GENERATION = "2026-09-05 from dataset-11, 1,458 development / 404 sealed"

# The candidate report the ADR-0002 contract tests read. Named here for the
# same reason as everything else in this file: five test files once each
# pinned their own scratch path and went on checking the previous generation.
CANDIDATE_REPORT = SCRATCH / "tw-alpha-m6-report-01"
