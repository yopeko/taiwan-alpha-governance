"""How far back the official daily-price endpoints actually answer.

M3's window starts 2019-01-01 because that is what was captured, not because
the sources stop there. Nobody had checked which.

That matters now for one specific reason. [D25] exempted M0 section 9.1's
walk-forward folds until the development half reaches 1,650 sessions, and the
development half is **bounded at both ends** -- 2019-01-01 and the day before
`SEAL_FROM` -- so it is 1,458 sessions permanently. Time passing lengthens the
sealed half and never the development half. The only way to lift that
exemption is to backfill history before 2019, and whether that is even
possible is this measurement.

WHAT THIS IS NOT

It captures nothing and writes nothing into any warehouse. It asks each
endpoint for one day, records whether an answer came back with rows in it, and
writes a report to an isolated root. Deciding to backfill is a separate
decision that would use `capture_window.py` like every other lane.

WHY TWO DATES A YEAR

One date cannot tell "the source does not reach this year" from "that day was
a holiday". Two mid-month weekdays six months apart can: a year answering with
rows on either date is reachable, a year answering empty on both is either
unreachable or improbably unlucky, and the report says which pattern it saw
rather than collapsing them.

THE INTERVAL IS NOT NEGOTIABLE

Six seconds, the same floor every capture lane uses. A 0.7-second interval
over the six-year backfill got this machine's address refused by twse.com.tw
for more than a day, and a probe is not a reason to spend that again.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_ID = "tw-alpha-m3-history-reach-probe/1.0.0"

# Third Wednesday of March and of October. Chosen for being as far from Lunar
# New Year, Tomb Sweeping, Dragon Boat and Mid-Autumn as the calendar allows,
# and fixed here rather than picked per year so the sample is not chosen after
# seeing which dates answered.
PROBE_MONTHS = (3, 10)
PROBE_WEEKDAY = 2  # Wednesday
PROBE_NTH = 3


def probe_date(year: int, month: int) -> date:
    day = date(year, month, 1)
    while day.weekday() != PROBE_WEEKDAY:
        day += timedelta(days=1)
    return day + timedelta(days=7 * (PROBE_NTH - 1))


def row_count(payload: Any) -> int | None:
    """How many quotation rows came back, or None when the shape is unknown.

    None is not zero. A response this does not recognise is a fact about the
    parser, and reporting it as an empty day would read as "the source does
    not reach this year".
    """

    if payload is None:
        return 0
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return None

    # TWSE MI_INDEX: ten tables, the quotations are the widest one.
    tables = payload.get("tables")
    if isinstance(tables, list):
        best = 0
        for table in tables:
            data = (table or {}).get("data")
            if isinstance(data, list):
                best = max(best, len(data))
        return best
    for key in ("aaData", "data", "tables_data"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    if payload.get("stat") and "OK" not in str(payload.get("stat")):
        # The exchange's own way of saying it has nothing for this request.
        return 0
    return None


def run(years: list[int], interval: float) -> dict[str, Any]:
    from tw_sepa_screener.sources.tpex import TpexClient
    from tw_sepa_screener.sources.twse import TwseClient

    clients = {"TWSE": TwseClient(), "TPEX": TpexClient()}
    attempts: list[dict[str, Any]] = []
    first = True

    for year in sorted(years):
        for month in PROBE_MONTHS:
            when = probe_date(year, month)
            for market, client in clients.items():
                if not first:
                    time.sleep(interval)
                first = False
                record: dict[str, Any] = {
                    "market": market,
                    "probe_date": when.isoformat(),
                    "year": year,
                    "asked_at": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    payload = client.get_market_day_payload(when)
                    count = row_count(payload)
                    record["rows"] = count
                    record["outcome"] = (
                        "unrecognised-shape"
                        if count is None
                        else ("data" if count > 0 else "empty")
                    )
                except Exception as exc:  # noqa: BLE001
                    # Recorded, not raised. A transport failure on one date is
                    # not evidence about the year, and stopping here would
                    # leave the rest of the sample unmeasured.
                    record["outcome"] = "error"
                    record["error"] = f"{type(exc).__name__}: {exc}"[:300]
                print(
                    f"  {record['probe_date']}  {market:5s} "
                    f"{record['outcome']:19s} rows={record.get('rows')}",
                    flush=True,
                )
                attempts.append(record)

    verdict: dict[str, Any] = {}
    for market in clients:
        for year in sorted(years):
            got = [
                a
                for a in attempts
                if a["market"] == market and a["year"] == year
            ]
            outcomes = {a["outcome"] for a in got}
            verdict[f"{market}:{year}"] = (
                "reachable"
                if "data" in outcomes
                else "error" if outcomes == {"error"}
                else "no-data-on-either-probe"
                if outcomes <= {"empty", "error"}
                else "inconclusive"
            )

    earliest: dict[str, Any] = {}
    for market in clients:
        reachable = sorted(
            int(k.split(":")[1])
            for k, v in verdict.items()
            if k.startswith(f"{market}:") and v == "reachable"
        )
        earliest[market] = reachable[0] if reachable else None

    return {
        "schema_id": SCHEMA_ID,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "interval_seconds": interval,
        "probe_dates": "third Wednesday of March and of October, fixed in advance",
        "requests": len(attempts),
        "attempts": attempts,
        "verdict_by_market_year": dict(sorted(verdict.items())),
        "earliest_year_with_data": earliest,
        "reading_note": (
            "`no-data-on-either-probe` is not proof a year is unreachable -- "
            "two holidays would look the same -- but two mid-month Wednesdays "
            "six months apart make that unlikely. `unrecognised-shape` is a "
            "fact about this parser, not about the source, and is never "
            "counted as an empty year."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, required=True)
    parser.add_argument("--to-year", type=int, required=True)
    parser.add_argument(
        "--interval",
        type=float,
        default=6.0,
        help="seconds between requests. The 6s floor exists because 0.7 "
        "got this address refused for over a day",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.interval < 6.0:
        raise SystemExit(
            f"--interval {args.interval} is below the 6s floor every capture "
            f"lane uses. A probe is not a reason to spend that again"
        )
    # Resolved first. The unresolved form silently passed for a relative
    # path -- `Path("probe.json").is_relative_to("C:/...")` is False -- and
    # the first run of this script wrote into the repository while the guard
    # said nothing. A guard that cannot fire is worse than no guard, because
    # it is read as coverage.
    args.out = args.out.resolve()
    if args.out.is_relative_to(Path(__file__).resolve().parents[2]):
        raise SystemExit(
            f"{args.out} is inside the repository. Probe output goes to an "
            f"isolated root, same as every capture"
        )

    years = list(range(args.from_year, args.to_year + 1))
    print(f"probing {len(years)} years x 2 dates x 2 markets at {args.interval}s")
    report = run(years, args.interval)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print()
    print(json.dumps(report["earliest_year_with_data"], ensure_ascii=False))
    print(f"寫入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
