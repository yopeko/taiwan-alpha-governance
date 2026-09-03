"""The backtest driver may not read a column it did not ask for.

`load_dataset` projects twelve of the dataset's twenty-three columns. That is
worth 5.4 GB on a 32 GB machine, and it introduces one failure mode: a column
read somewhere the projection list forgot arrives as `None`, which is
indistinguishable from a genuinely absent value. A missing `close` would read
as "no quotation that session" and the driver would skip the security in
silence.

So the list is checked against the driver's own source rather than maintained
by memory.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

SOURCE = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
    encoding="utf-8"
)

# The names the driver binds a dataset row to. `result`, `manifest` and the
# rest are its own output structures and are deliberately not here.
ROW_VARIABLES = ("row", "bar", "today", "b", "prior", "previous")

ACCESS = re.compile(
    r"\b(?:" + "|".join(ROW_VARIABLES) + r")\s*(?:\[\s*|\.get\(\s*)[\"']([a-z_]+)[\"']"
)


# The dataset's declared schema, read from the builder that writes it rather
# than from a parquet file, so this runs without the operator's warehouse.
SCHEMA_SOURCE = (REPO / "scripts" / "m6" / "build_research_dataset.py").read_text(
    encoding="utf-8"
)
FIELD = re.compile(r'pa\.field\(\s*"([a-z_]+)"')


def dataset_schema() -> set[str]:
    return set(FIELD.findall(SCHEMA_SOURCE))


def columns_read() -> set[str]:
    """Names the driver reads off a row **that are dataset columns**.

    The driver also indexes its own report structures with the same variable
    names, and those are not dataset columns. Intersecting with the schema is
    what separates the two, and it does it from the builder's own declaration
    rather than from a list someone would have to keep in step.
    """

    return set(ACCESS.findall(SOURCE)) & dataset_schema()


def test_every_column_the_driver_reads_is_projected():
    """The whole point. A forgotten column becomes a silent None."""

    import run_ledger_backtest as backtest

    missing = columns_read() - set(backtest.DATASET_COLUMNS)
    assert not missing, (
        f"read but not projected: {sorted(missing)}. Add them to "
        f"DATASET_COLUMNS -- an unprojected column arrives as None and is "
        f"indistinguishable from a value the warehouse genuinely lacks"
    )


def test_the_scan_actually_finds_something():
    """A regex that matched nothing would make the test above vacuous, and a
    vacuous test that passes is worse than no test."""

    found = columns_read()
    assert len(found) >= 8, found
    assert {"close", "high", "low", "session_date"} <= found


def test_every_projected_column_exists_in_the_dataset_schema():
    """A typo in the list would be a read-time error on the operator's machine
    and nothing at all on CI. Checked against the builder's declaration, so it
    fails in the fast lane instead."""

    import run_ledger_backtest as backtest

    unknown = set(backtest.DATASET_COLUMNS) - dataset_schema()
    assert not unknown, unknown


def test_the_schema_scan_found_the_real_schema():
    schema = dataset_schema()
    assert len(schema) >= 20, schema
    assert {"tradability_state", "limit_up", "previous_close"} <= schema


def test_the_projection_is_a_real_saving():
    """Twelve of twenty-three. If the list ever grows to cover everything the
    projection has stopped paying for itself and should be reconsidered rather
    than left as decoration."""

    import run_ledger_backtest as backtest

    assert len(backtest.DATASET_COLUMNS) <= 16
    assert "columns=list(DATASET_COLUMNS)" in SOURCE
