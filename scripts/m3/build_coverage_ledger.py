"""Build the G0-A fixed-window market-date coverage ledger.

Window: 2025-01-01 .. 2026-08-03 inclusive, TWSE and TPEx listed separately.
Every state is derived only from durable raw-v2 evidence. Absence of evidence
is recorded as `unknown` and never inferred into a tradable or open state.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq

M2_MAIN = Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03")
M2_PRICE96 = Path(
    r"C:\project\tw-sepa-screener\data\raw_v2\m2_dailyprice96_2026-08-03"
)
OUT_DIR = Path(
    r"C:\project\tw-sepa-screener\data\raw_v2\m3_coverage_ledger_2026-08-16"
)

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2026, 8, 3)
MARKETS = ("TWSE", "TPEX")

FAMILIES = (
    "calendar",
    "security_lifecycle",
    "daily_price",
    "market_status",
    "corporate_action",
    "fundamental",
)


def load_price_sessions() -> dict[str, set[date]]:
    """Durable session-level daily-price observations, by market."""

    sessions: dict[str, set[date]] = {market: set() for market in MARKETS}
    for root in (M2_MAIN, M2_PRICE96):
        for path in (root / "raw_observations").rglob("manifest.json"):
            manifest = json.loads(path.read_bytes())
            period = str(manifest["logical_period"])
            if not period.startswith("session:"):
                continue
            if "daily-prices" not in str(manifest["endpoint_id"]):
                continue
            source = str(manifest["source_id"])
            market = "TPEX" if "TPEX" in source else "TWSE"
            sessions[market].add(date.fromisoformat(period.split(":", 1)[1]))
    return sessions


def load_calendar_closures() -> dict[str, set[date]]:
    """Official closure dates, by market, from the captured holiday schedule."""

    closures: dict[str, set[date]] = {market: set() for market in MARKETS}
    for path in (M2_MAIN / "parsed_observations").rglob("parse_manifest.json"):
        manifest = json.loads(path.read_bytes())
        if str(manifest["endpoint_id"]) != "holiday-schedule":
            continue
        source = str(manifest["source_id"])
        market = "TPEX" if "TPEX" in source else "TWSE"
        table = pq.read_table(path.parent / str(manifest["rows_path"]))
        rows = table.to_pydict()
        for raw_date, is_closure in zip(
            rows["calendar_date"], rows["is_closure"], strict=True
        ):
            if not is_closure:
                continue
            value = (
                raw_date
                if isinstance(raw_date, date)
                else date.fromisoformat(str(raw_date))
            )
            closures[market].add(value)
    return closures


def load_corporate_action_ranges() -> dict[str, set[date]]:
    ranges: dict[str, set[date]] = {market: set() for market in MARKETS}
    for path in (M2_MAIN / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(path.read_bytes())
        period = str(manifest["logical_period"])
        if not period.startswith("range:"):
            continue
        if "exright" not in str(manifest["endpoint_id"]):
            continue
        _, start, end = period.split(":")
        source = str(manifest["source_id"])
        market = "TPEX" if "TPEX" in source else "TWSE"
        current = date.fromisoformat(start)
        last = date.fromisoformat(end)
        while current <= last:
            ranges[market].add(current)
            current += timedelta(days=1)
    return ranges


def main() -> None:
    price_sessions = load_price_sessions()
    closures = load_calendar_closures()
    action_days = load_corporate_action_ranges()

    rows: list[dict[str, str]] = []
    current = WINDOW_START
    while current <= WINDOW_END:
        for market in MARKETS:
            families: dict[str, str] = {}
            reasons: list[str] = []

            if current in closures[market]:
                families["calendar"] = "covered"
                session_state = "official-closed"
            else:
                families["calendar"] = "unknown"
                session_state = "unknown"
                reasons.append("no-official-session-record-for-market-date")

            # Security lifecycle: only a current snapshot exists.
            families["security_lifecycle"] = "current-only"
            reasons.append("security-lifecycle-current-only")

            if current in price_sessions[market]:
                families["daily_price"] = "covered"
            else:
                families["daily_price"] = "unknown"
                reasons.append("no-durable-daily-price-observation")

            families["market_status"] = "current-only"
            reasons.append("market-status-current-only")

            if current in action_days[market]:
                families["corporate_action"] = "covered"
            else:
                families["corporate_action"] = "unknown"
                reasons.append("no-dated-corporate-action-observation")

            families["fundamental"] = "partial"
            reasons.append("fundamental-coverage-limited-to-2026-06-and-2026Q1")

            if session_state == "official-closed":
                reconstruction = "not-session"
            elif all(families[name] == "covered" for name in FAMILIES):
                reconstruction = "supported"
            elif any(families[name] == "covered" for name in FAMILIES):
                reconstruction = "partial"
            else:
                reconstruction = "unknown"

            rows.append(
                {
                    "market": market,
                    "calendar_date": current.isoformat(),
                    "session_state": session_state,
                    "reconstruction_state": reconstruction,
                    **{f"coverage_{name}": families[name] for name in FAMILIES},
                    "reason_codes": ";".join(sorted(set(reasons))),
                }
            )
        current += timedelta(days=1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = OUT_DIR / "coverage_ledger.csv"
    fieldnames = list(rows[0].keys())
    with ledger_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    ledger_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

    by_state: dict[str, int] = {}
    by_market: dict[str, dict[str, int]] = {m: {} for m in MARKETS}
    for row in rows:
        state = row["reconstruction_state"]
        by_state[state] = by_state.get(state, 0) + 1
        market = by_market[row["market"]]
        market[state] = market.get(state, 0) + 1

    covered_price = {
        market: sorted(d.isoformat() for d in price_sessions[market] if
                       WINDOW_START <= d <= WINDOW_END)
        for market in MARKETS
    }

    summary = {
        "schema_id": "tw-alpha-pit-coverage-certificate/1.0.0",
        "certificate_id": "tw-alpha-m3-coverage-ledger-20260816-01",
        "status": "gap-ledger-only-not-a-supported-date-certificate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": WINDOW_START.isoformat(),
            "end": WINDOW_END.isoformat(),
            "calendar_dates": (WINDOW_END - WINDOW_START).days + 1,
        },
        "markets": list(MARKETS),
        "row_count": len(rows),
        "ledger_path": str(ledger_path),
        "ledger_sha256": ledger_sha,
        "reconstruction_state_counts": by_state,
        "reconstruction_state_counts_by_market": by_market,
        "durable_daily_price_sessions_in_window": {
            market: {"count": len(values), "dates": values}
            for market, values in covered_price.items()
        },
        "durable_daily_price_sessions_total": {
            market: len(price_sessions[market]) for market in MARKETS
        },
        "official_closure_dates_in_window": {
            market: sorted(
                d.isoformat()
                for d in closures[market]
                if WINDOW_START <= d <= WINDOW_END
            )
            for market in MARKETS
        },
        "inputs": {
            "m2_main": str(M2_MAIN),
            "m2_dailyprice96": str(M2_PRICE96),
        },
        "blocking_findings": [
            "No official trading-calendar source covers 2025; TWSE holiday "
            "evidence exists only for 2026 and TPEx has no calendar source.",
            "A date absent from the holiday schedule is NOT evidence of an "
            "open session; open sessions remain unproven.",
            "Security lifecycle and market status are current-only snapshots "
            "and cannot describe any historical date.",
            "Durable daily-price coverage inside the window is a single "
            "session (2026-07-31) for both markets; the 96-session repair "
            "archive is TWSE-only and almost entirely outside the window.",
            "Zero market-dates reach `supported`; M3 exit is therefore not "
            "attainable without a new historical capture programme.",
        ],
    }
    summary_path = OUT_DIR / "coverage_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
