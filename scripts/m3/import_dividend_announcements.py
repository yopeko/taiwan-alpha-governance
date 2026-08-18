"""M3.9: attach TEJ ex-dividend announcement dates to the official actions.

TWT49U publishes the corporate actions but no announcement date, so every one
of them fell back to `first-observed-only` and was therefore invisible at
every historical cutoff. TEJ supplies the missing announcement date.

The official record stays the subject. TEJ contributes one field and nothing
else, because comparison showed TEJ is missing 109 events that the exchange
did publish: letting TEJ define the event set would silently delete them.

Three outcomes, each explicit:

* `publisher-exact`  — TEJ supplied an announcement date that precedes the
  ex-date, so the action was knowable in advance.
* `unknown-blocked`  — TEJ's announcement date is on or after the ex-date, so
  the action was not knowable when it took effect. Kept, never usable.
* `first-observed-only` — TEJ has no row for this official event.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_ID = "tw-alpha-m3-action-availability/1.0.0"
ACTIONS = Path(r"C:\project\tw-sepa-screener\data\raw_v2\m3_actions_2025-01-01_2026-08-03")
WINDOW = ("2025-01-01", "2026-08-03")


def sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def iso8(value: Any) -> str:
    digits = "".join(c for c in str(value) if c.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    return ""


def read_tej(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-16", "utf-8-sig", "cp950"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise SystemExit(f"cannot decode {path}")
    lines = text.splitlines()
    separator = "\t" if lines[0].count("\t") > lines[0].count(",") else ","
    columns = [c.strip() for c in lines[0].split(separator)]
    index = {c: i for i, c in enumerate(columns)}
    for required in ("年月日", "除息公告日"):
        if required not in index:
            raise SystemExit(f"TEJ export lacks required column {required}")
    out: dict[tuple[str, str], dict[str, str]] = {}
    for line in lines[1:]:
        values = line.split(separator)
        if len(values) <= max(index["年月日"], index["除息公告日"]):
            continue
        symbol = values[0].split()[0] if values[0].split() else ""
        ex_date = iso8(values[index["年月日"]])
        if not symbol or not ex_date:
            continue
        out[(symbol, ex_date)] = {
            "announced_at": iso8(values[index["除息公告日"]]),
            "reference_price": (
                values[index["除息(權)參考價(元)"]].strip()
                if "除息(權)參考價(元)" in index
                and len(values) > index["除息(權)參考價(元)"]
                else ""
            ),
            "dividend_type": (
                values[index["股息分配型態"]].strip()
                if "股息分配型態" in index and len(values) > index["股息分配型態"]
                else ""
            ),
        }
    return out


def blob_text(root: Path, blob_id: str) -> str:
    blob = root / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
    raw = blob.read_bytes()
    try:
        return gzip.decompress(raw).decode("utf-8")
    except (OSError, gzip.BadGzipFile):
        return raw.decode("utf-8-sig", errors="replace")


def read_official() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in (ACTIONS / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        payload = json.loads(blob_text(ACTIONS, str(manifest["blob_id"])))
        index = {str(n): i for i, n in enumerate(payload.get("fields") or [])}
        for ordinal, row in enumerate(payload.get("data") or []):
            symbol = str(row[index["股票代號"]]).strip()
            ex_date = iso8(row[index["資料日期"]])
            if not (symbol and ex_date):
                continue
            rows.append(
                {
                    "market": "TWSE",
                    "symbol": symbol,
                    "effective_date": ex_date,
                    "official_reference_price": str(row[index["除權息參考價"]]).strip(),
                    "official_limit_up": str(row[index["漲停價格"]]).strip(),
                    "official_limit_down": str(row[index["跌停價格"]]).strip(),
                    "right_or_dividend": str(row[index["權/息"]]).strip(),
                    "snapshot_id": str(manifest["snapshot_id"]),
                    "source_id": str(manifest["source_id"]),
                    "source_row_ordinal": ordinal,
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tej-csv", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out_root.exists() and any(args.out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {args.out_root}")

    tej = read_tej(args.tej_csv)
    official = read_official()

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for record in official:
        key = (record["symbol"], record["effective_date"])
        match = tej.get(key)
        announced = match["announced_at"] if match else ""
        if not match:
            basis = "first-observed-only"
            reason = "no-tej-row-for-this-official-event"
        elif not announced:
            basis = "first-observed-only"
            reason = "tej-row-has-empty-announcement-date"
        elif announced >= record["effective_date"]:
            # Announced on or after the day it took effect: nobody could have
            # acted on it in advance, so it must never inform an as-of query.
            basis = "unknown-blocked"
            reason = "announcement-not-earlier-than-effect"
        else:
            basis = "publisher-exact"
            reason = "tej-announcement-precedes-effect"
        counts[basis] = counts.get(basis, 0) + 1
        rows.append(
            {
                **record,
                "announced_at": announced,
                "availability_basis": basis,
                "availability_reason": reason,
                "announcement_evidence_state": (
                    "licensed-vendor-snapshot" if announced else "missing-at-source"
                ),
                "evidence_state": "verified-snapshot",
                "lead_days": (
                    (
                        date.fromisoformat(record["effective_date"])
                        - date.fromisoformat(announced)
                    ).days
                    if announced
                    else None
                ),
            }
        )
    for row in rows:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("market", "symbol", "effective_date", "snapshot_id")}
        )
    rows.sort(key=lambda r: (r["effective_date"], r["symbol"]))

    args.out_root.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        [{k: (None if v == "" else v) for k, v in row.items()} for row in rows]
    )
    out = args.out_root / "corporate_actions_pit.parquet"
    pq.write_table(table, out)

    usable = [r for r in rows if r["availability_basis"] == "publisher-exact"]
    visibility = {}
    for cutoff in ("2025-06-30", "2025-12-31", WINDOW[1]):
        visibility[cutoff] = sum(
            1
            for r in usable
            if r["announced_at"] <= cutoff and WINDOW[0] <= r["effective_date"] <= WINDOW[1]
        )
    leads = sorted(r["lead_days"] for r in usable if r["lead_days"] is not None)
    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "tej_source": str(args.tej_csv),
        "tej_source_sha256": hashlib.sha256(args.tej_csv.read_bytes()).hexdigest(),
        "official_events": len(official),
        "tej_rows": len(tej),
        "rows": len(rows),
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "availability_basis_counts": dict(sorted(counts.items())),
        "asof_visibility": visibility,
        "lead_days": {
            "min": leads[0] if leads else None,
            "median": leads[len(leads) // 2] if leads else None,
            "max": leads[-1] if leads else None,
        },
        "design_notes": [
            "The official TWT49U record is the subject; TEJ contributes only "
            "the announcement date. TEJ is missing 109 events the exchange "
            "published, so letting it define the event set would delete them.",
            "An announcement dated on or after the ex-date is kept but marked "
            "unknown-blocked, never usable at any cutoff.",
        ],
    }
    (args.out_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
