"""M3.5 invariants for market status and fundamentals.

The two tables fail in opposite directions, so they are guarded differently:
status by refusing to let absence mean permission, fundamentals by refusing to
let a figure be available before it was filed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIT = Path(r"C:\tmp\tw-alpha-m3-pit-status-01")


def table(name: str):
    path = PIT / name
    if not path.is_file():
        pytest.skip(f"{name} not built on this machine")
    pq = pytest.importorskip("pyarrow.parquet")
    return pq.read_table(path)


@pytest.fixture(scope="module")
def status():
    return table("market_status_pit.parquet")


@pytest.fixture(scope="module")
def coverage():
    return table("market_status_coverage.parquet")


@pytest.fixture(scope="module")
def fundamentals():
    return table("fundamentals_pit.parquet")


class TestMarketStatusAbsenceIsNotPermission:
    def test_coverage_intervals_exist_so_absence_can_be_interpreted(self, coverage):
        assert coverage.num_rows > 0, (
            "without coverage intervals a query cannot tell 'no event' from "
            "'no coverage', and would read silence as tradable"
        )

    def test_coverage_spans_the_whole_fixed_window(self, coverage):
        starts = coverage["coverage_from"].to_pylist()
        ends = coverage["coverage_to"].to_pylist()
        assert min(starts) <= "2025-01-01"
        assert max(ends) >= "2026-08-03"

    def test_every_event_carries_an_announcement_date(self, status):
        announced = status["announced_at"].to_pylist()
        missing = sum(1 for value in announced if not value)
        assert missing == 0, f"{missing} status events have no announcement date"

    def test_availability_basis_matches_the_announcement_date(self, status):
        announced = status["announced_at"].to_pylist()
        basis = status["availability_basis"].to_pylist()
        wrong = [
            i for i, value in enumerate(announced)
            if bool(value) != (basis[i] == "publisher-exact")
        ]
        assert not wrong, f"{len(wrong)} rows disagree with their availability basis"

    def test_disposal_events_keep_their_effective_interval(self, status):
        kinds = status["event_kind"].to_pylist()
        starts = status["effective_from"].to_pylist()
        disposals = [i for i, k in enumerate(kinds) if k == "disposal"]
        assert disposals, "no disposal events"
        assert all(starts[i] for i in disposals), (
            "a disposal without an effective interval cannot be applied to a date"
        )

    def test_announcement_never_follows_the_effect_it_announces(self, status):
        kinds = status["event_kind"].to_pylist()
        announced = status["announced_at"].to_pylist()
        starts = status["effective_from"].to_pylist()
        late = [
            i
            for i, kind in enumerate(kinds)
            if kind == "disposal" and starts[i] and announced[i] > starts[i]
        ]
        assert not late, (
            f"{len(late)} disposals are announced after they take effect, which "
            "would make them unknowable when they began"
        )

    def test_suspension_is_absent_and_that_is_deliberate(self, status):
        kinds = set(status["event_kind"].to_pylist())
        assert "suspension" not in kinds, (
            "suspension has no official historical source; if it appears here "
            "it came from somewhere unapproved"
        )


class TestFundamentalAvailability:
    def test_most_rows_have_a_publisher_filing_date(self, fundamentals):
        basis = fundamentals["availability_basis"].to_pylist()
        exact = sum(1 for value in basis if value == "publisher-exact")
        assert exact / len(basis) > 0.9, (
            f"only {exact}/{len(basis)} rows have a filing date; without one a "
            "figure cannot be used at any historical cutoff"
        )

    def test_a_filing_date_is_present_whenever_claimed(self, fundamentals):
        basis = fundamentals["availability_basis"].to_pylist()
        released = fundamentals["publisher_released_at"].to_pylist()
        wrong = [
            i for i, value in enumerate(basis)
            if value == "publisher-exact" and not released[i]
        ]
        assert not wrong, f"{len(wrong)} rows claim an exact filing time with no date"

    def test_vendor_sourced_availability_is_labelled_as_such(self, fundamentals):
        basis = fundamentals["availability_basis"].to_pylist()
        evidence = fundamentals["availability_evidence_state"].to_pylist()
        wrong = [
            i for i, value in enumerate(basis)
            if value == "publisher-exact"
            and evidence[i] != "licensed-vendor-snapshot"
        ]
        assert not wrong, (
            "filing dates come from TEJ and must keep the licensed-vendor "
            "evidence state rather than inheriting the statement's"
        )

    def test_every_row_declares_a_statement_type(self, fundamentals):
        assert all(fundamentals["statement_type"].to_pylist())

    def test_revision_chain_column_exists_even_while_empty(self, fundamentals):
        assert "revision_of_record_id" in fundamentals.column_names
