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

# Any subscript by a dataset column name, whatever the expression in front of
# it. This exists because the variable-name list above was not enough: the
# driver had `rows[(s.market, s.symbol)]["tradability_state"]` in two places,
# which is a dataset row read through an expression rather than a bound name.
# Both a manual grep and the first version of this test missed them, and the
# run failed at the site instead -- loudly, but only after four minutes.
#
# Any subscript-by-column-name is either a dict where a `Bar` belongs, or an
# output structure that happens to share a column name with the dataset. The
# second is rare enough to name explicitly.
ANY_SUBSCRIPT = re.compile(r"""\[\s*["']([a-z_]+)["']\s*\]""")

# Output fields whose names collide with dataset columns. None today; kept so
# a future collision is declared here rather than silently widening the scan.
OUTPUT_FIELDS_SHARING_A_COLUMN_NAME: frozenset[str] = frozenset()

# Attribute access since 2026-09-04, when the row dicts became `Bar` objects
# with `__slots__`. The subscript and `.get()` forms stay in the pattern on
# purpose: a revert, or a new site written in the old style, must still be
# caught rather than quietly ignored.
ACCESS = re.compile(
    r"\b(?:" + "|".join(ROW_VARIABLES) + r")\s*"
    r"""(?:\[\s*["']([a-z_]+)["']|\.get\(\s*["']([a-z_]+)["']|\.([a-z_]+)\b)"""
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

    found = {name for match in ACCESS.findall(SOURCE) for name in match if name}
    return found & dataset_schema()


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


def test_no_dataset_column_is_read_by_subscript_anywhere():
    """The check the variable-name scan could not make.

    `rows[(s.market, s.symbol)]["tradability_state"]` is a dataset row reached
    through an expression, so no list of bound names would have found it. Two
    of those survived the conversion and the run raised
    `TypeError: 'Bar' object is not subscriptable` four minutes in.

    Loud is better than silent, but this is better than loud.
    """

    offenders = sorted(
        (set(ANY_SUBSCRIPT.findall(SOURCE)) & dataset_schema())
        - OUTPUT_FIELDS_SHARING_A_COLUMN_NAME
    )
    assert not offenders, (
        f"read by subscript: {offenders}. Dataset rows are `Bar` objects with "
        f"`__slots__` -- use attribute access, or add the name to "
        f"OUTPUT_FIELDS_SHARING_A_COLUMN_NAME if it is an output field that "
        f"happens to share a column name"
    )


def test_the_rows_are_slotted_objects_not_dicts():
    """Measured 2026-09-04 over 3,928,820 rows: 3.37 GB as dicts against
    0.59 GB as `Bar`. A twelve-key dict carries a hash table for attribute
    names the author already knows."""

    import run_ledger_backtest as backtest

    assert backtest.Bar.__slots__ == backtest.DATASET_COLUMNS
    assert not hasattr(backtest.Bar(tuple([None] * 12)), "__dict__")


def test_a_column_the_projection_forgot_raises_rather_than_reads_as_none():
    """The failure mode the projection introduced, closed by the slots.

    A dict answers `.get("volume")` with None for a column that was never
    read, and None is also what the warehouse returns for a value it
    genuinely lacks. The two are indistinguishable. A slot never filled is not.
    """

    import pytest

    import run_ledger_backtest as backtest

    bar = backtest.Bar.__new__(backtest.Bar)
    with pytest.raises(AttributeError):
        bar.close


def test_sharing_a_value_cannot_change_a_comparison():
    """The loader shares one object per distinct value. The whole change rests
    on Python comparing by value, so it is asserted rather than argued."""

    import run_ledger_backtest as backtest

    pool: dict = {}
    shared = [pool.setdefault(v, v) for v in (12.5, 12.5)]
    assert shared[0] == shared[1] == 12.5 and shared[0] is shared[1]
    # `is None` still works: None is a singleton and is never pooled.
    assert backtest.Bar(tuple([None] * 12)).close is None


def test_the_loader_shares_values_and_says_why():
    source = (REPO / "scripts" / "m6" / "run_ledger_backtest.py").read_text(
        encoding="utf-8"
    )
    assert "pool.setdefault(v, v)" in source
    assert "cannot change behaviour" in source


def test_the_projection_is_a_real_saving():
    """Twelve of twenty-three. If the list ever grows to cover everything the
    projection has stopped paying for itself and should be reconsidered rather
    than left as decoration."""

    import run_ledger_backtest as backtest

    assert len(backtest.DATASET_COLUMNS) <= 16
    assert "columns=list(DATASET_COLUMNS)" in SOURCE


class TestTheFinMindIntradayProbeAsksOnlyWhatIsUnsettled:
    """The 2026-08-21 cross-validation settled the tier, the rate limit, the
    universe coverage and the price agreement. A probe that re-asked those
    would spend the free tier's hourly budget on answers already on record.
    """

    PROBE = (REPO / "scripts" / "audit" / "probe_finmind_intraday.py").read_text(
        encoding="utf-8"
    )

    def test_it_probes_a_liquid_control_alongside_the_delisted_case(self):
        """Without the control, a refusal on the delisted security cannot be
        told from a refusal about the tier."""

        assert 'LIQUID_CONTROL = "2330"' in self.PROBE
        assert 'DELISTED_CASE = "3202"' in self.PROBE

    def test_it_keeps_a_daily_request_as_the_liveness_control(self):
        """A refusal on the minute dataset means nothing if the network or the
        account is down. The daily call is what separates them."""

        assert 'f"daily/{DELISTED_CASE}/window"' in self.PROBE

    def test_a_refusal_is_recorded_rather_than_raised(self):
        """The tier refusal **is** the answer to question one. Raising on it
        would throw the finding away."""

        assert "Every outcome is data. Nothing here raises on a refusal." in self.PROBE

    def test_the_interval_respects_the_measured_free_tier_limit(self):
        """300 requests an hour is one every twelve seconds."""

        assert "INTERVAL_SECONDS = 12.0" in self.PROBE

    def test_output_may_not_land_in_the_repository(self):
        """The same guard the history probe needed after it wrote into the
        repository while its own check said nothing -- resolved first, because
        a relative path is not `is_relative_to` an absolute one."""

        assert "out = args.out.resolve()" in self.PROBE
        assert "is inside the repository" in self.PROBE
