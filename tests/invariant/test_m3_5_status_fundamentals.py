"""M3.5 invariants for market status and fundamentals.

The two tables fail in opposite directions, so they are guarded differently:
status by refusing to let absence mean permission, fundamentals by refusing to
let a figure be available before it was filed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIT = Path(r"C:\tmp\tw-alpha-m3-pit-status-06")
PRICES = Path(r"C:\tmp\tw-alpha-m3-pit-prices-02")


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


class TestCapitalReductionHalts:
    """A reduction halt is the one status event with a hard price consequence.

    Trading stops, and when it resumes the price is restated on a new share
    base. A backtest that misses the halt sees an unexplained gap; one that
    misses the restatement sees a fabricated return. Both dates therefore have
    to be present and ordered, or the row must be blocked outright.
    """

    def reductions(self, status):
        kinds = status["event_kind"].to_pylist()
        return [i for i, kind in enumerate(kinds) if kind == "capital-reduction"]

    def test_reductions_are_present(self, status):
        assert self.reductions(status), (
            "no capital reductions; the resumption listing covers the window "
            "and is known to contain them"
        )

    def test_every_reduction_has_both_ends_of_its_halt(self, status):
        starts = status["effective_from"].to_pylist()
        ends = status["effective_to"].to_pylist()
        missing = [
            i for i in self.reductions(status) if not starts[i] or not ends[i]
        ]
        assert not missing, (
            f"{len(missing)} reductions have an open-ended halt; the halt date "
            "comes from the announcement document, so this means the document "
            "was not joined"
        )

    def test_the_halt_starts_before_it_ends(self, status):
        starts = status["effective_from"].to_pylist()
        ends = status["effective_to"].to_pylist()
        wrong = [i for i in self.reductions(status) if starts[i] >= ends[i]]
        assert not wrong, f"{len(wrong)} reductions resume on or before they halt"

    def test_a_usable_reduction_is_announced_before_it_halts(self, status):
        announced = status["announced_at"].to_pylist()
        starts = status["effective_from"].to_pylist()
        basis = status["availability_basis"].to_pylist()
        late = [
            i
            for i in self.reductions(status)
            if basis[i] == "publisher-exact" and announced[i] > starts[i]
        ]
        assert not late, (
            f"{len(late)} reductions claim an exact announcement dated after "
            "the halt began, which would make the halt unknowable when it started"
        )

    def test_no_security_trades_during_its_own_halt(self, status):
        """The strongest available check, and it shares no code with the halt.

        The halt dates come from the announcement documents; the price table
        comes from the daily quotation feed. If a security has a price inside
        the interval this table calls a halt, one of the two is wrong.
        """

        path = PRICES / "daily_prices_pit.parquet"
        if not path.is_file():
            pytest.skip("daily_prices_pit not built on this machine")
        pq = pytest.importorskip("pyarrow.parquet")
        prices = pq.read_table(path, columns=["symbol", "session_date"])
        traded: dict[str, set[str]] = {}
        for symbol, session in zip(
            prices["symbol"].to_pylist(), prices["session_date"].to_pylist()
        ):
            traded.setdefault(str(symbol), set()).add(str(session))

        symbols = status["symbol"].to_pylist()
        starts = status["effective_from"].to_pylist()
        ends = status["effective_to"].to_pylist()
        offenders = []
        for i in self.reductions(status):
            inside = sorted(
                s
                for s in traded.get(str(symbols[i]), ())
                if starts[i] <= s <= ends[i]
            )
            if inside:
                offenders.append((symbols[i], starts[i], ends[i], inside))
        assert not offenders, (
            "these securities have quoted prices inside their own halt: "
            f"{offenders}"
        )

    def test_an_unjoined_reduction_is_blocked_rather_than_guessed(self, status):
        announced = status["announced_at"].to_pylist()
        basis = status["availability_basis"].to_pylist()
        leaked = [
            i
            for i in self.reductions(status)
            if not announced[i] and basis[i] != "unknown-blocked"
        ]
        assert not leaked, (
            f"{len(leaked)} reductions have no announcement date but are not "
            "blocked; they would enter as-of results with no evidence of when "
            "they became knowable"
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
