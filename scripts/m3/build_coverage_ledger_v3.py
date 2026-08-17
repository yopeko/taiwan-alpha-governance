"""Build the G0-A coverage ledger v3, including all M3.1b-e captures.

v3 adds market status, corporate actions and the TEJ licensed-vendor lane.

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
WINDOW_CAPTURE = RAW / "m3_window_2025-01-01_2026-08-03"
STATUS_CAPTURE = RAW / "m3_market_status_2025-01-01_2026-08-03"
ACTIONS_CAPTURE = RAW / "m3_actions_2025-01-01_2026-08-03"
TEJ_LANE = RAW / "m3_tej_licensed_2026-08-16"
OUT_DIR = RAW / "m3_coverage_ledger_2026-08-16-v3"

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
    for record in load_jsonl(ACTIONS_CAPTURE / "actions_capture_ledger.jsonl"):
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
    for record in load_jsonl(STATUS_CAPTURE / "status_capture_ledger.jsonl"):
        if record.get("outcome") not in {"captured", "official-empty-range"}:
            continue
        market = "TPEX" if str(record["source_id"]).startswith("TPEX") else "TWSE"
        cursor = date.fromisoformat(record["range_start"])
        stop = date.fromisoformat(record["range_end"])
        while cursor <= stop:
            covered[market].add(cursor.isoformat())
            cursor += timedelta(days=1)
    return covered


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
        for r in load_jsonl(WINDOW_CAPTURE / "capture_ledger.jsonl")
    }
    actions = action_days()
    status = status_days()
    tej = tej_present()

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
            else:
                families["corporate_action"] = "unknown"
                reasons.append("tpex-no-range-based-exright-endpoint")

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
        "certificate_id": "tw-alpha-m3-coverage-ledger-20260816-03",
        "supersedes": "tw-alpha-m3-coverage-ledger-20260816-02",
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
            "window_capture": str(WINDOW_CAPTURE),
            "status_capture": str(STATUS_CAPTURE),
            "actions_capture": str(ACTIONS_CAPTURE),
            "tej_lane": str(TEJ_LANE),
        },
        "remaining_gaps": [
            "TPEx corporate actions: no range-based official endpoint exists; "
            "the only historical route is MOPS per-symbol-per-year "
            "(~890 symbols x 2 years). TPEx therefore cannot reach `supported` "
            "under either scoring rule.",
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
