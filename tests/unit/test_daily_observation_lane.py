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

import sys
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
