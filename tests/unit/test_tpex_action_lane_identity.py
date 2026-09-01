"""Two things the TPEx action lane got wrong, and what now holds them right.

Both surfaced finishing the 2019-2023 backfill, and both are the same shape:
something that describes the lane was allowed to be overwritten or to be
ambiguous, while the thing it described was fine.

1. The detail key was `(symbol, announced_date)`. Eighteen periods in the new
   lane and nine in the archived one carry two different payloads under one
   name. No bytes were lost -- the store is content-addressed -- but the name
   does not identify the record, and the announced date parsed out of that
   name becomes `announced_at`, which decides point-in-time visibility.

2. The manifest was written from the counters of whichever process wrote it
   last. A resume that found everything already captured overwrote a finished
   capture's totals with its own zeroes. The ledger was made append-only for
   precisely this reason; the manifest was not.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
sys.path.insert(0, str(REPO / "scripts" / "m3"))


def load(name: str):
    """Load a capture script by path.

    Skips where the module reaches Taiwan Core. Some of these scripts import
    `tw_sepa_screener` transitively -- `capture_tpex_actions` pulls in
    `capture_window`, which imports `m2_daily_price_pilot` -- and that package
    is installed only on the operator's machine. Without this guard the three
    ledger-summary tests error on any runner, which is what they did on the
    first two CI runs this repository ever had.

    The tests that need no capture script keep running everywhere; that is why
    the guard is here rather than on the module.
    """

    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "m3" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:  # noqa: PERF203
        if exc.name and exc.name.split(".")[0] == "tw_sepa_screener":
            pytest.skip(f"{name} needs the Taiwan Core package: {exc}")
        raise
    return module


def detail_period(symbol: str, announced: str, date1: str, seq: str) -> str:
    """The key the capture now builds, kept in one place for these tests."""

    return f"company:TPEX:{symbol}:announced:{announced}:src:{date1}-{seq}"


class TestDetailPeriodIdentity:
    # The real collisions, taken from the lane. Two announcements on one day,
    # and two records whose different DATE1 parse to one announced date.
    COLLISIONS = [
        ("3709", "2021-07-09", [("20210707", "1"), ("20210707", "2")]),
        ("4905", "2019-07-08", [("20190708", "1"), ("20190704", "1")]),
        ("5386", "2019-01-25", [("20190125", "1"), ("20190124", "1")]),
    ]

    @pytest.mark.parametrize("symbol,announced,records", COLLISIONS)
    def test_records_that_used_to_collide_now_have_distinct_keys(
        self, symbol, announced, records
    ):
        old = {f"company:TPEX:{symbol}:announced:{announced}" for _ in records}
        assert len(old) == 1, "these records shared one key before the fix"

        new = {detail_period(symbol, announced, d, s) for d, s in records}
        assert len(new) == len(records), (
            f"{symbol} {announced}: still collide under the new key"
        )

    def test_seq_alone_would_not_have_been_enough(self):
        """Six of the eighteen differ only by DATE1, so both parts are needed."""

        symbol, announced, records = self.COLLISIONS[1]
        seq_only = {f"{symbol}:{announced}:{s}" for _, s in records}
        assert len(seq_only) == 1, "this pair shares SEQ_NO; DATE1 is what differs"


@pytest.fixture(scope="module")
def pattern() -> re.Pattern:
    return load("build_prices_actions").TPEX_DETAIL_PERIOD


@pytest.fixture(scope="module")
def summarise():
    return load("capture_tpex_actions").lane_summary


class TestDownstreamStillParsesBothKeyShapes:
    """The archived lanes must not stop parsing because the key grew."""

    def test_the_older_coarser_key_still_matches(self, pattern):
        m = pattern.fullmatch("company:TPEX:4129:announced:2021-08-19")
        assert m is not None, "the two archived lanes would go unread"
        assert m.group("symbol") == "4129"
        assert m.group("announced") == "2021-08-19"

    def test_the_new_key_matches_and_keeps_the_announced_date(self, pattern):
        m = pattern.fullmatch(detail_period("4129", "2021-08-19", "20210817", "2"))
        assert m is not None
        # `announced_at` is read from this group and decides as-of
        # visibility, so the suffix must not disturb it.
        assert m.group("announced") == "2021-08-19"
        assert m.group("src") == "20210817-2"

    def test_a_foreign_key_shape_is_still_rejected(self, pattern):
        assert pattern.fullmatch("company:TWSE:4129:announced:2021-08-19") is None
        assert pattern.fullmatch("company:TPEX:4129:year:110") is None


class TestLaneSummaryFromLedger:
    def write(self, tmp_path: Path, records: list[dict]) -> Path:
        path = tmp_path / "ledger.jsonl"
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )
        return path

    def test_a_resume_that_did_nothing_cannot_erase_the_totals(
        self, summarise, tmp_path
    ):
        """This is what happened: attempt 2 reported zero announcements."""

        real = [
            {"symbol": "1240", "roc_year": 108, "outcome": "captured", "announcements": 3},
            {"symbol": "1240", "roc_year": 109, "outcome": "official-no-announcements"},
        ]
        resume = [
            {"symbol": "1240", "roc_year": 108, "outcome": "already-captured"},
            {"symbol": "1240", "roc_year": 109, "outcome": "already-captured"},
        ]
        after = summarise(self.write(tmp_path, real + resume))
        assert after["total_announcements"] == 3
        assert after["symbol_years_captured"] == 2
        assert after["outcome_counts"] == {
            "captured": 1,
            "official-no-announcements": 1,
        }
        assert after["resume_skips"] == 2

    def test_the_summary_does_not_change_when_a_resume_is_appended(
        self, summarise, tmp_path
    ):
        real = [
            {"symbol": "1240", "roc_year": 108, "outcome": "captured", "announcements": 2},
        ]
        before = summarise(self.write(tmp_path, real))
        appended = real + [
            {"symbol": "1240", "roc_year": 108, "outcome": "already-captured"}
        ]
        after = summarise(self.write(tmp_path, appended))
        for field in ("symbol_years_captured", "outcome_counts", "total_announcements"):
            assert before[field] == after[field], f"{field} moved on a no-op resume"

    def test_a_symbol_year_is_counted_by_its_first_real_outcome(
        self, summarise, tmp_path
    ):
        """A later retry must not reclassify what the lane already holds."""

        path = self.write(
            tmp_path,
            [
                {"symbol": "1240", "roc_year": 108, "outcome": "captured", "announcements": 1},
                {"symbol": "1240", "roc_year": 108, "outcome": "already-captured"},
                {"symbol": "1240", "roc_year": 108, "outcome": "captured", "announcements": 9},
            ],
        )
        summary = summarise(path)
        assert summary["symbol_years_captured"] == 1
        assert summary["total_announcements"] == 1
