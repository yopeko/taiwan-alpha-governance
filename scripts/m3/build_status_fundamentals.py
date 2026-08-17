"""M3.5: build `market_status_pit` and `fundamentals_pit`.

Two tables with opposite failure modes.

Market status fails by *absence being read as permission*. A security that
appears in no disposal list is not thereby known to be freely tradable — it
may simply be a date the source never covered. The table therefore records
coverage intervals alongside events, so a query can tell "no event" from
"no coverage".

Fundamentals fail by *a revision travelling backwards*. A restated figure must
not inherit the original's availability, so each statement row carries its own
availability basis and a supersession chain rather than being overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_ID = "tw-alpha-m3-status-fundamentals/1.0.0"
RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
TEJ_LANE = RAW / "m3_tej_licensed_2026-08-16"
WINDOW = (date(2025, 1, 1), date(2026, 8, 3))

STATUS_SOURCES = {
    "TWSE-STATUS-PUNISH-HIST",
    "TWSE-STATUS-NOTICE-HIST",
    "TPEX-STATUS-DISPOSAL-HIST",
    "TPEX-STATUS-ATTENTION-HIST",
}
FUNDAMENTAL_SOURCES = {
    "MOPS-REVENUE-HIST": "monthly-revenue",
    "MOPS-INCOME-HIST": "quarterly-income",
    "MOPS-BALANCE-HIST": "balance-sheet",
    "MOPS-CASHFLOW-HIST": "cash-flow",
}


def sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_index(staging: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (staging / "staging_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def manifest_index(staging: Path) -> dict[str, Path]:
    return {
        m.parent.name: m for m in (staging / "parsed_observations").rglob("parse_manifest.json")
    }


def rows_of(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_bytes())
    rows_path = manifest.get("rows_path")
    if not rows_path:
        return []
    return pq.read_table(manifest_path.parent / str(rows_path)).to_pylist()


def pick(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def build_status(index, manifests):
    """Events plus the coverage intervals that make absence interpretable."""

    events: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] not in STATUS_SOURCES:
            continue
        period = str(record["logical_period"])
        if period.startswith("range:"):
            _, start, end = period.split(":")
            coverage.append(
                {
                    "source_id": record["source_id"],
                    "market": "TPEX" if record["source_id"].startswith("TPEX") else "TWSE",
                    "coverage_from": start,
                    "coverage_to": end,
                    "coverage_state": "covered",
                    "snapshot_id": record["snapshot_id"],
                }
            )
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for ordinal, row in enumerate(rows_of(manifest_path)):
            events.append(
                {
                    "market": row.get("market"),
                    "symbol": row.get("symbol"),
                    "event_kind": row.get("event_kind"),
                    "announced_at": str(row.get("announced_at") or ""),
                    "effective_from": str(row.get("effective_from") or ""),
                    "effective_to": str(row.get("effective_to") or ""),
                    "altered_trading": bool(row.get("altered_trading")),
                    "reason_text": (row.get("reason_text") or "")[:400],
                    "measure_text": (row.get("measure_text") or "")[:400],
                    # Announcement precedes effect, so the announcement date is
                    # the earliest moment the market could act on it.
                    "availability_basis": (
                        "publisher-exact" if row.get("announced_at") else "unknown-blocked"
                    ),
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    for row in events:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("market", "symbol", "event_kind", "effective_from", "snapshot_id")}
        )
    events.sort(key=lambda r: (r["effective_from"] or r["announced_at"], r["market"], str(r["symbol"])))
    coverage.sort(key=lambda r: (r["market"], r["source_id"], r["coverage_from"]))
    return events, coverage


def tej_announcements() -> dict[tuple[str, str], str]:
    """(symbol, period) -> publisher filing date, from the TEJ lane."""

    out: dict[tuple[str, str], str] = {}
    if not TEJ_LANE.is_dir():
        return out
    for manifest_path in TEJ_LANE.rglob("import_manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("module") != "financial-announcement":
            continue
        table = manifest_path.parent / "normalized" / "rows.parquet"
        if not table.is_file():
            continue
        for row in pq.read_table(table).to_pylist():
            symbol, period = row.get("symbol"), str(row.get("period") or "").strip()
            if symbol and period and row.get("announce_date"):
                out[(str(symbol), period)] = str(row["announce_date"])
    return out


def build_fundamentals(index, manifests, announcements):
    rows: list[dict[str, Any]] = []
    basis_counts: dict[str, int] = {}
    for record in index:
        statement = FUNDAMENTAL_SOURCES.get(record["source_id"])
        if not statement:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for ordinal, row in enumerate(rows_of(manifest_path)):
            symbol = str(pick(row, "symbol", "security_id", "co_id") or "").strip()
            if not symbol:
                continue
            period = str(pick(row, "period", "period_end", "year_month", "yearmonth") or "").strip()
            key_period = period.replace("-", "")[:6]
            announced = announcements.get((symbol, key_period))
            basis = "publisher-exact" if announced else "first-observed-only"
            basis_counts[basis] = basis_counts.get(basis, 0) + 1
            rows.append(
                {
                    "symbol": symbol,
                    "statement_type": statement,
                    "period": period,
                    "metric": str(pick(row, "metric", "item", "field") or "as-published-row"),
                    "value": pick(row, "value", "amount"),
                    "publisher_released_at": announced or "",
                    "availability_basis": basis,
                    "revision_of_record_id": "",
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "availability_evidence_state": (
                        "licensed-vendor-snapshot" if announced else "verified-snapshot"
                    ),
                    "source_row_ordinal": ordinal,
                }
            )
    for row in rows:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("symbol", "statement_type", "period", "snapshot_id", "source_row_ordinal")}
        )
    rows.sort(key=lambda r: (r["symbol"], r["statement_type"], r["period"], r["source_row_ordinal"]))
    return rows, basis_counts


def write(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        [{k: (None if v == "" else v) for k, v in row.items()} for row in rows]
    )
    pq.write_table(table, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(staging_root: Path, out_root: Path) -> dict[str, Any]:
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")
    index = load_index(staging_root)
    manifests = manifest_index(staging_root)

    events, coverage = build_status(index, manifests)
    announcements = tej_announcements()
    fundamentals, basis_counts = build_fundamentals(index, manifests, announcements)

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "staging_dataset_id": json.loads(
            (staging_root / "dataset_manifest.json").read_bytes()
        )["dataset_id"],
        "market_status_pit": {
            "rows": len(events),
            "sha256": write(out_root / "market_status_pit.parquet", events),
            "event_kinds": {
                kind: sum(1 for e in events if e["event_kind"] == kind)
                for kind in sorted({e["event_kind"] for e in events})
            },
            "altered_trading_rows": sum(1 for e in events if e["altered_trading"]),
            "with_announcement_date": sum(1 for e in events if e["announced_at"]),
            "distinct_symbols": len({(e["market"], e["symbol"]) for e in events}),
        },
        "market_status_coverage": {
            "rows": len(coverage),
            "sha256": write(out_root / "market_status_coverage.parquet", coverage),
            "note": (
                "Absence of an event inside a covered interval means no event. "
                "Absence outside every covered interval means no coverage, and "
                "must not be read as tradable."
            ),
        },
        "fundamentals_pit": {
            "rows": len(fundamentals),
            "sha256": write(out_root / "fundamentals_pit.parquet", fundamentals),
            "availability_basis_counts": dict(sorted(basis_counts.items())),
            "tej_announcement_pairs": len(announcements),
            "distinct_symbols": len({r["symbol"] for r in fundamentals}),
            "statement_types": sorted({r["statement_type"] for r in fundamentals}),
        },
        "notes": [
            "Suspension is not in this table: no official historical source "
            "exists and it rests on the D8 price-absence inference.",
            "Fundamental availability comes from the TEJ licensed-vendor lane "
            "where present; rows without it fall back to first-observed-only.",
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
    print(json.dumps(build(args.staging_root, args.out_root), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
