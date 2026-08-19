"""M3.4 invariants for the price and corporate-action tables.

The failure mode these guard against is the quiet one: a gap that gets filled,
a price that gets adjusted without a documented method, or an action treated
as knowable before it was announced. None of those raise an error at the time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIT = Path(r"C:\tmp\tw-alpha-m3-pit-prices-02")


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
        """Both allowed values name what the publisher stated, never a gap.

        TWSE publishes the reference price it used; TPEx publishes only the
        dividend amount. Whoever adjusts prices has to know which, because a
        dividend alone does not determine the reference price the exchange
        actually applied.
        """

        allowed = {"publisher-reference-price", "publisher-dividend-amount-only"}
        assert set(actions["adjustment_evidence"].to_pylist()) <= allowed

    def test_effective_date_is_present(self, actions):
        assert all(actions["effective_date"].to_pylist())


class TestKnownGaps:
    """Gaps recorded as tests so they cannot be forgotten or quietly closed."""

    def test_twt49u_supplies_no_announcement_date_at_all(self, actions):
        """Still true of TWSE, and only of TWSE.

        The endpoint supplies no announcement date for any row, so every TWSE
        action falls back to `first-observed-only` — and first observation is
        2026, which puts it after every date in the window. M3.9 closes this
        from the TEJ lane in a separate table; this table remains official-only
        and therefore still unusable point-in-time for TWSE.
        """

        basis = [
            b
            for b, market in zip(
                actions["availability_basis"].to_pylist(),
                actions["market"].to_pylist(),
            )
            if market == "TWSE"
        ]
        assert basis and set(basis) == {"first-observed-only"}

    def test_tpex_actions_carry_the_announcement_date_twse_lacks(self, actions):
        """The MOPS route gives what TWT49U does not.

        TPEx has no range endpoint, so each action arrives as the announcement
        document that published it, and the announcement date comes with it.
        The market with the worse endpoint ends up with the better provenance.
        """

        pairs = [
            (market, basis)
            for market, basis in zip(
                actions["market"].to_pylist(),
                actions["availability_basis"].to_pylist(),
            )
            if market == "TPEX"
        ]
        assert pairs, "no TPEx actions"
        assert {basis for _, basis in pairs} == {"publisher-exact"}


class TestBothMarketsPresent:
    def test_both_markets_are_represented(self, actions):
        assert set(actions["market"].to_pylist()) == {"TWSE", "TPEX"}

    def test_one_action_is_not_stored_several_times(self, actions):
        """Overlapping range queries return the same action more than once.

        Counting it twice would double a dividend. Two rows may share an
        ex-date only when their terms differ, which is a restatement, so the
        check is on the terms and not on the slot.
        """

        counts: dict[tuple, int] = {}
        for values in zip(
            actions["market"].to_pylist(),
            actions["symbol"].to_pylist(),
            actions["effective_date"].to_pylist(),
            actions["action_type"].to_pylist(),
            actions["cash_dividend"].to_pylist(),
            actions["stock_dividend_ratio"].to_pylist(),
        ):
            counts[values] = counts.get(values, 0) + 1
        repeats = {k: v for k, v in counts.items() if v > 1}
        assert not repeats, f"identical actions stored more than once: {repeats}"

    def test_a_restated_slot_is_numbered_so_a_cutoff_can_choose(self, actions):
        """Two rows for one ex-date must be orderable, or a query gets both.

        The exchange restates terms when a figure changes. Point-in-time, the
        answer depends on the cutoff, so the rows carry an order rather than
        one of them being deleted.
        """

        assert "revision_ordinal" in actions.column_names
        slots: dict[tuple, list[tuple]] = {}
        for market, symbol, effective, ordinal, announced in zip(
            actions["market"].to_pylist(),
            actions["symbol"].to_pylist(),
            actions["effective_date"].to_pylist(),
            actions["revision_ordinal"].to_pylist(),
            actions["announced_at"].to_pylist(),
        ):
            slots.setdefault((market, symbol, effective), []).append(
                (ordinal, announced)
            )
        for slot, entries in slots.items():
            ordinals = sorted(o for o, _ in entries)
            assert ordinals == list(range(len(entries))), (
                f"{slot} has non-contiguous revision ordinals {ordinals}"
            )
            ordered = sorted(entries)
            announced = [a for _, a in ordered]
            assert announced == sorted(announced, key=lambda v: v or ""), (
                f"{slot} numbers its restatements out of announcement order"
            )
