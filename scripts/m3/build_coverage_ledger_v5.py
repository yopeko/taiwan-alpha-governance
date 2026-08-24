"""Build the G0-A coverage ledger v5 over the six-year window.

v5 extends the window back to 2019-01-01 and adds the TPEx corporate-action
lane captured for 2019-2023. That lane is what makes the extension worth
anything: `corporate_action` is scored per market, so without it every TPEx
session before 2024 stays `unknown` and the backfill would have bought six
years of TWSE against two of TPEx.

v4 remains as written. It is the evidence for the 1,160 market-date ledger a
Validation Owner signed off, and a rebuild under a different window is a new
artifact, not a correction of that one.

It scores every market-date twice, because whether licensed-vendor evidence
may satisfy `supported` is an open Owner question, not one this build may
decide:

  strict  — only official raw-v2 evidence counts
  vendor  — TEJ `licensed-vendor-snapshot` also counts

The published `reconstruction_state` column uses the strict rule, so the
ledger stays fail-closed. The vendor rule is reported alongside so the Owner
can see exactly what a G0 amendment would unlock.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
# Every family is captured in two ranges: the original 2025-2026 window and
# the 2019-2024 backfill. A builder that widened its window but kept pointing
# at the later lane alone would score six years against captures that do not
# contain them and report `unknown` for all of it -- wrong, and plausible.
WINDOW_CAPTURES = (
    RAW / "m3_window_2019-01-01_2024-12-31",
    RAW / "m3_window_2025-01-01_2026-08-03",
)
STATUS_CAPTURES = (
    RAW / "m3_market_status_2019-01-01_2024-12-31",
    RAW / "m3_market_status_2025-01-01_2026-08-03",
)
ACTIONS_CAPTURES = (
    RAW / "m3_actions_2019-01-01_2024-12-31",
    RAW / "m3_actions_2025-01-01_2026-08-03",
)
# Both lanes. The split is a capture-cost artifact -- MOPS answers one
# symbol-year at a time and the two ranges were captured months apart -- not
# a difference in what the evidence is.
TPEX_ACTION_LANES = (
    RAW / "m3_tpex_actions_2019-2023",
    RAW / "m3_tpex_actions_2024-2026",
)
TEJ_LANE = RAW / "m3_tej_licensed_2026-08-16"
OUT_DIR = RAW / "m3_coverage_ledger_2026-08-24-v5"

WINDOW_START = date(2019, 1, 1)
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
OFFICIAL_OK = {"covered", "official-no-data"}
VENDOR_OK = OFFICIAL_OK | {"licensed-vendor"}


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def blob_text(root: Path, blob_id: str) -> str:
    blob = root / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
    raw = blob.read_bytes()
    try:
        return gzip.decompress(raw).decode("utf-8")
    except (OSError, gzip.BadGzipFile):
        return raw.decode("utf-8-sig", errors="replace")


def action_days() -> set[str]:
    """Calendar days covered by a successful TWSE ex-right range capture."""

    covered: set[str] = set()
    records = [
        record
        for lane in ACTIONS_CAPTURES
        for record in load_jsonl(lane / "actions_capture_ledger.jsonl")
    ]
    for record in records:
        if record.get("outcome") not in {"captured", "official-no-data", "official-empty-range"}:
            continue
        cursor = date.fromisoformat(record["range_start"])
        stop = date.fromisoformat(record["range_end"])
        while cursor <= stop:
            covered.add(cursor.isoformat())
            cursor += timedelta(days=1)
    return covered


def status_days() -> dict[str, set[str]]:
    """Calendar days covered by a successful status range capture, by market."""

    covered: dict[str, set[str]] = {m: set() for m in MARKETS}
    records = [
        record
        for lane in STATUS_CAPTURES
        for record in load_jsonl(lane / "status_capture_ledger.jsonl")
    ]
    for record in records:
        if record.get("outcome") not in {"captured", "official-empty-range"}:
            continue
        market = "TPEX" if str(record["source_id"]).startswith("TPEX") else "TWSE"
        cursor = date.fromisoformat(record["range_start"])
        stop = date.fromisoformat(record["range_end"])
        while cursor <= stop:
            covered[market].add(cursor.isoformat())
            cursor += timedelta(days=1)
    return covered


def tpex_action_years() -> set[int]:
    """Gregorian years whose TPEx per-symbol MOPS capture completed cleanly.

    A year counts only if no symbol-year in it was left incomplete, so a
    partially captured year cannot quietly be treated as covered.
    """

    years: set[int] = set()
    failed: set[int] = set()
    for lane in TPEX_ACTION_LANES:
        ledger = lane / "tpex_actions_ledger.jsonl"
        if not ledger.is_file():
            continue
        lane_failed: set[int] = set()
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            year = int(record["roc_year"]) + 1911
            outcome = record.get("outcome")
            # `already-captured` is a later run reporting that the lane
            # already holds this symbol-year, so it neither proves nor
            # disproves the year. Only real outcomes vote.
            if outcome in {"captured", "official-no-announcements"}:
                years.add(year)
            elif outcome != "already-captured":
                lane_failed.add(year)
        retry = lane / "tpex_detail_retry.json"
        if retry.is_file():
            report = json.loads(retry.read_bytes())
            if report.get("outcome_counts", {}).get("retry-failed", 0) == 0:
                lane_failed.clear()
        failed |= lane_failed
    return years - failed


def tej_present() -> dict[str, bool]:
    listing = False
    announcement = False
    for manifest in TEJ_LANE.rglob("import_manifest.json"):
        payload = json.loads(manifest.read_bytes())
        if payload.get("verdict") != "imported":
            continue
        if payload.get("module") == "security-listing":
            listing = int(payload.get("accepted_rows", 0)) > 0
        if payload.get("module") == "financial-announcement":
            announcement = int(payload.get("accepted_rows", 0)) > 0
    return {"security_lifecycle": listing, "fundamental": announcement}


def main() -> None:
    price = {
        (r["market"], r["date"]): r
        for lane in WINDOW_CAPTURES
        for r in load_jsonl(lane / "capture_ledger.jsonl")
    }
    actions = action_days()
    status = status_days()
    tej = tej_present()
    tpex_years = tpex_action_years()

    rows: list[dict[str, str]] = []
    current = WINDOW_START
    while current <= WINDOW_END:
        iso = current.isoformat()
        both_empty = all(
            price.get((m, iso), {}).get("outcome")
            in {"official-no-data", "official-zero-rows"}
            for m in MARKETS
        )
        for market in MARKETS:
            record = price.get((market, iso), {})
            outcome = record.get("outcome")
            families: dict[str, str] = {}
            reasons: list[str] = []

            if outcome == "captured" and int(record.get("rows", 0)) > 0:
                session_state = "official-open"
                families["calendar"] = "covered"
                families["daily_price"] = "covered"
            elif outcome in {"official-no-data", "official-zero-rows"}:
                session_state = "official-closed"
                families["daily_price"] = "official-no-data"
                families["calendar"] = "covered" if both_empty else "partial"
                if not both_empty:
                    reasons.append("single-market-absence-only")
            else:
                session_state = "unknown"
                families["calendar"] = "unknown"
                families["daily_price"] = "unknown"
                reasons.append("no-capture-outcome-recorded")

            families["market_status"] = (
                "covered" if iso in status[market] else "unknown"
            )
            if families["market_status"] == "covered":
                reasons.append("disposal-and-attention-captured")
                reasons.append("suspension-inferred-from-price-absence")

            if market == "TWSE":
                families["corporate_action"] = (
                    "covered" if iso in actions else "unknown"
                )
            elif current.year in tpex_years:
                families["corporate_action"] = "covered"
                reasons.append("tpex-actions-from-mops-per-symbol-capture")
            else:
                families["corporate_action"] = "unknown"
                reasons.append("tpex-action-year-not-captured")

            families["security_lifecycle"] = (
                "licensed-vendor" if tej["security_lifecycle"] else "current-only"
            )
            families["fundamental"] = (
                "licensed-vendor" if tej["fundamental"] else "partial"
            )
            reasons.append("lifecycle-and-fundamental-from-tej-licensed-vendor")

            def aggregate(allowed: set[str]) -> str:
                if session_state == "official-closed" and families["calendar"] == "covered":
                    return "not-session"
                if session_state == "unknown":
                    return "unknown"
                if all(families[name] in allowed for name in FAMILIES):
                    return "supported"
                if any(families[name] in allowed for name in FAMILIES):
                    return "partial"
                return "unknown"

            strict = aggregate(OFFICIAL_OK)
            vendor = aggregate(VENDOR_OK)
            if strict == "partial" and vendor == "supported":
                reasons.append("blocked-only-by-vendor-dependency")

            rows.append(
                {
                    "market": market,
                    "calendar_date": iso,
                    "session_state": session_state,
                    "reconstruction_state": strict,
                    "reconstruction_state_if_vendor_accepted": vendor,
                    "price_rows": str(record.get("rows", 0) or 0),
                    **{f"coverage_{n}": families[n] for n in FAMILIES},
                    "reason_codes": ";".join(sorted(set(reasons))),
                }
            )
        current += timedelta(days=1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger = OUT_DIR / "coverage_ledger.csv"
    with ledger.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    def tally(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            out[row[key]] = out.get(row[key], 0) + 1
        return dict(sorted(out.items()))

    by_market = {
        m: {
            k: sum(
                1
                for r in rows
                if r["market"] == m and r["reconstruction_state_if_vendor_accepted"] == k
            )
            for k in {r["reconstruction_state_if_vendor_accepted"] for r in rows}
        }
        for m in MARKETS
    }
    blockers: dict[str, int] = {}
    for row in rows:
        if row["reconstruction_state"] != "partial":
            continue
        for name in FAMILIES:
            value = row[f"coverage_{name}"]
            if value not in OFFICIAL_OK:
                key = f"{name}={value}"
                blockers[key] = blockers.get(key, 0) + 1

    summary = {
        "schema_id": "tw-alpha-pit-coverage-certificate/1.0.0",
        "certificate_id": "tw-alpha-m3-coverage-ledger-20260824-05",
        "supersedes": "tw-alpha-m3-coverage-ledger-20260816-04",
        "status": "gap-ledger-only-not-a-supported-date-certificate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": WINDOW_START.isoformat(),
            "end": WINDOW_END.isoformat(),
            "calendar_dates": (WINDOW_END - WINDOW_START).days + 1,
        },
        "row_count": len(rows),
        "ledger_path": str(ledger),
        "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "scoring_note": (
            "reconstruction_state uses official raw-v2 evidence only. "
            "reconstruction_state_if_vendor_accepted also counts TEJ "
            "licensed-vendor-snapshot evidence. Whether the latter may "
            "satisfy `supported` requires a G0 amendment by the Owner."
        ),
        "strict_counts": tally("reconstruction_state"),
        "vendor_counts": tally("reconstruction_state_if_vendor_accepted"),
        "vendor_counts_by_market": by_market,
        "strict_partial_blocking_families": dict(sorted(blockers.items())),
        "inputs": {
            "window_captures": [str(p) for p in WINDOW_CAPTURES],
            "status_captures": [str(p) for p in STATUS_CAPTURES],
            "actions_captures": [str(p) for p in ACTIONS_CAPTURES],
            "tej_lane": str(TEJ_LANE),
            "tpex_action_lanes": [str(p) for p in TPEX_ACTION_LANES],
        },
        "remaining_gaps": [
            "TPEx corporate actions now cover 2019-2026 across two lanes, so "
            "this is no longer a blocking gap. The route is still MOPS "
            "per-symbol-per-year, so extending the window further costs "
            "roughly 900 requests per added year.",
            "Suspension state rests on the D8 owner-approved inference, not on "
            "official evidence.",
            "Security lifecycle and fundamentals rest on TEJ licensed-vendor "
            "evidence; a G0 amendment is required to decide whether that may "
            "satisfy `supported`.",
        ],
    }
    (OUT_DIR / "coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
