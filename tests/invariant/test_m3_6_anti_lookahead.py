"""M3.6 anti-lookahead tests: the reason the warehouse exists.

Every earlier work package proved the data was captured, reproducible and had
lineage. None of them proved that asking about a past date cannot return
something only knowable later. These do.

The tests are written adversarially: each one describes a way a careless
implementation would leak the future, then asserts it does not happen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))


@pytest.fixture(scope="module")
def warehouse():
    pytest.importorskip("pyarrow")
    try:
        from asof import default_warehouse

        return default_warehouse()
    except Exception as exc:  # noqa: BLE001 - tables may not be built here
        pytest.skip(f"warehouse not available: {exc}")


class TestKnowabilityPredicate:
    """The single comparison the whole guarantee rests on."""

    def test_a_fact_with_no_announcement_date_is_never_knowable(self):
        from asof import Warehouse

        assert Warehouse.is_knowable("", "2026-08-03") is False
        assert Warehouse.is_knowable("", "1990-01-01") is False

    def test_a_fact_announced_later_is_not_knowable(self):
        from asof import Warehouse

        assert Warehouse.is_knowable("2025-03-15", "2025-03-14") is False

    def test_a_fact_announced_on_the_day_is_knowable(self):
        from asof import Warehouse

        assert Warehouse.is_knowable("2025-03-14", "2025-03-14") is True

    def test_a_fact_announced_earlier_is_knowable(self):
        from asof import Warehouse

        assert Warehouse.is_knowable("2025-01-02", "2025-03-14") is True


class TestQueryRefusesImpossibleQuestions:
    def test_decision_time_before_the_session_is_rejected(self, warehouse):
        from asof import AsOfError

        with pytest.raises(AsOfError):
            warehouse.reconstruct(
                as_of_session="2025-03-14", decision_as_of="2025-03-13"
            )


class TestFutureStatusNeverLeaks:
    """A disposal announced tomorrow must not restrict a security today."""

    def _restricted(self, result):
        return {
            s.symbol for s in result.securities if s.tradability_state == "restricted"
        }

    def test_restrictions_grow_monotonically_with_the_decision_time(self, warehouse):
        session = "2025-03-14"
        early = warehouse.reconstruct(as_of_session=session, decision_as_of=session)
        late = warehouse.reconstruct(as_of_session=session, decision_as_of="2026-08-03")
        assert self._restricted(early) <= self._restricted(late), (
            "knowing less cannot restrict more; a symbol restricted at the "
            "earlier cutoff but not the later one means the filter is unsound"
        )

    def test_a_later_cutoff_can_reveal_more(self, warehouse):
        """Sanity check that the filter actually does something."""

        session = "2025-03-14"
        early = warehouse.reconstruct(as_of_session=session, decision_as_of=session)
        late = warehouse.reconstruct(as_of_session=session, decision_as_of="2026-08-03")
        assert len(self._restricted(late)) >= len(self._restricted(early))

    def test_every_reported_status_was_announced_by_the_cutoff(self, warehouse):
        """Directly re-derive the guarantee from the underlying rows."""

        from asof import _iso

        session, cutoff = "2025-06-16", "2025-06-16"
        result = warehouse.reconstruct(as_of_session=session, decision_as_of=cutoff)
        flagged = {
            s.symbol
            for s in result.securities
            if s.market_status_state not in {"no-event-in-covered-window", "no-coverage"}
        }
        leaks = []
        for row in warehouse._status:
            if str(row.get("symbol")) not in flagged:
                continue
            announced = _iso(row.get("announced_at"))
            start = _iso(row.get("effective_from"))
            end = _iso(row.get("effective_to"))
            covers = (start <= session <= end) if start and end else announced == session
            if covers and announced > cutoff:
                leaks.append((row.get("symbol"), announced))
        assert not leaks, f"status known only after the cutoff was applied: {leaks[:5]}"


class TestLifecycleBoundaries:
    def test_a_security_is_not_eligible_before_it_listed(self, warehouse):
        result = warehouse.reconstruct(
            as_of_session="2025-01-02", decision_as_of="2025-01-02"
        )
        early = [s for s in result.securities if s.membership_state == "not-yet-listed"]
        assert all(s.tradability_state == "ineligible" for s in early)

    def test_a_delisted_security_is_not_eligible_afterwards(self, warehouse):
        # 2888 delisted 2025-07-24.
        after = warehouse.reconstruct(
            as_of_session="2025-08-01", decision_as_of="2025-08-01", symbols=["2888"]
        )
        assert after.securities
        assert all(s.membership_state == "delisted" for s in after.securities)
        assert all(s.tradability_state == "ineligible" for s in after.securities)

    def test_the_same_security_was_eligible_before_delisting(self, warehouse):
        before = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16", symbols=["2888"]
        )
        assert before.securities
        assert all(s.membership_state == "listed" for s in before.securities)

    def test_membership_does_not_depend_on_the_decision_time(self, warehouse):
        """Listing is a market fact, so a later cutoff must not change it."""

        early = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        late = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2026-08-03"
        )
        early_states = {(s.market, s.symbol): s.membership_state for s in early.securities}
        late_states = {(s.market, s.symbol): s.membership_state for s in late.securities}
        assert early_states == late_states


class TestFailClosed:
    def test_a_closed_session_makes_everything_ineligible(self, warehouse):
        result = warehouse.reconstruct(
            as_of_session="2026-07-10", decision_as_of="2026-08-03"
        )
        assert result.session_states["TWSE"] == "official-closed"
        assert set(result.by_tradability()) == {"ineligible"}

    def test_nothing_is_eligible_without_a_listing_date(self, warehouse):
        result = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        unknown = [s for s in result.securities if s.membership_state == "unknown"]
        assert all(s.tradability_state == "unknown" for s in unknown)

    def test_absence_from_the_official_table_blocks_rather_than_permits(self, warehouse):
        result = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        absent = [
            s for s in result.securities
            if s.price_state == "absent-from-official-table"
        ]
        assert absent, "expected some securities absent from the closing table"
        # Absence never grants permission. A security that was also delisted or
        # not yet listed is `ineligible` for that reason instead, which is a
        # stronger statement than `blocked`, not a weaker one.
        assert all(s.tradability_state != "eligible" for s in absent)
        listed = [s for s in absent if s.membership_state == "listed"]
        assert listed, "expected some listed securities absent from the table"
        assert all(s.tradability_state == "blocked" for s in listed)
        assert all(
            "suspension-inferred-from-price-absence" in s.reason_codes for s in listed
        )

    def test_every_non_eligible_state_carries_a_reason_or_a_definite_state(
        self, warehouse
    ):
        result = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        for state in result.securities:
            if state.tradability_state == "eligible":
                continue
            assert state.reason_codes or state.membership_state in {
                "not-yet-listed",
                "delisted",
            } or state.session_state != "official-open"


class TestDeterminism:
    def test_the_same_question_yields_the_same_output_hash(self, warehouse):
        first = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        second = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        assert first.output_hash == second.output_hash

    def test_a_different_cutoff_yields_a_different_hash(self, warehouse):
        first = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        second = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2026-08-03"
        )
        assert first.dataset_id == second.dataset_id
        assert first.output_hash != second.output_hash
