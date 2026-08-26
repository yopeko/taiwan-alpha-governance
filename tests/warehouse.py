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

import sys
from pathlib import Path
from typing import Any

import pytest

from conftest import TAIWAN_CORE, require_local_environment

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "m3"))

# The single source lives with the build scripts, because the generation is a
# property of the build and `validate_m3_7.py` needs it too. That validator
# carried the identical stale-path defect these helpers were written to fix,
# and was missed because it is not a test file -- so the constants moved to
# where both can read them rather than being duplicated here.
from current_build import (  # noqa: E402,F401
    CALENDAR,
    CANDIDATE_REPORT,
    GENERATION,
    PRICES,
    RESEARCH_DATASET,
    RESEARCH_DATASET_GENERATION,
    RESEARCH_DATASET_PRICES,
    STAGING,
    STATUS,
    WAREHOUSE_ROOTS,
    WINDOW,
)


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
