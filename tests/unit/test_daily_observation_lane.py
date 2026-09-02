"""The M9 daily lane: one capture root through the same builders.

Added with D22. The lane exists because the observation and the reconstruction
were reading the same `PRICES` root, so divergence could only ever come from
the warehouse having been rebuilt -- never from "the day showed something the
warehouse does not say", which is the one thing the shadow observation
contract section 1 measures.

`build_staging.py` could only build everything, which is 79.8 minutes. The
`--archive` override makes one day 9 seconds. These tests watch the two things
that override could quietly break: the default, and the protection it opens a
path around.
"""

from __future__ import annotations

import inspect
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))

LANE = REPO / "scripts" / "m9" / "daily_observation.cmd"


def staging():
    """`build_staging` imports `tw_sepa_screener`, which exists only on the
    operator's machine.

    Imported here rather than at module scope, and this is why: the module
    scope version passed locally and broke CI's collection on the first push
    after it was written -- the whole suite failed in 22 seconds. The lane
    script tests below need none of that, so they keep running everywhere.
    """

    try:
        import build_staging
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"build_staging needs an operator-only module: {exc}")
    return build_staging


class TestTheOverrideDoesNotChangeTheDefault:
    """A full rebuild must stay a full rebuild. The override is for one lane."""

    def test_build_still_defaults_to_every_archive(self):
        import inspect

        sig = inspect.signature(staging().build)
        assert sig.parameters["archives"].default is None, (
            "the default must be None, which build() resolves to ARCHIVES. A "
            "default of anything else would silently narrow every rebuild"
        )

    def test_the_archive_list_is_still_the_full_set(self):
        """If an entry is ever dropped from ARCHIVES the six-year rebuild gets
        quietly smaller, and the row count is the only thing that would say
        so -- after the fact."""

        names = {a.name for a in staging().ARCHIVES}
        for expected in (
            "m2_2026-08-03",
            "m3_window_2025-01-01_2026-08-03",
            "m3_window_2019-01-01_2024-12-31",
            "m3_tpex_actions_2019-2023",
        ):
            assert expected in names


class TestAPassedArchiveIsStillProtected:
    """The hole the override would otherwise have opened.

    `assert_publishable` refuses to write a staging root into an archive. It
    knew about `ARCHIVES` only, so a root passed on the command line would
    have been unprotected -- and publishing staging inside the evidence being
    read is precisely what the function exists to stop.
    """

    def test_publishing_inside_a_passed_archive_is_refused(self, tmp_path):
        archive = tmp_path / "daily-raw"
        archive.mkdir()
        with pytest.raises(staging().StagingError) as caught:
            staging().assert_publishable(
                archive / "staging", extra_protected=(archive,)
            )
        assert "protected" in str(caught.value)

    def test_publishing_onto_a_passed_archive_is_refused(self, tmp_path):
        archive = tmp_path / "daily-raw"
        archive.mkdir()
        with pytest.raises(staging().StagingError):
            staging().assert_publishable(archive, extra_protected=(archive,))

    def test_a_parent_of_a_passed_archive_is_refused(self, tmp_path):
        archive = tmp_path / "lane" / "daily-raw"
        archive.mkdir(parents=True)
        with pytest.raises(staging().StagingError):
            staging().assert_publishable(
                tmp_path / "lane", extra_protected=(archive,)
            )

    def test_an_unrelated_empty_directory_is_still_allowed(self, tmp_path):
        archive = tmp_path / "daily-raw"
        archive.mkdir()
        target = tmp_path / "staging"
        assert staging().assert_publishable(
            target, extra_protected=(archive,)
        ) == target.resolve()


class TestTheLaneScriptSaysWhatItMustNotDo:
    def test_the_lane_exists(self):
        assert LANE.is_file()

    def test_the_lane_never_passes_the_backfill_escape_hatch(self):
        """`--backfill-unusable` marks a file as not countable. A scheduled
        lane that passed it would fill the ledger with reconstructions and
        reach 60 without observing anything.

        Checked on the commands only. The script's comments name the flag
        deliberately, to say why it is absent -- a first version of this test
        matched the explanation and failed, which is the difference between
        looking for a string and looking for the thing.
        """

        commands = [
            line
            for line in LANE.read_text(encoding="utf-8").splitlines()
            if not line.strip().upper().startswith("REM")
        ]
        assert not [c for c in commands if "--backfill-unusable" in c]

    def test_the_lane_records_failures_rather_than_swallowing_them(self):
        """Contract section 4: a capture failure does not count towards the
        60. A lane that failed silently would reach 60 on fewer days than it
        claims, and nothing would say which."""

        text = LANE.read_text(encoding="utf-8")
        assert "failures.log" in text
        assert "exit /b 1" in text


def prices_builder():
    """`build_prices_actions` reaches Taiwan Core the same way `build_staging`
    does, so it skips where that package is absent."""

    try:
        import build_prices_actions
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"build_prices_actions needs an operator-only module: {exc}")
    return build_prices_actions


SOURCE = (REPO / "scripts" / "m3" / "build_prices_actions.py").read_text(
    encoding="utf-8"
)


class TestTheWindowEndIsNoLongerOnlyAConstant:
    """The defect this override was added for.

    `WINDOW`'s end was a date that was current when it was written. On
    2026-09-02 a capture of the following month produced 43,603 staging rows
    and **zero** price rows, because every session past 2026-08-03 was skipped
    -- with no error, no warning, and no count.
    """

    def test_the_constant_still_ends_where_the_six_year_build_did(self):
        """The override must not have moved the default. A rebuild without it
        has to produce the same table it produced before."""

        assert "WINDOW = (date(2019, 1, 1), date(2026, 8, 3))" in SOURCE

    def test_build_prices_takes_an_end_and_defaults_to_none(self):
        import inspect

        sig = inspect.signature(prices_builder().build_prices)
        assert sig.parameters["window_end"].default is None

    def test_build_takes_the_same_override(self):
        import inspect

        sig = inspect.signature(prices_builder().build)
        assert sig.parameters["window_end"].default is None

    def test_a_dropped_session_is_counted_not_only_skipped(self):
        """A decision that leaves no number behind is how 43,603 rows became 0
        without anything saying so."""

        assert "outside_window += 1" in SOURCE
        assert '"sessions_outside_window": outside_window,' in SOURCE

    def test_the_manifest_records_the_window_that_applied(self):
        """A run with an override must not read as a run without one."""

        assert '"end": (window_end or WINDOW[1]).isoformat(),' in SOURCE


CALENDAR_SOURCE = (REPO / "scripts" / "m3" / "build_calendar_lifecycle.py").read_text(
    encoding="utf-8"
)
STATUS_SOURCE = (REPO / "scripts" / "m3" / "build_status_fundamentals.py").read_text(
    encoding="utf-8"
)


class TestTheSameConstantInTheOtherTwoBuilders:
    """One defect, three builders, found one at a time.

    `build_prices_actions` was fixed first, on the evidence of 43,603 staging
    rows becoming zero price rows. The same hardcoded end was then in
    `build_calendar_lifecycle` and `build_status_fundamentals`, and neither
    would have announced itself either.
    """

    def test_the_calendar_constant_still_ends_where_the_six_year_build_did(self):
        assert "WINDOW_END = date(2026, 8, 3)" in CALENDAR_SOURCE

    def test_the_status_constant_still_ends_where_the_six_year_build_did(self):
        assert "WINDOW = (date(2019, 1, 1), date(2026, 8, 3))" in STATUS_SOURCE

    def test_the_calendar_stops_generating_at_the_override(self):
        """The calendar bounds what the as-of interface can be asked about, so
        a stale end here caps `tradability_state` at the same date."""

        import build_calendar_lifecycle

        assert "last = window_end or WINDOW_END" in CALENDAR_SOURCE
        assert "while cursor <= last:" in CALENDAR_SOURCE
        sig = inspect.signature(build_calendar_lifecycle.build_calendar)
        assert sig.parameters["window_end"].default is None

    def test_a_still_current_listing_is_in_window_only_under_the_override(self):
        """The one behavioural check available without the licensed lanes.

        A leg that opened on 2026-08-20 and has not closed is current. Against
        the constant's own end it reads as starting after the window and is
        dropped -- which is how a newly listed security would go missing.
        """

        import build_calendar_lifecycle as c

        assert c.overlaps_window("2026-08-20", "", None) is False
        assert c.overlaps_window("2026-08-20", "", date(2026, 9, 2)) is True

    def test_the_status_end_closes_open_intervals_rather_than_filtering(self):
        """This one is not the same failure as the other two.

        A stale end in the price and calendar builders drops rows: the answer
        is missing and a consumer can see that it is missing. Here the end is
        what an **unlifted** designation runs to, so a stale value expires it.
        Measured 2026-09-02: the previous generation had zero securities under
        any restriction that day; rebuilt with the override, 31 full-cash-
        delivery, 24 disposal and one capital-reduction. Thirty-one names that
        cannot be bought on ordinary settlement read as freely tradable.
        """

        import build_status_fundamentals

        assert (
            '"effective_to": end or (window_end or WINDOW[1]).isoformat(),'
            in STATUS_SOURCE
        )
        sig = inspect.signature(build_status_fundamentals.build_full_cash_delivery)
        assert sig.parameters["window_end"].default is None

    def test_both_manifests_record_the_window_that_applied(self):
        """A run with an override must not read as a run without one."""

        assert '"end": (window_end or WINDOW_END).isoformat(),' in CALENDAR_SOURCE
        assert (
            '"effective_to": end or (window_end or WINDOW[1]).isoformat(),'
            in STATUS_SOURCE
        )

    def test_both_expose_the_override_on_the_command_line(self):
        for source in (CALENDAR_SOURCE, STATUS_SOURCE):
            assert '"--window-end",' in source
            assert "type=date.fromisoformat," in source
