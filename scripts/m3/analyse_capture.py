"""Analyse the window capture ledger: do the two markets share a calendar?

D2 approved a policy that TWSE and TPEx share one securities-market calendar.
This checks that policy against what the official endpoints actually returned.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

LEDGER = Path(r"C:\tmp\tw-alpha-m3-capture-20260816-01\capture_ledger.jsonl")
TRADING = {"captured"}
NON_TRADING = {"official-no-data", "official-zero-rows"}


def main() -> None:
    trading: dict[str, set[str]] = defaultdict(set)
    non_trading: dict[str, set[str]] = defaultdict(set)
    rows: dict[tuple[str, str], int] = {}

    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        market = record["market"]
        day = record["date"]
        if record["outcome"] in TRADING:
            trading[market].add(day)
            rows[(market, day)] = int(record.get("rows", 0))
        elif record["outcome"] in NON_TRADING:
            non_trading[market].add(day)

    twse_t, tpex_t = trading["TWSE"], trading["TPEX"]
    twse_n, tpex_n = non_trading["TWSE"], non_trading["TPEX"]

    only_twse = sorted(twse_t - tpex_t)
    only_tpex = sorted(tpex_t - twse_t)

    # Weekend / weekday split of the agreed non-trading days.
    shared_non = sorted(twse_n & tpex_n)
    weekday_closures = [
        d for d in shared_non if date.fromisoformat(d).weekday() < 5
    ]
    weekend_closures = [
        d for d in shared_non if date.fromisoformat(d).weekday() >= 5
    ]

    # Any weekend that was actually a trading day (make-up sessions).
    weekend_sessions = sorted(
        d for d in twse_t if date.fromisoformat(d).weekday() >= 5
    )

    start, end = date(2025, 1, 1), date(2026, 8, 3)
    all_days = set()
    cur = start
    while cur <= end:
        all_days.add(cur.isoformat())
        cur += timedelta(days=1)

    report = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "calendar_dates": len(all_days),
        "trading_days": {"TWSE": len(twse_t), "TPEX": len(tpex_t)},
        "non_trading_days": {"TWSE": len(twse_n), "TPEX": len(tpex_n)},
        "calendars_identical": twse_t == tpex_t,
        "trading_only_in_TWSE": only_twse,
        "trading_only_in_TPEX": only_tpex,
        "shared_non_trading_days": len(shared_non),
        "weekend_closures": len(weekend_closures),
        "weekday_closures": len(weekday_closures),
        "weekday_closure_dates": weekday_closures,
        "weekend_trading_sessions": weekend_sessions,
        "coverage_complete": len(twse_t | twse_n) == len(all_days)
        and len(tpex_t | tpex_n) == len(all_days),
        "row_totals": {
            "TWSE": sum(v for (m, _), v in rows.items() if m == "TWSE"),
            "TPEX": sum(v for (m, _), v in rows.items() if m == "TPEX"),
        },
        "row_range": {
            market: {
                "min": min(
                    (v for (m, _), v in rows.items() if m == market), default=0
                ),
                "max": max(
                    (v for (m, _), v in rows.items() if m == market), default=0
                ),
            }
            for market in ("TWSE", "TPEX")
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
