"""M3.9: corporate actions become knowable, without TEJ redefining the event set.

Two failure modes are guarded here, and they pull in opposite directions.

Letting the vendor define which events exist would silently delete the 109
official events TEJ does not carry. Letting the vendor's date through
unchecked would let an action that was announced too late inform a decision
that could not have known about it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# These now guard the canonical table rather than the one-off audit that
# derived the join. An invariant protecting a table nobody reads protects
# nothing, and there is no longer a second `corporate_actions_pit`.
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

from warehouse import PRICES, WINDOW, load_table  # noqa: E402

# Every test in this module reads the operator's warehouse or archives, so all
# of them skip on a machine without them -- and on a machine with them, they
# are where the suite's 25 minutes go. The marker was declared in
# tests/conftest.py on 2026-08-17 and nothing used it until 2026-09-01.
#
# `pytest -m "not needs_local_data"` is the lane the pre-commit hook runs. A
# hook slow enough to be bypassed is a hook that gets bypassed, and the value
# of these checks is zero on the commits where someone passes --no-verify.
pytestmark = pytest.mark.needs_local_data

OFFICIAL_SOURCE = "TWSE-ACTIONS-HIST"


def table(request):
    full = load_table(request, PRICES, "corporate_actions_pit.parquet")
    # Scoped to the rows TWT49U produced, because those are the ones the
    # vendor join touches. TPEx and the halt events reach the table with
    # their own publishers' dates and are guarded elsewhere.
    keep = [
        i
        for i, source in enumerate(full["source_id"].to_pylist())
        if source == OFFICIAL_SOURCE
    ]
    return full.take(keep)


@pytest.fixture(scope="module")
def actions(request):
    return table(request)


class TestOfficialEventSetIsPreserved:
    def test_every_official_event_survives_the_join(self, actions):
        """The join adds a date. It must not add, drop or merge an event.

        This asserted `== 1665`, the count on the day it was written. A frozen
        count does notice a change, but it cannot say the join caused one, and
        it fires on a legitimate window change in exactly the same voice as on
        a defect -- which is how it came to be read as noise.

        Two properties say the same thing without a literal: every event landed
        in exactly one availability bucket, and no natural key appears twice.
        An event dropped by the join leaves no bucket; one duplicated by it
        collides on the key.
        """

        assert actions.num_rows > 0
        basis = actions["availability_basis"].to_pylist()
        buckets = set(basis)
        assert buckets <= {"publisher-exact", "first-observed-only", "unknown-blocked"}, (
            f"events in an unlabelled availability state: {buckets}"
        )
        assert len(basis) == actions.num_rows

        keys = list(
            zip(
                actions["market"].to_pylist(),
                actions["symbol"].to_pylist(),
                actions["effective_date"].to_pylist(),
                actions["revision_ordinal"].to_pylist(),
                strict=True,
            )
        )
        assert len(set(keys)) == len(keys), (
            "the join duplicated events: a (market, symbol, effective_date, "
            "revision_ordinal) appears more than once"
        )

    def test_events_without_a_vendor_row_are_kept_not_dropped(self, actions):
        """Kept and labelled unusable, never deleted.

        Also a frozen count once (`== 103`), which tested how many rather than
        whether. Over the six-year window it is 5,292 of 6,854 -- the vendor's
        announcement lane barely reaches back before 2024 -- and the number
        moving is not what this test is about.
        """

        basis = actions["availability_basis"].to_pylist()
        unusable = [i for i, b in enumerate(basis) if b == "first-observed-only"]
        assert unusable, (
            "no event lacks a vendor announcement date, which would mean the "
            "join silently discarded the ones TEJ does not carry"
        )
        evidence = actions["evidence_state"].to_pylist()
        reference = actions["reference_price"].to_pylist()
        for i in unusable:
            assert evidence[i] == "verified-snapshot", (
                "an event the vendor could not date is still the exchange's "
                "own record and keeps its evidence state"
            )
            assert reference[i], "a kept event must keep its official fields"

    def test_the_subject_is_the_official_record(self, actions):
        assert set(actions["source_id"].to_pylist()) == {OFFICIAL_SOURCE}
        assert all(actions["reference_price"].to_pylist())


class TestAnnouncementSoundness:
    def test_an_announcement_never_follows_the_effect(self, actions):
        announced = actions["announced_at"].to_pylist()
        effective = actions["effective_date"].to_pylist()
        basis = actions["availability_basis"].to_pylist()
        wrong = [
            i
            for i, value in enumerate(announced)
            if value and basis[i] == "publisher-exact" and value >= effective[i]
        ]
        assert not wrong, (
            f"{len(wrong)} actions claim advance knowledge while being "
            "announced on or after the day they took effect"
        )

    def test_late_announcements_are_blocked_rather_than_used(self, actions):
        announced = actions["announced_at"].to_pylist()
        effective = actions["effective_date"].to_pylist()
        basis = actions["availability_basis"].to_pylist()
        for i, value in enumerate(announced):
            if value and value >= effective[i]:
                assert basis[i] == "unknown-blocked"

    def test_usable_rows_all_carry_a_date(self, actions):
        announced = actions["announced_at"].to_pylist()
        basis = actions["availability_basis"].to_pylist()
        missing = [
            i for i, b in enumerate(basis) if b == "publisher-exact" and not announced[i]
        ]
        assert not missing

    def test_lead_time_is_positive_for_every_usable_row(self, actions):
        """Derived here rather than stored, so a stored value cannot drift.

        A usable row must have been announced strictly before it took effect;
        a lead of zero means the market learned of it on the day.
        """

        from datetime import date

        leads = [
            (
                date.fromisoformat(effective) - date.fromisoformat(announced)
            ).days
            for announced, effective, basis in zip(
                actions["announced_at"].to_pylist(),
                actions["effective_date"].to_pylist(),
                actions["availability_basis"].to_pylist(),
                strict=True,
            )
            if basis == "publisher-exact"
        ]
        assert leads
        assert min(leads) >= 1


class TestVendorEvidenceKeepsItsLabel:
    def test_announcement_dates_are_labelled_licensed_vendor(self, actions):
        states = actions["announcement_evidence_state"].to_pylist()
        announced = actions["announced_at"].to_pylist()
        for i, value in enumerate(announced):
            expected = "licensed-vendor-snapshot" if value else "missing-at-source"
            assert states[i] == expected

    def test_the_action_itself_stays_official_evidence(self, actions):
        assert set(actions["evidence_state"].to_pylist()) == {"verified-snapshot"}


class TestAsOfVisibility:
    """The point of the exercise: actions must become visible at a cutoff."""

    def _visible(self, actions, cutoff: str) -> int:
        return sum(
            1
            for announced, basis, effective in zip(
                actions["announced_at"].to_pylist(),
                actions["availability_basis"].to_pylist(),
                actions["effective_date"].to_pylist(),
                strict=True,
            )
            if basis == "publisher-exact"
            and announced
            and announced <= cutoff
            and WINDOW[0] <= effective <= WINDOW[1]
        )

    def test_actions_are_visible_at_a_mid_window_cutoff(self, actions):
        assert self._visible(actions, "2025-06-30") > 0, (
            "before this import the answer was zero at every cutoff"
        )

    def test_visibility_grows_with_the_cutoff(self, actions):
        early = self._visible(actions, "2025-06-30")
        middle = self._visible(actions, "2025-12-31")
        late = self._visible(actions, WINDOW[1])
        assert early < middle < late

    def test_announcements_can_predate_the_window(self, actions):
        """An action effective in January may have been announced in November.

        The longest observed lead is 168 days, so a cutoff before the window
        opens legitimately sees some of it. This is knowability reaching
        backwards, not the future leaking forwards: every such row is still
        announced before the cutoff and effective inside the window.
        """

        early = self._visible(actions, "2024-12-31")
        assert early > 0
        for announced, basis, effective in zip(
            actions["announced_at"].to_pylist(),
            actions["availability_basis"].to_pylist(),
            actions["effective_date"].to_pylist(),
            strict=True,
        ):
            if basis != "publisher-exact" or not announced:
                continue
            if announced <= "2024-12-31":
                assert effective >= WINDOW[0]
                assert announced < effective
