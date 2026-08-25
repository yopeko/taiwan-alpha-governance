"""Which build of the point-in-time warehouse the invariant tests read.

Five test files each carried their own hardcoded scratch path, pinned to
whichever build existed the day it was written. The six-year rebuild landed in
new roots and every one of them went on reading the 2025-2026 generation: the
suite reported 422 passed without looking at a single new table, and the count
did not move, which is exactly what made it look fine.

A passing test is more persuasive than a stale document, so a test aimed at
the wrong data is worse than no test.

The second failure is quieter. These are scratch paths. `pytest.skip` on a
missing file meant a cleaned `C:\\tmp` would turn the whole M3 invariant suite
into skips, and in the summary line a run of all skips reads the same as a run
of all passes. `test_warehouse_generation.py` exists to make that impossible:
on a machine that has Taiwan Core, an absent warehouse is a failure, never a
skip. On a machine without it -- CI -- everything still skips with a reason,
which is what `--strict-env` is for.

This is the same lesson `test_capture_politeness` already recorded for itself
("a reader that breaks makes every case skip, and all-skip looks like
all-pass") applied to the output it was never applied to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import TAIWAN_CORE, require_local_environment

SCRATCH = Path(r"C:\tmp")

# The generation these tests describe. Moving the warehouse means changing
# these four lines and nothing else, and the golden counts that depend on the
# window live beside it rather than scattered through the files.
GENERATION = "2026-08-25 six-year rebuild"
WINDOW = ("2019-01-01", "2026-08-03")

CALENDAR = SCRATCH / "tw-alpha-m3-pit-12"
PRICES = SCRATCH / "tw-alpha-m3-pit-prices-11"
STATUS = SCRATCH / "tw-alpha-m3-pit-status-11"

# Not rebuilt for the six-year window. M6 has not been re-run, so this is
# still the 382-session dataset and its tests describe that generation. Named
# here rather than left hardcoded so the discrepancy is visible in one place
# instead of being discovered the next time someone trusts a green suite.
RESEARCH_DATASET = SCRATCH / "tw-alpha-m6-dataset-08"
RESEARCH_DATASET_GENERATION = "2026-08-20 382-session build, not yet rebuilt"
# The warehouse that dataset was built from. It must stay paired with it: the
# M6 tests cross-check the dataset against the prices it was derived from, and
# pointing them at the six-year table would compare 382 sessions against 1,840
# and call the difference a defect.
RESEARCH_DATASET_PRICES = SCRATCH / "tw-alpha-m3-pit-prices-09"

WAREHOUSE_ROOTS = {
    "calendar and lifecycle": CALENDAR,
    "prices and corporate actions": PRICES,
    "market status and fundamentals": STATUS,
}


def missing_roots() -> list[str]:
    return [name for name, root in WAREHOUSE_ROOTS.items() if not root.is_dir()]


def _require(request, path: Path, what: str) -> None:
    """Absent local environment skips; absent warehouse on a live box fails."""

    if not TAIWAN_CORE.is_dir():
        require_local_environment(request, what)
    if not path.exists():
        pytest.fail(
            f"{what}: {path} is missing. This machine has Taiwan Core, so the "
            f"warehouse should be built. Either rebuild it or update "
            f"tests/warehouse.py -- do not let it skip."
        )


def load_table(request, root: Path, name: str) -> Any:
    _require(request, root / name, name)
    pq = pytest.importorskip("pyarrow.parquet")
    return pq.read_table(root / name)


def load_rows(request, root: Path, name: str) -> list[dict[str, str]]:
    import csv

    _require(request, root / name, name)
    with (root / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
