"""D13: the daily snapshot has to be safe to run, and to re-run.

Six of the eight trading-status sources are current-state. They say what is
true today and keep no history, so a suspension or a change of trading method
is observable only if somebody captured that day. Nothing recovers a day that
was missed: 1589 永冠-KY was suspended in April 2026 and no official source
can now say when.

That makes the daily run infrastructure, and it has two properties worth
holding still. It must not ask an exchange twice for something already held,
or a scheduled job that fires on retry becomes a scraper. And a source that
failed must stay retryable without disturbing the ones that succeeded.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))

capture = pytest.importorskip("capture_trading_status")


def observation(root: Path, source_id: str, period: str, status: str) -> None:
    folder = root / "raw_observations" / source_id / period.replace(":", "_")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "source_id": source_id,
                "logical_period": period,
                "capture_status": status,
            }
        ),
        encoding="utf-8",
    )


class TestAlreadyCaptured:
    def test_an_empty_root_holds_nothing(self, tmp_path):
        assert capture.already_captured(tmp_path) == set()

    def test_a_verified_observation_is_held(self, tmp_path):
        observation(tmp_path, "TWSE-DELISTING", "snapshot:2026-08-22", "hash-verified")
        assert capture.already_captured(tmp_path) == {
            ("TWSE-DELISTING", "snapshot:2026-08-22")
        }

    def test_an_unverified_observation_is_not_held(self, tmp_path):
        """A half-written capture must be retried, not counted as done."""

        observation(tmp_path, "TWSE-DELISTING", "snapshot:2026-08-22", "transport-error")
        assert capture.already_captured(tmp_path) == set()

    def test_each_day_is_held_separately(self, tmp_path):
        """Yesterday's snapshot must not satisfy today's.

        The whole point is one observation per day; a key that ignored the
        day would capture once and then report itself complete forever.
        """

        for day in ("2026-08-20", "2026-08-21", "2026-08-22"):
            observation(tmp_path, "TPEX-TRADING-ALTERED-TRADING", f"snapshot:{day}", "hash-verified")
        held = capture.already_captured(tmp_path)
        assert len(held) == 3
        assert ("TPEX-TRADING-ALTERED-TRADING", "snapshot:2026-08-23") not in held

    def test_one_failed_source_leaves_the_others_held(self, tmp_path):
        period = "snapshot:2026-08-22"
        observation(tmp_path, "TWSE-DELISTING", period, "hash-verified")
        observation(tmp_path, "TPEX-DELISTING-HIST", period, "transport-error")
        held = capture.already_captured(tmp_path)
        assert ("TWSE-DELISTING", period) in held
        assert ("TPEX-DELISTING-HIST", period) not in held

    def test_unreadable_manifest_does_not_stop_the_scan(self, tmp_path):
        """One corrupt file must not make the run believe it holds nothing."""

        observation(tmp_path, "TWSE-DELISTING", "snapshot:2026-08-22", "hash-verified")
        broken = tmp_path / "raw_observations" / "broken" / "x"
        broken.mkdir(parents=True)
        (broken / "manifest.json").write_text("{not json", encoding="utf-8")
        assert ("TWSE-DELISTING", "snapshot:2026-08-22") in capture.already_captured(tmp_path)


class TestTheSourceListStaysHonest:
    def test_every_source_names_an_allowlisted_id_and_url(self):
        for spec in capture.SOURCES:
            assert spec["source_id"]
            assert str(spec["url"]).startswith("https://")

    def test_the_daily_material_feeds_are_present(self):
        """They are the only forward answer to a TWSE suspension.

        TWSE publishes no dated list of long-term suspensions and MOPS, where
        the company's own announcement lives, refuses programmatic access at
        the WAF. Dropping these two would leave the gap permanently open
        rather than merely open for the past.
        """

        ids = {spec["source_id"] for spec in capture.SOURCES}
        assert "TWSE-MATERIAL-ANNOUNCEMENT-DAILY" in ids
        assert "TPEX-MATERIAL-ANNOUNCEMENT-DAILY" in ids

    def test_no_source_is_listed_twice(self):
        ids = [spec["source_id"] for spec in capture.SOURCES]
        assert len(ids) == len(set(ids))
