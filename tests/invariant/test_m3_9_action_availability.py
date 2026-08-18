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

PIT = Path(r"C:\tmp\tw-alpha-m3-actions-avail")
WINDOW = ("2025-01-01", "2026-08-03")


def table():
    path = PIT / "corporate_actions_pit.parquet"
    if not path.is_file():
        pytest.skip("action availability table not built on this machine")
    pq = pytest.importorskip("pyarrow.parquet")
    return pq.read_table(path)


@pytest.fixture(scope="module")
def actions():
    return table()


class TestOfficialEventSetIsPreserved:
    def test_every_official_event_survives_the_join(self, actions):
        assert actions.num_rows == 2388, (
            "the official event count changed, which means the vendor join "
            "added or removed events instead of only adding a date"
        )

    def test_events_without_a_vendor_row_are_kept_not_dropped(self, actions):
        basis = actions["availability_basis"].to_pylist()
        assert basis.count("first-observed-only") == 109, (
            "the 109 events TEJ does not carry must remain in the table, "
            "marked unusable rather than deleted"
        )

    def test_the_subject_is_the_official_record(self, actions):
        assert set(actions["source_id"].to_pylist()) == {"TWSE-ACTIONS-HIST"}
        assert all(actions["official_limit_up"].to_pylist())


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
        leads = [
            lead
            for lead, b in zip(
                actions["lead_days"].to_pylist(),
                actions["availability_basis"].to_pylist(),
                strict=True,
            )
            if b == "publisher-exact"
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
