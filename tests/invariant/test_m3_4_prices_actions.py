"""M3.4 invariants for the price and corporate-action tables.

The failure mode these guard against is the quiet one: a gap that gets filled,
a price that gets adjusted without a documented method, or an action treated
as knowable before it was announced. None of those raise an error at the time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIT = Path(r"C:\tmp\tw-alpha-m3-pit-prices-07")


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

        allowed = {
            "publisher-reference-price",
            "publisher-dividend-amount-only",
            "publisher-resumption-reference-price",
            "publisher-exchange-ratio-only",
        }
        assert set(actions["adjustment_evidence"].to_pylist()) <= allowed

    def test_effective_date_is_present(self, actions):
        assert all(actions["effective_date"].to_pylist())


class TestKnownGaps:
    """Gaps recorded as tests so they cannot be forgotten or quietly closed."""

    def test_a_twt49u_date_is_always_labelled_as_vendor_evidence(self, actions):
        """TWT49U still publishes no announcement date. The vendor supplies it.

        This began as "no TWT49U row has a date at all", which held until the
        licensed-vendor lane was joined in. The gap it recorded is closed, but
        the risk it guarded moved rather than vanished: a vendor date wearing
        official evidence would let a reader treat TEJ's word as the exchange's.
        """

        rows = [
            (basis, announced, evidence)
            for basis, announced, evidence, source in zip(
                actions["availability_basis"].to_pylist(),
                actions["announced_at"].to_pylist(),
                actions["announcement_evidence_state"].to_pylist(),
                actions["source_id"].to_pylist(),
            )
            if source == "TWSE-ACTIONS-HIST"
        ]
        assert rows
        for basis, announced, evidence in rows:
            if announced:
                assert evidence == "licensed-vendor-snapshot", (
                    "an announcement date on a TWT49U row can only have come "
                    "from the vendor, so it must not claim official evidence"
                )
            else:
                assert evidence == "missing-at-source"
                assert basis == "first-observed-only"

    def test_the_action_itself_never_becomes_vendor_evidence(self, actions):
        """One field came from TEJ. Nothing else may.

        The event set, the reference price and the limits are the exchange's.
        If `evidence_state` ever follows the announcement into the vendor lane,
        the official record has been quietly relabelled.
        """

        assert set(actions["evidence_state"].to_pylist()) == {"verified-snapshot"}

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


class TestCapitalReductionIsAlsoAnAction:
    """The halt lives in market status; the price restatement lives here.

    They are two facts about one event, and each is stored where its shape
    fits. A consumer adjusting prices looks at corporate actions, and without
    these rows it sees nothing on the day a security's price legitimately
    jumps by a factor of ten.
    """

    def reductions(self, actions):
        """TWSE reductions only, because only TWSE publishes the prices.

        TPEx reductions reach this table too, but from the announcement
        archive, which states the exchange ratio and nothing about price: TPEx
        publishes its resumption reference only for the next few days. The
        price assertions below therefore apply to TWSE, and the difference is
        carried explicitly by `adjustment_evidence` rather than by a null that
        a reader has to interpret.
        """

        types = actions["action_type"].to_pylist()
        markets = actions["market"].to_pylist()
        return [
            i
            for i, t in enumerate(types)
            if t == "capital_reduction" and markets[i] == "TWSE"
        ]

    def test_reductions_reach_the_action_table(self, actions):
        assert self.reductions(actions), "no TWSE capital-reduction actions"

    def test_tpex_halts_declare_that_they_carry_no_reference_price(self, actions):
        """The absence is a stated fact, not a gap to be filled in later.

        Anyone adjusting TPEx prices across a reduction has to know the
        exchange's own reference price is unavailable for history, so the row
        says so instead of leaving four nulls to be guessed at.
        """

        markets = actions["market"].to_pylist()
        types = actions["action_type"].to_pylist()
        evidence = actions["adjustment_evidence"].to_pylist()
        reference = actions["reference_price"].to_pylist()
        rows = [
            i
            for i, t in enumerate(types)
            if markets[i] == "TPEX" and t in ("capital_reduction", "par_value_change")
        ]
        assert rows, "no TPEx halt actions"
        assert {evidence[i] for i in rows} == {"publisher-exchange-ratio-only"}
        assert all(reference[i] is None for i in rows)

    def test_each_one_carries_the_resumption_reference_price(self, actions):
        """The reference is the whole point of the row.

        The limits the exchange published are set around it, and the standard
        ten percent rule reproduces them from it exactly. From the pre-halt
        close it reproduces none of them.
        """

        reference = actions["reference_price"].to_pylist()
        missing = [i for i in self.reductions(actions) if reference[i] in (None, "")]
        assert not missing, (
            f"{len(missing)} reductions have no resumption reference price"
        )

    def test_the_reference_is_not_the_pre_halt_close(self, actions):
        """If they were equal the row would be carrying the wrong number.

        6120 is the one reduction whose reference happens to sit near its prior
        close, so a blanket inequality would be wrong; the check is that they
        are not systematically identical.
        """

        reference = actions["reference_price"].to_pylist()
        prior = actions["prior_close"].to_pylist()
        rows = self.reductions(actions)
        differing = sum(1 for i in rows if reference[i] != prior[i])
        assert differing >= len(rows) - 1, (
            "reference prices look copied from the prior close"
        )

    def test_the_published_limits_come_with_them(self, actions):
        up = actions["limit_up"].to_pylist()
        down = actions["limit_down"].to_pylist()
        missing = [
            i for i in self.reductions(actions) if up[i] is None or down[i] is None
        ]
        assert not missing, (
            f"{len(missing)} reductions arrive without the limits the exchange "
            "published, which is what lets M4 resolve them publisher-exact"
        )


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
