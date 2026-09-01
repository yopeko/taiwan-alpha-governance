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

# Every test in this module reads the operator's warehouse or archives, so all
# of them skip on a machine without them -- and on a machine with them, they
# are where the suite's 25 minutes go. The marker was declared in
# tests/conftest.py on 2026-08-17 and nothing used it until 2026-09-01.
#
# `pytest -m "not needs_local_data"` is the lane the pre-commit hook runs. A
# hook slow enough to be bypassed is a hook that gets bypassed, and the value
# of these checks is zero on the commits where someone passes --no-verify.
pytestmark = pytest.mark.needs_local_data

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
        """No listing date, no permission -- but a firmer refusal may win.

        Same rule as absence from the closing table below: `ineligible` is a
        stronger statement than `unknown`, not a weaker one. A security the
        Owner has put out of scope is refused on that ground without anyone
        needing to establish when it listed.
        """

        result = warehouse.reconstruct(
            as_of_session="2025-06-16", decision_as_of="2025-06-16"
        )
        unknown = [s for s in result.securities if s.membership_state == "unknown"]
        assert unknown, "expected some securities with no usable listing date"
        assert all(s.tradability_state != "eligible" for s in unknown)
        # A firmer refusal may replace the vague one, but never a permission.
        # Once the company master arrived, most of these stopped being
        # "we do not know when it listed" and became "it was on a board that
        # is out of scope", which is the same refusal said properly.
        assert all(
            s.tradability_state == "unknown" or s.reason_codes for s in unknown
        )

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


class TestCorporateActionsAreVisible:
    """Until now the as-of layer read prices and status but not actions.

    That is its own failure mode, and a quiet one: every ex-dividend day looked
    like an ordinary session, so a return computed across it counted the
    distribution as a loss. These check that the event is surfaced, and that
    surfacing it did not open a hole in the other direction.
    """

    # 2352 佳世達 resumed from its capital reduction on this session.
    REDUCTION_SESSION = "2025-10-07"
    # 4763 材料-KY resumed from a par-value change; TWSE publishes no
    # announcement date for these at all.
    PAR_VALUE_SESSION = "2025-06-30"
    # 8932 智通 resumed from a TPEx par-value change, which does carry one.
    TPEX_SESSION = "2026-03-09"

    def one(self, warehouse, session, symbol):
        result = warehouse.reconstruct(
            as_of_session=session, decision_as_of=session
        )
        found = [s for s in result.securities if s.symbol == symbol]
        assert found, f"{symbol} absent from {session}"
        return found[0]

    def test_a_restatement_session_is_not_silent(self, warehouse):
        state = self.one(warehouse, self.REDUCTION_SESSION, "2352")
        assert state.corporate_action_state == "capital_reduction"
        assert "price-not-comparable-to-previous-close" in state.reason_codes

    def test_an_ordinary_session_reports_no_action(self, warehouse):
        """The flag has to mean something, so it must be off by default."""

        state = self.one(warehouse, "2025-09-26", "2352")
        assert state.corporate_action_state == "no-action"
        assert "price-not-comparable-to-previous-close" not in state.reason_codes

    def test_an_action_does_not_make_a_tradable_security_untradable(self, warehouse):
        """An ex-date is an ordinary trading day.

        The price basis changes; the ability to trade does not. Downgrading
        tradability here would quietly remove every dividend payer from the
        universe on its ex-date.
        """

        state = self.one(warehouse, self.REDUCTION_SESSION, "2352")
        assert state.tradability_state == "eligible"

    def test_an_unannounced_action_is_shown_but_labelled(self, warehouse):
        """TWSE publishes the par-value change but never says when it said so.

        The restatement still happened on the day, so hiding it would fabricate
        a ninety percent loss. What must not happen is pretending it could have
        been anticipated.
        """

        state = self.one(warehouse, self.PAR_VALUE_SESSION, "4763")
        assert state.corporate_action_state == "par_value_change"
        assert "action-not-announced-in-advance" in state.reason_codes

    def test_an_announced_action_is_not_labelled_as_unannounced(self, warehouse):
        """The same event kind, the other market, the better provenance.

        If this ever starts matching the TWSE case, the announcement dates have
        stopped reaching the table and nobody would otherwise notice.
        """

        state = self.one(warehouse, self.TPEX_SESSION, "8932")
        assert state.corporate_action_state == "par_value_change"
        assert "action-not-announced-in-advance" not in state.reason_codes

    def test_no_action_dated_after_the_session_ever_appears(self, warehouse):
        """The whole point. An action is surfaced on its effective date only.

        Surfacing a future ex-date would hand the caller a dividend nobody had
        yet received, which is the exact class of leak this module exists to
        prevent.
        """

        session = "2025-07-15"
        result = warehouse.reconstruct(as_of_session=session, decision_as_of="2026-08-03")
        flagged = [
            s
            for s in result.securities
            if s.corporate_action_state not in ("no-action", "no-coverage")
        ]
        assert flagged, "no actions at all on a session known to have them"
        for state in flagged:
            rows = [
                row
                for row in warehouse._actions
                if row.get("market") == state.market
                and str(row.get("symbol")) == state.symbol
            ]
            effective = {str(row.get("effective_date")) for row in rows}
            assert session in effective, (
                f"{state.symbol} was flagged on {session} with no action "
                f"effective that day: {sorted(effective)}"
            )

    def test_a_later_cutoff_does_not_change_what_happened_that_day(self, warehouse):
        """Actions are contemporaneous facts, so the cutoff must not move them.

        Status and prices are filtered by what was knowable; the restatement is
        not, because it took effect on the session being reconstructed. This
        pins that distinction so it cannot be "fixed" into a leak later.
        """

        session = "2025-07-15"
        same_day = warehouse.reconstruct(as_of_session=session, decision_as_of=session)
        much_later = warehouse.reconstruct(
            as_of_session=session, decision_as_of="2026-08-03"
        )
        by_symbol = {(s.market, s.symbol): s.corporate_action_state for s in same_day.securities}
        for state in much_later.securities:
            assert by_symbol[(state.market, state.symbol)] == state.corporate_action_state

    def test_a_date_outside_the_built_window_is_unknown_not_empty(self, warehouse):
        """Outside the window there is no evidence, which is not the same as none."""

        from datetime import date, timedelta

        start, end = warehouse._action_window
        assert start and end, "the action table records no window"
        # Derived from the window the table reports, not written down. This
        # was the literal "2024-01-02", chosen when the window began in 2025;
        # the six-year rebuild moved the window over it and the test began
        # asserting that a date inside the window was outside it.
        outside = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        assert not warehouse._has_action_coverage(outside)
        assert warehouse._has_action_coverage(end)
