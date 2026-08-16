"""Build the G0-A fixed-window market-date coverage ledger (v2).

Window: 2025-01-01 .. 2026-08-03 inclusive, TWSE and TPEx listed separately.

v2 consumes the M3.1b window capture, so session state now rests on direct
official evidence: an official full-market closing table for a date is evidence
the session happened, and an explicit empty reply from both markets is evidence
it did not. Absence of evidence is still never inferred into a tradable state.
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
M3_WINDOW = Path(
    r"C:\project\tw-sepa-screener\data\raw_v2\m3_window_2025-01-01_2026-08-03"
)
CAPTURE_LEDGER = M3_WINDOW / "capture_ledger.jsonl"
OUT_DIR = Path(
    r"C:\project\tw-sepa-screener\data\raw_v2\m3_coverage_ledger_2026-08-16-v2"
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


def load_capture_outcomes() -> dict[tuple[str, str], dict[str, object]]:
    outcomes: dict[tuple[str, str], dict[str, object]] = {}
    for line in CAPTURE_LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        outcomes[(record["market"], record["date"])] = record
    return outcomes


def load_official_closures() -> dict[str, set[date]]:
    closures: dict[str, set[date]] = {market: set() for market in MARKETS}
    for path in (M2_MAIN / "parsed_observations").rglob("parse_manifest.json"):
        manifest = json.loads(path.read_bytes())
        if str(manifest["endpoint_id"]) != "holiday-schedule":
            continue
        market = "TPEX" if "TPEX" in str(manifest["source_id"]) else "TWSE"
        rows = pq.read_table(path.parent / str(manifest["rows_path"])).to_pydict()
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


def load_archive_sessions() -> dict[str, set[date]]:
    sessions: dict[str, set[date]] = {market: set() for market in MARKETS}
    for root in (M2_MAIN, M2_PRICE96):
        for path in (root / "raw_observations").rglob("manifest.json"):
            manifest = json.loads(path.read_bytes())
            period = str(manifest["logical_period"])
            if not period.startswith("session:"):
                continue
            if "daily-prices" not in str(manifest["endpoint_id"]):
                continue
            market = "TPEX" if "TPEX" in str(manifest["source_id"]) else "TWSE"
            sessions[market].add(date.fromisoformat(period.split(":", 1)[1]))
    return sessions


def load_action_days() -> dict[str, set[date]]:
    ranges: dict[str, set[date]] = {market: set() for market in MARKETS}
    for path in (M2_MAIN / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(path.read_bytes())
        period = str(manifest["logical_period"])
        if not period.startswith("range:") or "exright" not in str(
            manifest["endpoint_id"]
        ):
            continue
        _, start, end = period.split(":")
        market = "TPEX" if "TPEX" in str(manifest["source_id"]) else "TWSE"
        current = date.fromisoformat(start)
        last = date.fromisoformat(end)
        while current <= last:
            ranges[market].add(current)
            current += timedelta(days=1)
    return ranges


def main() -> None:
    outcomes = load_capture_outcomes()
    official_closures = load_official_closures()
    archive_sessions = load_archive_sessions()
    action_days = load_action_days()

    rows: list[dict[str, str]] = []
    current = WINDOW_START
    while current <= WINDOW_END:
        iso = current.isoformat()
        both_empty = all(
            (outcomes.get((m, iso), {}).get("outcome"))
            in {"official-no-data", "official-zero-rows"}
            for m in MARKETS
        )
        for market in MARKETS:
            record = outcomes.get((market, iso))
            families: dict[str, str] = {}
            reasons: list[str] = []

            outcome = record.get("outcome") if record else None
            price_rows = int(record.get("rows", 0)) if record else 0

            if outcome == "captured" and price_rows > 0:
                session_state = "official-open"
                families["calendar"] = "covered"
                families["daily_price"] = "covered"
                reasons.append("official-closing-table-present")
            elif outcome in {"official-no-data", "official-zero-rows"}:
                session_state = "official-closed"
                families["daily_price"] = "official-no-data"
                if current in official_closures[market] or (
                    market == "TPEX" and current in official_closures["TWSE"]
                ):
                    families["calendar"] = "covered"
                    reasons.append("official-holiday-schedule-listed")
                elif both_empty:
                    families["calendar"] = "covered"
                    reasons.append("closure-corroborated-by-both-markets-absence")
                else:
                    families["calendar"] = "partial"
                    reasons.append("single-market-absence-only")
            else:
                session_state = "unknown"
                families["calendar"] = "unknown"
                families["daily_price"] = "unknown"
                reasons.append("no-capture-outcome-recorded")

            if current in archive_sessions[market]:
                reasons.append("also-present-in-m2-archive")

            families["security_lifecycle"] = "current-only"
            reasons.append("security-lifecycle-current-only")
            families["market_status"] = "current-only"
            reasons.append("market-status-current-only")
            families["corporate_action"] = (
                "covered" if current in action_days[market] else "unknown"
            )
            if families["corporate_action"] == "unknown":
                reasons.append("no-dated-corporate-action-observation")
            families["fundamental"] = "partial"
            reasons.append("fundamental-coverage-limited-to-2026-06-and-2026Q1")

            if session_state == "official-closed" and families["calendar"] == "covered":
                reconstruction = "not-session"
            elif session_state == "unknown":
                reconstruction = "unknown"
            elif all(families[name] == "covered" for name in FAMILIES):
                reconstruction = "supported"
            elif any(families[name] == "covered" for name in FAMILIES):
                reconstruction = "partial"
            else:
                reconstruction = "unknown"

            rows.append(
                {
                    "market": market,
                    "calendar_date": iso,
                    "session_state": session_state,
                    "reconstruction_state": reconstruction,
                    "price_rows": str(price_rows),
                    **{f"coverage_{name}": families[name] for name in FAMILIES},
                    "reason_codes": ";".join(sorted(set(reasons))),
                }
            )
        current += timedelta(days=1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = OUT_DIR / "coverage_ledger.csv"
    with ledger_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    ledger_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

    by_state: dict[str, int] = {}
    by_market: dict[str, dict[str, int]] = {m: {} for m in MARKETS}
    blockers: dict[str, int] = {}
    for row in rows:
        state = row["reconstruction_state"]
        by_state[state] = by_state.get(state, 0) + 1
        by_market[row["market"]][state] = by_market[row["market"]].get(state, 0) + 1
        if state == "partial":
            for name in FAMILIES:
                value = row[f"coverage_{name}"]
                if value not in {"covered", "official-no-data"}:
                    key = f"{name}={value}"
                    blockers[key] = blockers.get(key, 0) + 1

    summary = {
        "schema_id": "tw-alpha-pit-coverage-certificate/1.0.0",
        "certificate_id": "tw-alpha-m3-coverage-ledger-20260816-02",
        "supersedes": "tw-alpha-m3-coverage-ledger-20260816-01",
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
        "partial_blocking_families": dict(sorted(blockers.items())),
        "inputs": {
            "m2_main": str(M2_MAIN),
            "m2_dailyprice96": str(M2_PRICE96),
            "m3_window_capture": str(M3_WINDOW),
        },
        "remaining_gaps": [
            "security_lifecycle is a current-only snapshot for every date; "
            "TEJ listing history is the approved fill and is not yet imported.",
            "market_status is current-only for every date and has no approved "
            "historical source at all — this is now the single largest gap.",
            "corporate_action has dated coverage for one date only.",
            "fundamental coverage is limited to 2026-06 revenue and 2026Q1; "
            "TEJ announcement dates are the approved fill and are not yet imported.",
        ],
    }
    (OUT_DIR / "coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
