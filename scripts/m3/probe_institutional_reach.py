"""Can the exchanges' institutional net-buy reports become an M3 lane?

A strategy phrased as "投信買超前幾名" needs one number per security per
session: how much each institution class bought net that day. Both exchanges
publish it, it is official rather than vendor, and nothing in this warehouse
captures it.

Before spending three hours on a backfill, three questions -- the same three
the daily-price history probe asked, because they are the ones that decide
whether a lane is possible rather than merely desirable.

ONE. HOW FAR BACK DOES IT ANSWER

M3's window starts in 2019 because that is what was captured. Whether these
reports reach further is a separate fact and nobody has checked it.

TWO. DOES A DELISTED SECURITY APPEAR

The whole point of this warehouse's lifecycle lane is that a company which
stopped trading still has to be in the history, or every backtest silently
excludes the ones that failed. 3202 traded 57 sessions inside the window and
then delisted, and it is the security that exposed that defect the first
time, so it is the one to ask about.

**A report that only lists what still trades would put survivorship straight
back in**, and it would do it in a field that looks like a signal.

THREE. IS THE SHAPE THE SAME ACROSS THE YEARS

The daily-price probe found TPEx responses from before 2010 whose row counts
could not be security counts -- an older layout that the current parser reads
as something else. A lane built on one year's shape and run over eight is how
that becomes silent.

WHAT THIS DOES NOT DO

It captures nothing, writes into no warehouse, and settles no question about
what the numbers mean. Whether 自營商 net buying is a directional view or a
hedge is a question about the market, not about whether the file exists.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_ID = "tw-alpha-m3-institutional-reach-probe/1.0.0"

# Candidate endpoints. Written as candidates on purpose: this project has no
# registered source for these reports, so part of the probe is finding out
# which address answers. A refusal is recorded, not retried in another shape.
TWSE_T86 = (
    "https://www.twse.com.tw/rwd/zh/fund/T86"
    "?date={ymd}&selectType=ALL&response=json"
)
TPEX_CANDIDATES = (
    (
        "tpex-openapi-daily",
        "https://www.tpex.org.tw/openapi/v1/tpex_3itrade_hedge_daily",
    ),
    (
        "tpex-rwd-dated",
        "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
        "?type=Daily&sect=EW&date={roc_slash}&id=&response=json",
    ),
)

# Same rule as the price-history probe: the third Wednesday of March and of
# October, fixed here rather than chosen per year, so the sample cannot have
# been picked after seeing which dates answered.
PROBE_MONTHS = (3, 10)
PROBE_WEEKDAY = 2
PROBE_NTH = 3

# 3202 樺晟, listed until 2025-04-02.
DELISTED_CASE = "3202"
DELISTED_LISTED_UNTIL = "2025-04-02"

INTERVAL_SECONDS = 6.0


def probe_date(year: int, month: int) -> date:
    day = date(year, month, 1)
    while day.weekday() != PROBE_WEEKDAY:
        day += timedelta(days=1)
    return day + timedelta(days=7 * (PROBE_NTH - 1))


def get(url: str, timeout: int = 60) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            raw = response.read()
            try:
                return {"http": response.status, "body": json.loads(raw)}
            except json.JSONDecodeError:
                return {
                    "http": response.status,
                    "not_json": raw[:200].decode("utf-8", "replace"),
                }
    except urllib.error.HTTPError as error:
        return {"http": error.code, "text": error.read()[:250].decode("utf-8", "replace")}
    except Exception as exc:  # noqa: BLE001
        return {"http": None, "error": f"{type(exc).__name__}: {exc}"[:250]}


def read_twse(answer: dict[str, Any], want_symbol: str | None) -> dict[str, Any]:
    body = answer.get("body")
    if not isinstance(body, dict):
        return {
            "http": answer.get("http"),
            "outcome": "refused" if answer.get("http") else "error",
            "detail": (answer.get("text") or answer.get("error") or answer.get("not_json") or "")[:200],
        }
    stat = str(body.get("stat") or "")
    rows = body.get("data") or []
    out: dict[str, Any] = {
        "http": answer.get("http"),
        "stat": stat[:120],
        "rows": len(rows),
        "outcome": "data" if rows else "empty",
    }
    if rows:
        out["fields"] = body.get("fields") or []
        out["first"] = rows[0]
        if want_symbol is not None:
            hit = [r for r in rows if r and str(r[0]).strip() == want_symbol]
            out["delisted_case_present"] = bool(hit)
            if hit:
                out["delisted_case_row"] = hit[0]
    return out


def run(years: list[int], interval: float) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    first = True

    def pause() -> None:
        nonlocal first
        if not first:
            time.sleep(interval)
        first = False

    for year in sorted(years):
        for month in PROBE_MONTHS:
            when = probe_date(year, month)
            pause()
            # Ask about the delisted security only on sessions inside its
            # listed period; outside it, absence is correct and would read as
            # a coverage gap.
            want = (
                DELISTED_CASE
                if "2019-01-01" <= when.isoformat() <= DELISTED_LISTED_UNTIL
                else None
            )
            record = read_twse(
                get(TWSE_T86.format(ymd=when.strftime("%Y%m%d"))), want
            )
            record.update(
                {"market": "TWSE", "probe_date": when.isoformat(), "year": year}
            )
            note = ""
            if "delisted_case_present" in record:
                note = f"  3202={'有' if record['delisted_case_present'] else '無'}"
            print(
                f"  {when} TWSE  {record['outcome']:8s} rows={record.get('rows')}{note}",
                flush=True,
            )
            attempts.append(record)

    tpex: list[dict[str, Any]] = []
    probe = probe_date(max(years), PROBE_MONTHS[0])
    roc = f"{probe.year - 1911}/{probe.month:02d}/{probe.day:02d}"
    for label, template in TPEX_CANDIDATES:
        pause()
        answer = get(template.format(roc_slash=roc))
        body = answer.get("body")
        entry = {
            "candidate": label,
            "http": answer.get("http"),
            "probe_date": probe.isoformat(),
        }
        if isinstance(body, list):
            entry.update({"outcome": "data" if body else "empty", "rows": len(body)})
            if body:
                entry["fields"] = sorted(body[0]) if isinstance(body[0], dict) else None
                entry["first"] = body[0]
        elif isinstance(body, dict):
            rows = body.get("tables", [{}])[0].get("data") if body.get("tables") else body.get("data")
            entry.update({"outcome": "data" if rows else "empty", "rows": len(rows or [])})
            if rows:
                entry["first"] = rows[0]
        else:
            entry.update(
                {
                    "outcome": "refused" if answer.get("http") else "error",
                    "detail": (answer.get("text") or answer.get("error") or answer.get("not_json") or "")[:200],
                }
            )
        print(f"  {label:22s} {entry['outcome']:8s} rows={entry.get('rows')}", flush=True)
        tpex.append(entry)

    reachable = sorted({a["year"] for a in attempts if a["outcome"] == "data"})
    shapes = {
        a["year"]: len(a.get("fields") or [])
        for a in attempts
        if a["outcome"] == "data" and a.get("fields")
    }
    delisted = [a for a in attempts if "delisted_case_present" in a]
    return {
        "schema_id": SCHEMA_ID,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "interval_seconds": interval,
        "requests": len(attempts) + len(tpex),
        "twse": attempts,
        "tpex_candidates": tpex,
        "twse_earliest_year_with_data": reachable[0] if reachable else None,
        "twse_years_with_data": reachable,
        "twse_field_count_by_year": shapes,
        "delisted_case": {
            "symbol": DELISTED_CASE,
            "sessions_checked": len(delisted),
            "present_on": [a["probe_date"] for a in delisted if a["delisted_case_present"]],
            "absent_on": [a["probe_date"] for a in delisted if not a["delisted_case_present"]],
        },
        "reading_note": (
            "A field count that changes between years is a layout change, and "
            "a lane built on one year's shape would read the others as "
            "something else. The delisted case is only asked about on sessions "
            "inside its listed period: outside it, absence is correct."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", required=True, help="comma separated")
    parser.add_argument("--interval", type=float, default=INTERVAL_SECONDS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.interval < 6.0:
        raise SystemExit(f"--interval {args.interval} is below the 6s floor")
    out = args.out.resolve()
    if out.is_relative_to(Path(__file__).resolve().parents[2]):
        raise SystemExit(f"{out} is inside the repository")

    years = [int(y) for y in args.years.split(",")]
    print(f"{len(years)} 年 × 2 日 + {len(TPEX_CANDIDATES)} 個上櫃候選，{args.interval}s")
    report = run(years, args.interval)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\n寫入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
