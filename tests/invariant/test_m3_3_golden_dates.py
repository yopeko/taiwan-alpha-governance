"""M3.3 golden-date tests for the calendar and lifecycle tables.

Golden dates are chosen because each one would be wrong under a plausible
shortcut: a holiday you would get right by guessing, a typhoon closure you
would not, and securities that vanished mid-window.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PIT = Path(r"C:\tmp\tw-alpha-m3-pit-04")

sys.path.insert(0, str(REPO / "scripts" / "m3"))


def rows(name: str) -> list[dict[str, str]]:
    path = PIT / name
    if not path.is_file():
        pytest.skip(f"{name} not built on this machine")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def calendar() -> dict[tuple[str, str], dict[str, str]]:
    return {(r["market"], r["session_date"]): r for r in rows("trading_calendar_pit.csv")}


@pytest.fixture(scope="module")
def intervals() -> list[dict[str, str]]:
    return rows("security_intervals.csv")


class TestCalendarGoldenDates:
    def test_new_year_is_closed_in_both_markets(self, calendar):
        for market in ("TWSE", "TPEX"):
            assert calendar[(market, "2025-01-01")]["session_state"] == "official-closed"

    def test_first_trading_day_of_2025_is_open(self, calendar):
        for market in ("TWSE", "TPEX"):
            row = calendar[(market, "2025-01-02")]
            assert row["session_state"] == "official-open"
            assert int(row["observed_row_count"]) > 0

    def test_typhoon_closure_not_in_the_annual_calendar_is_still_closed(self, calendar):
        # 2026-07-10 is absent from the published holiday schedule. Deriving
        # the calendar from "weekdays minus listed holidays" would call this a
        # trading day and invent a session that never happened.
        for market in ("TWSE", "TPEX"):
            assert calendar[(market, "2026-07-10")]["session_state"] == "official-closed"

    def test_lunar_new_year_run_is_closed(self, calendar):
        for day in ("2026-02-16", "2026-02-17", "2026-02-18"):
            assert calendar[("TWSE", day)]["session_state"] == "official-closed"

    def test_no_market_date_is_left_unknown(self, calendar):
        unknown = [k for k, v in calendar.items() if v["session_state"] == "unknown"]
        assert not unknown, f"unresolved market-dates: {unknown[:10]}"

    def test_both_markets_share_the_same_open_days(self, calendar):
        twse = {d for (m, d), v in calendar.items() if m == "TWSE" and v["session_state"] == "official-open"}
        tpex = {d for (m, d), v in calendar.items() if m == "TPEX" and v["session_state"] == "official-open"}
        assert twse == tpex

    def test_every_open_day_cites_a_published_closing_table(self, calendar):
        for key, row in calendar.items():
            if row["session_state"] == "official-open":
                assert row["evidence_basis"] == "official-closing-table-published", key


class TestLifecycleMembership:
    DISAPPEARED = {
        "2888": "2025-07-24",
        "6288": "2025-08-15",
        "2809": "2025-10-01",
        "3454": "2026-03-27",
        "6806": "2026-06-23",
    }

    def _find(self, intervals, symbol):
        matches = [r for r in intervals if r["symbol"] == symbol and r["market"] == "TWSE"]
        if not matches:
            pytest.skip(f"{symbol} absent from the lifecycle lane")
        return matches[0]

    @pytest.mark.parametrize("symbol", sorted(DISAPPEARED))
    def test_delisted_security_is_listed_before_and_delisted_after(
        self, intervals, symbol
    ):
        from build_calendar_lifecycle import membership_on

        row = self._find(intervals, symbol)
        assert row["delisting_date"] == self.DISAPPEARED[symbol]
        delisting = date.fromisoformat(row["delisting_date"])
        instance = row["security_instance_id"]
        # A month before delisting, and the last day of the window.
        assert membership_on([row], delisting - timedelta(days=30))[instance] == "listed"
        assert membership_on([row], date(2026, 8, 3))[instance] == "delisted"
        # The boundary itself: delisting date is the first non-member day.
        assert membership_on([row], delisting)[instance] == "delisted"
        assert membership_on([row], delisting - timedelta(days=1))[instance] == "listed"

    def test_a_security_is_not_a_member_before_its_listing_date(self, intervals):
        from build_calendar_lifecycle import membership_on

        recent = [
            r
            for r in intervals
            if r["listing_date"] and date.fromisoformat(r["listing_date"]) > date(2025, 6, 1)
        ]
        if not recent:
            pytest.skip("no security listed inside the window")
        row = recent[0]
        states = membership_on([row], date(2025, 1, 2))
        assert states[row["security_instance_id"]] == "not-yet-listed"

    def test_missing_listing_date_never_resolves_to_listed(self, intervals):
        from build_calendar_lifecycle import membership_on

        probe = {
            "security_instance_id": "probe",
            "market": "TWSE",
            "symbol": "9999",
            "listing_date": "",
            "delisting_date": "",
            "membership_basis": "missing-at-source",
            "default_membership_state": "unknown",
            "evidence_state": "licensed-vendor-snapshot",
        }
        assert membership_on([probe], date(2025, 6, 2))["probe"] == "unknown"

    def test_lifecycle_rows_keep_their_vendor_evidence_state(self, intervals):
        states = {r["evidence_state"] for r in intervals}
        assert states == {"licensed-vendor-snapshot"}

    def test_a_company_that_stopped_filing_is_still_in_the_universe(self, intervals):
        """3202 樺晟, the security that showed how the universe was selected.

        The lifecycle lane was built from a TEJ *financial statements* export,
        so its universe was really "securities that filed in the queried
        periods". 3202 filed nothing -- its own TEJ record gives 危機事件 =
        財報未出具或遲交 -- and it is absent from all 13,748 rows of that
        export, not merely rejected by it.

        Failing to file is what gets a company delisted. A universe drawn from
        filings therefore drops securities *because* they are failing, which
        is survivorship bias arriving through the selection mechanism rather
        than through anyone's judgement. It traded 57 sessions of our window,
        falling 6.61 to 3.96, and a backtest could not have lost a cent on it.
        """

        matches = [
            r for r in intervals if r["symbol"] == "3202" and r["market"] == "TPEX"
        ]
        assert matches, (
            "3202 has 57 sessions of official TPEx prices and no lifecycle "
            "row; the company master is keyed on the company existing, not "
            "on it reporting"
        )
        row = matches[0]
        assert row["listing_date"] == "2005-07-26"
        assert row["delisting_date"] == "2025-07-21"
        assert row["membership_basis"] == "listed-interval"


class TestTheExchangeOwnsItsOwnDelistings:
    """A delisting is the exchange's act, so the exchange should say so.

    Every delisting here used to be a TEJ claim carrying
    `licensed-vendor-snapshot`, because nobody had asked either exchange --
    both publish a dated list, and both were already on the M2 P0 allowlist
    and had simply never been captured.

    Asking produced 12 agreements, 0 disagreements, and 3 dates the vendor
    does not carry at all. All three are board transfers: 6589 台康生技 and
    5236 凌陽創新 ended their TPEx leg on moving to TWSE, 6423 億而得 ended
    its TWSE leg on moving to TPEx, and TEJ records only the surviving leg.
    The exchange terminates the old one and dates it.
    """

    TRANSFERS = {
        ("TPEX", "6589"): "2025-07-21",
        ("TPEX", "5236"): "2026-07-16",
    }

    def _row(self, intervals, market, symbol):
        matches = [
            r for r in intervals if r["market"] == market and r["symbol"] == symbol
        ]
        if not matches:
            pytest.skip(f"{market} {symbol} absent from the lifecycle lane")
        return max(matches, key=lambda r: r["listing_date"])

    @pytest.mark.parametrize("key", sorted(TRANSFERS))
    def test_a_transferred_leg_is_closed_by_the_exchange(self, intervals, key):
        row = self._row(intervals, *key)
        assert row["delisting_date"] == self.TRANSFERS[key], (
            f"{key} should end on the date the exchange terminated it; the "
            "vendor is silent on transfers and would leave the leg open"
        )
        assert row.get("delisting_basis") == "official-exchange-list"

    def test_an_out_of_scope_leg_is_closed_by_its_board_interval(self):
        """6423's third transfer has no lifecycle row, and should not.

        It left the innovation board for TPEx on 2026-01-22. The innovation
        board is out of the M0 universe, so no lifecycle interval is emitted
        for that leg at all -- the board interval carries it instead. The
        exchange's delisting entry for the TWSE leg therefore has nothing to
        attach to, which is the structure being correct rather than a gap.
        """

        boards = rows("security_board_intervals.csv")
        legs = {
            r["board"]: (r["effective_from"], r["effective_to"])
            for r in boards
            if r["symbol"] == "6423"
        }
        assert legs.get("TIB") == ("2024-05-15", "2026-01-22")
        assert legs.get("OTC", ("", ""))[0] == "2026-01-22"

        listed = [
            r
            for r in rows("security_intervals.csv")
            if r["symbol"] == "6423" and r["market"] == "TWSE"
        ]
        assert not listed, (
            "an innovation-board leg must not appear as a listed interval; "
            "its refusal comes from the board, not from membership"
        )

    def test_an_official_delisting_says_it_is_official(self, intervals):
        """Vendor and exchange evidence must stay distinguishable."""

        bases = {r.get("delisting_basis", "") for r in intervals}
        assert bases <= {"", "official-exchange-list", "licensed-vendor-snapshot"}
        official = [
            r for r in intervals if r.get("delisting_basis") == "official-exchange-list"
        ]
        assert len(official) >= 15, (
            f"only {len(official)} delistings carry exchange evidence; both "
            "lists cover the window and should confirm the great majority"
        )
        assert all(r["delisting_date"] for r in official)

    def test_the_reason_survives_where_the_exchange_gave_one(self, intervals):
        """TPEx cites the rule it acted under, which is how a transfer is
        told from a failure. Dropping it would make the two look alike."""

        row = self._row(intervals, "TPEX", "3202")
        assert row["delisting_date"] == "2025-07-21"
        assert "第15條之11" in (row.get("delisting_reason") or ""), (
            "3202 was terminated under the financial-criteria rule; the "
            "citation is the evidence of why"
        )


class TestSecurityInstanceIdentity:
    """symbol+market is not an identity; the schema must not assume it is."""

    def test_instance_id_changes_when_the_listing_interval_changes(self):
        from build_calendar_lifecycle import build_lifecycle

        records = [
            {
                "market": "TWSE",
                "symbol": "2301",
                "security_name": "first life",
                "listing_date": "1980-01-02",
                "delisting_date": "2010-05-06",
                "evidence_state": "licensed-vendor-snapshot",
                "snapshot_id": "a",
            },
            {
                "market": "TWSE",
                "symbol": "2301",
                "security_name": "reused code",
                "listing_date": "2015-03-04",
                "delisting_date": None,
                "evidence_state": "licensed-vendor-snapshot",
                "snapshot_id": "b",
            },
        ]
        _events, intervals = build_lifecycle(records)
        assert len({r["security_instance_id"] for r in intervals}) == 2

    @pytest.mark.xfail(
        reason=(
            "the TEJ import deduplicates on (market, symbol), which is exactly "
            "the key the PIT contract forbids as an identity, so a reused code "
            "collapses to one instance. Fixing this needs the importer to key "
            "on the listing interval."
        ),
        strict=True,
    )
    def test_reused_codes_survive_the_tej_import(self, intervals):
        counts: dict[tuple[str, str], int] = {}
        for row in intervals:
            key = (row["market"], row["symbol"])
            counts[key] = counts.get(key, 0) + 1
        assert any(count > 1 for count in counts.values()), (
            "no security code carries more than one listing interval"
        )
