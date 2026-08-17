"""M3.4 invariants for the price and corporate-action tables.

The failure mode these guard against is the quiet one: a gap that gets filled,
a price that gets adjusted without a documented method, or an action treated
as knowable before it was announced. None of those raise an error at the time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIT = Path(r"C:\tmp\tw-alpha-m3-pit-prices-01")


def table(name: str):
    path = PIT / name
    if not path.is_file():
        pytest.skip(f"{name} not built on this machine")
    pq = pytest.importorskip("pyarrow.parquet")
    return pq.read_table(path)


@pytest.fixture(scope="module")
def prices():
    return table("daily_prices_pit.parquet")


@pytest.fixture(scope="module")
def actions():
    return table("corporate_actions_pit.parquet")


class TestPricesAreRawAndUnfilled:
    def test_every_row_declares_a_raw_unadjusted_basis(self, prices):
        assert set(prices["price_basis"].to_pylist()) == {"raw-official-unadjusted"}

    def test_missing_ohlc_is_left_missing(self, prices):
        """A row whose state says no OHLC must not carry a close anyway."""

        states = prices["ohlc_state"].to_pylist()
        closes = prices["close"].to_pylist()
        leaked = [
            i
            for i, state in enumerate(states)
            if state in {"activity-without-ohlc", "no-price-fields-published"}
            and closes[i] not in (None, "")
        ]
        assert not leaked, f"{len(leaked)} rows carry a close despite a no-OHLC state"

    def test_activity_without_ohlc_is_recorded_rather_than_dropped(self, prices):
        states = prices["ohlc_state"].to_pylist()
        assert "activity-without-ohlc" in states, (
            "no activity-without-OHLC rows survived; they are evidence that a "
            "security traded in some form without a regular quote, and dropping "
            "them would hide it"
        )

    def test_no_session_outside_the_fixed_window(self, prices):
        dates = prices["session_date"].to_pylist()
        assert min(dates) >= "2025-01-01"
        assert max(dates) <= "2026-08-03"

    def test_every_row_carries_full_lineage(self, prices):
        for column in ("source_id", "snapshot_id", "parse_run_id", "record_id"):
            values = prices[column].to_pylist()
            assert all(v for v in values), f"{column} has empty values"

    def test_price_rows_come_only_from_quality_gated_sources(self, prices):
        tiers = set(prices["evidence_tier"].to_pylist())
        assert tiers == {"gated-full"}, (
            f"price rows must come from quality-gated observations, saw {tiers}"
        )

    def test_session_count_matches_the_calendar(self, prices):
        assert len(set(prices["session_date"].to_pylist())) == 382


class TestCorporateActionAvailability:
    def test_availability_basis_is_declared_for_every_row(self, actions):
        allowed = {"publisher-exact", "first-observed-only", "unknown-blocked"}
        assert set(actions["availability_basis"].to_pylist()) <= allowed

    def test_rows_without_an_announcement_date_are_not_claimed_as_exact(self, actions):
        announced = actions["announced_at"].to_pylist()
        basis = actions["availability_basis"].to_pylist()
        wrong = [
            i
            for i, value in enumerate(announced)
            if not value and basis[i] == "publisher-exact"
        ]
        assert not wrong, (
            f"{len(wrong)} actions claim an exact publisher time with no "
            "announcement date"
        )

    def test_adjustment_evidence_is_never_inferred_from_price_moves(self, actions):
        allowed = {"publisher-reference-price"}
        assert set(actions["adjustment_evidence"].to_pylist()) <= allowed

    def test_effective_date_is_present(self, actions):
        assert all(actions["effective_date"].to_pylist())


class TestKnownGaps:
    """Gaps recorded as tests so they cannot be forgotten or quietly closed."""

    def test_twt49u_supplies_no_announcement_date_at_all(self, actions):
        """Every TWT49U row lacks one, so none is usable point-in-time yet.

        The plan assumed only *some* actions would lack an announcement date.
        The endpoint supplies none, so all 1,670 fall back to
        `first-observed-only` — and first observation is 2026, which puts them
        after every date in the window. A separate announcement source is
        required before corporate actions can inform an as-of query.
        """

        basis = actions["availability_basis"].to_pylist()
        assert set(basis) == {"first-observed-only"}

    @pytest.mark.xfail(
        reason=(
            "TPEx corporate actions live in MOPS per-symbol documents and are "
            "not yet promoted into corporate_actions_pit"
        ),
        strict=True,
    )
    def test_both_markets_are_represented(self, actions):
        assert set(actions["market"].to_pylist()) == {"TWSE", "TPEX"}
