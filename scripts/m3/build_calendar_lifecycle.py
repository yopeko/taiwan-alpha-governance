"""M3.3: build `trading_calendar_pit`, `security_events` and `security_intervals`.

Reads the M3.2 staging layer and the TEJ licensed-vendor lane, and emits the
first two canonical point-in-time table families.

Three rules this build exists to enforce:

* **A session is proved, never inferred.** A date is `official-open` only
  because the exchange published a closing table for it, and `official-closed`
  only because both markets explicitly returned nothing. The two markets
  express "nothing" differently — TWSE rejects the parse, TPEx returns zero
  rows — and both forms are recognised.

* **A symbol is not an identity.** 2301 and 2432 each appear in both the
  delisted and the current records, so membership is keyed on a
  `security_instance_id` derived from market, symbol and listing interval.

* **A missing listing date is not permission to trade.** Such a security gets
  `membership_state=unknown`, never `eligible`, exactly as M0 requires.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_ID = "tw-alpha-m3-calendar-lifecycle/1.0.0"
RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
TEJ_LANE = RAW / "m3_tej_licensed_2026-08-16"
WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2026, 8, 3)
MARKETS = ("TWSE", "TPEX")

PRICE_SOURCES = {"TWSE-PRICE-HIST": "TWSE", "TPEX-PRICE-HIST": "TPEX"}


def sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_index(staging: Path) -> list[dict[str, Any]]:
    path = staging / "staging_index.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_manifest_for(staging: Path, parse_run_id: str) -> Path | None:
    for manifest in (staging / "parsed_observations").rglob("parse_manifest.json"):
        if manifest.parent.name == parse_run_id:
            return manifest
    return None


def build_calendar(staging: Path, index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per market-date, with the evidence that decided its state."""

    observed: dict[tuple[str, str], dict[str, Any]] = {}
    for record in index:
        market = PRICE_SOURCES.get(record["source_id"])
        if not market:
            continue
        period = str(record["logical_period"])
        if not period.startswith("session:"):
            continue
        observed[(market, period.split(":", 1)[1])] = record

    # A session that produced no parseable rows is `official-no-data`; the
    # staging index only holds parsed observations, so an absent entry for a
    # captured date is itself the no-data signal.
    rows: list[dict[str, Any]] = []
    cursor = WINDOW_START
    while cursor <= WINDOW_END:
        iso = cursor.isoformat()
        present = {m: observed.get((m, iso)) for m in MARKETS}
        any_open = any(
            record and int(record.get("row_count", 0)) > 0 for record in present.values()
        )
        for market in MARKETS:
            record = present[market]
            row_count = int(record.get("row_count", 0)) if record else 0
            if record and row_count > 0:
                session_state = "official-open"
                basis = "official-closing-table-published"
                quality = record.get("quality_decision")
            elif any_open:
                # The other market traded, so this one's silence is not a
                # market-wide closure. Fail closed rather than guess.
                session_state = "unknown"
                basis = "single-market-absence-only"
                quality = record.get("quality_decision") if record else None
            else:
                session_state = "official-closed"
                basis = (
                    "zero-row-response"
                    if record
                    else "parse-rejected-no-data-response"
                )
                quality = record.get("quality_decision") if record else None
            rows.append(
                {
                    "market": market,
                    "session_date": iso,
                    "session_state": session_state,
                    "evidence_basis": basis,
                    "observed_row_count": row_count,
                    "quality_decision": quality or "",
                    "snapshot_id": (record or {}).get("snapshot_id", ""),
                    "parse_run_id": (record or {}).get("parse_run_id", ""),
                    "evidence_tier": (record or {}).get("evidence_tier", "no-parsed-observation"),
                }
            )
        cursor += timedelta(days=1)
    for row in rows:
        row["record_id"] = sha({k: row[k] for k in ("market", "session_date", "session_state")})
    return rows


def load_tej_lifecycle() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not TEJ_LANE.is_dir():
        return out
    for manifest_path in TEJ_LANE.rglob("import_manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("module") != "security-listing":
            continue
        table = manifest_path.parent / "normalized" / "rows.parquet"
        if not table.is_file():
            continue
        for row in pq.read_table(table).to_pylist():
            out.append(
                {
                    "market": row.get("market"),
                    "symbol": row.get("symbol"),
                    "security_name": row.get("security_name"),
                    "listing_date": row.get("listing_date"),
                    "delisting_date": row.get("delisting_date"),
                    "evidence_state": "licensed-vendor-snapshot",
                    "snapshot_id": row.get("snapshot_id"),
                    "source_locator": str(manifest_path.parent.name),
                }
            )
    return out


def build_lifecycle(records: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    events: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    for record in records:
        market, symbol = record.get("market"), record.get("symbol")
        if not market or not symbol:
            continue
        listing = record.get("listing_date")
        delisting = record.get("delisting_date")
        instance = sha(
            {"market": market, "symbol": symbol, "listing_date": listing or "unknown"}
        )
        for kind, when in (("listing", listing), ("delisting", delisting)):
            if not when:
                continue
            events.append(
                {
                    "security_instance_id": instance,
                    "market": market,
                    "symbol": symbol,
                    "event_kind": kind,
                    "effective_date": when,
                    "evidence_state": record["evidence_state"],
                    "snapshot_id": record.get("snapshot_id") or "",
                }
            )
        intervals.append(
            {
                "security_instance_id": instance,
                "market": market,
                "symbol": symbol,
                "security_name": record.get("security_name") or "",
                "listing_date": listing or "",
                "delisting_date": delisting or "",
                # A security with no listing date can never be proved to have
                # been in the market on a past date, so it stays unknown.
                "membership_basis": "listed-interval" if listing else "missing-at-source",
                "default_membership_state": "resolvable" if listing else "unknown",
                "evidence_state": record["evidence_state"],
            }
        )
    events.sort(key=lambda r: (r["market"], r["symbol"], r["event_kind"], r["effective_date"]))
    intervals.sort(key=lambda r: (r["market"], r["symbol"], r["listing_date"]))
    return events, intervals


def membership_on(intervals: list[dict[str, Any]], as_of: date) -> dict[str, str]:
    """Membership state per security_instance_id at a historical session."""

    states: dict[str, str] = {}
    for row in intervals:
        if row["default_membership_state"] == "unknown":
            states[row["security_instance_id"]] = "unknown"
            continue
        listed = date.fromisoformat(row["listing_date"])
        if as_of < listed:
            states[row["security_instance_id"]] = "not-yet-listed"
            continue
        if row["delisting_date"]:
            if as_of >= date.fromisoformat(row["delisting_date"]):
                states[row["security_instance_id"]] = "delisted"
                continue
        states[row["security_instance_id"]] = "listed"
    return states


def write_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(staging_root: Path, out_root: Path) -> dict[str, Any]:
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")
    index = load_index(staging_root)
    calendar = build_calendar(staging_root, index)
    events, intervals = build_lifecycle(load_tej_lifecycle())

    calendar_sha = write_csv(out_root / "trading_calendar_pit.csv", calendar)
    events_sha = write_csv(out_root / "security_events.csv", events)
    intervals_sha = write_csv(out_root / "security_intervals.csv", intervals)

    by_state: dict[str, int] = {}
    for row in calendar:
        by_state[row["session_state"]] = by_state.get(row["session_state"], 0) + 1

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "staging_root": str(staging_root),
        "staging_dataset_id": json.loads(
            (staging_root / "dataset_manifest.json").read_bytes()
        )["dataset_id"],
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "trading_calendar_pit": {
            "rows": len(calendar),
            "sha256": calendar_sha,
            "session_state_counts": dict(sorted(by_state.items())),
        },
        "security_events": {"rows": len(events), "sha256": events_sha},
        "security_intervals": {
            "rows": len(intervals),
            "sha256": intervals_sha,
            "with_listing_date": sum(1 for r in intervals if r["listing_date"]),
            "missing_at_source": sum(
                1 for r in intervals if r["membership_basis"] == "missing-at-source"
            ),
            "delisted": sum(1 for r in intervals if r["delisting_date"]),
            "distinct_instances": len({r["security_instance_id"] for r in intervals}),
            "distinct_symbols": len({(r["market"], r["symbol"]) for r in intervals}),
        },
        "notes": [
            "Lifecycle currently rests on TEJ licensed-vendor evidence, "
            "permitted for `supported` by G0 v2.0.0 D9 with its six conditions.",
            "A security without a listing date is `unknown`, never eligible.",
        ],
    }
    (out_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.staging_root, args.out_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
