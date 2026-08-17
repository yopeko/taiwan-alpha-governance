"""M3.4: build `daily_prices_pit` and `corporate_actions_pit`.

Reads the M3.2 staging layer and emits the price and corporate-action
point-in-time tables.

The rules this build exists to enforce, all from the PIT contract §6.4/§6.6:

* **A missing OHLC stays missing.** No forward fill, no carrying yesterday's
  close. `ohlc_state` records *why* it is absent, because "the exchange
  published no regular OHLC" and "we never observed this security" are
  different facts with different consequences.

* **Activity is not tradability.** A row with turnover but no OHLC is
  recorded as exactly that. Deciding whether it could have been traded is
  M3.6's job, using market status as well.

* **An action is usable only once it was announced.** `announced_at` is kept
  separate from the effective date, and where the publisher gives no
  announcement date the row is marked so a later stage cannot quietly assume
  the effective date was knowable in advance.
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

SCHEMA_ID = "tw-alpha-m3-prices-actions/1.0.0"
PRICE_SOURCES = {"TWSE-PRICE-HIST": "TWSE", "TPEX-PRICE-HIST": "TPEX"}
ACTION_SOURCES = {"TWSE-ACTIONS-HIST": "TWSE"}
WINDOW = (date(2025, 1, 1), date(2026, 8, 3))

OHLC_COMPLETE = "complete"
OHLC_SOURCE_NO_REGULAR = "source-reported-no-regular-ohlc"
OHLC_ACTIVITY_ONLY = "activity-without-ohlc"
OHLC_ABSENT = "no-price-fields-published"


def sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_index(staging: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (staging / "staging_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_manifest_index(staging: Path) -> dict[str, Path]:
    return {
        manifest.parent.name: manifest
        for manifest in (staging / "parsed_observations").rglob("parse_manifest.json")
    }


def parsed_rows(manifest_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    manifest = json.loads(manifest_path.read_bytes())
    rows_path = manifest.get("rows_path")
    if not rows_path:
        return [], []
    table = pq.read_table(manifest_path.parent / str(rows_path))
    return table.to_pylist(), list(table.column_names)


def first_present(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def classify_ohlc(row: dict[str, Any]) -> str:
    ohlc = [
        first_present(row, "open", "open_price"),
        first_present(row, "high", "high_price"),
        first_present(row, "low", "low_price"),
        first_present(row, "close", "close_price"),
    ]
    if all(value is not None for value in ohlc):
        return OHLC_COMPLETE
    activity = first_present(row, "volume", "trade_volume", "turnover", "trade_value")
    if activity not in (None, "", 0, "0"):
        return OHLC_ACTIVITY_ONLY
    if any(value is not None for value in ohlc):
        return OHLC_SOURCE_NO_REGULAR
    return OHLC_ABSENT


def build_prices(staging: Path, index: list[dict[str, Any]], manifests: dict[str, Path]):
    rows: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    columns_seen: set[str] = set()
    lo, hi = WINDOW
    for record in index:
        market = PRICE_SOURCES.get(record["source_id"])
        if not market:
            continue
        period = str(record["logical_period"])
        if not period.startswith("session:"):
            continue
        session = date.fromisoformat(period.split(":", 1)[1])
        if not (lo <= session <= hi):
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        source_rows, columns = parsed_rows(manifest_path)
        columns_seen.update(columns)
        for ordinal, source_row in enumerate(source_rows):
            symbol = str(first_present(source_row, "symbol", "security_id", "code") or "").strip()
            if not symbol:
                continue
            state = classify_ohlc(source_row)
            state_counts[state] = state_counts.get(state, 0) + 1
            rows.append(
                {
                    "market": market,
                    "session_date": session.isoformat(),
                    "symbol": symbol,
                    "open": first_present(source_row, "open", "open_price"),
                    "high": first_present(source_row, "high", "high_price"),
                    "low": first_present(source_row, "low", "low_price"),
                    "close": first_present(source_row, "close", "close_price"),
                    "volume": first_present(source_row, "volume", "trade_volume"),
                    "turnover": first_present(source_row, "turnover", "trade_value"),
                    "ohlc_state": state,
                    "activity_scope": "regular-session",
                    "price_basis": "raw-official-unadjusted",
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "quality_run_id": record.get("quality_run_id") or "",
                    "quality_decision": record.get("quality_decision") or "",
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    for row in rows:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("market", "session_date", "symbol", "snapshot_id")}
        )
    rows.sort(key=lambda r: (r["session_date"], r["market"], r["symbol"]))
    return rows, state_counts, sorted(columns_seen)


def build_actions(staging: Path, index: list[dict[str, Any]], manifests: dict[str, Path]):
    rows: list[dict[str, Any]] = []
    missing_announcement = 0
    for record in index:
        market = ACTION_SOURCES.get(record["source_id"])
        if not market:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        source_rows, _columns = parsed_rows(manifest_path)
        for ordinal, source_row in enumerate(source_rows):
            symbol = str(first_present(source_row, "symbol", "security_id", "code") or "").strip()
            if not symbol:
                continue
            effective = first_present(source_row, "action_date", "ex_date", "date")
            announced = first_present(source_row, "announced_at", "announcement_date")
            if announced is None:
                missing_announcement += 1
            rows.append(
                {
                    "market": market,
                    "symbol": symbol,
                    "effective_date": str(effective) if effective else "",
                    "announced_at": str(announced) if announced else "",
                    # Without a publisher announcement date the earliest
                    # defensible knowledge time is our own first observation.
                    "availability_basis": (
                        "publisher-exact" if announced else "first-observed-only"
                    ),
                    "reference_price": first_present(
                        source_row, "reference_price", "ex_reference_price"
                    ),
                    "prior_close": first_present(source_row, "prior_close", "pre_close"),
                    "limit_up": first_present(source_row, "limit_up", "limit_up_price"),
                    "limit_down": first_present(source_row, "limit_down", "limit_down_price"),
                    "adjustment_evidence": "publisher-reference-price",
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    for row in rows:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("market", "symbol", "effective_date", "snapshot_id")}
        )
    rows.sort(key=lambda r: (r["effective_date"], r["market"], r["symbol"]))
    return rows, missing_announcement


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
    manifests = parse_manifest_index(staging_root)

    prices, ohlc_states, columns = build_prices(staging_root, index, manifests)
    actions, missing_announcement = build_actions(staging_root, index, manifests)

    price_sha = write(out_root / "daily_prices_pit.parquet", prices)
    action_sha = write(out_root / "corporate_actions_pit.parquet", actions)

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "staging_dataset_id": json.loads(
            (staging_root / "dataset_manifest.json").read_bytes()
        )["dataset_id"],
        "window": {"start": WINDOW[0].isoformat(), "end": WINDOW[1].isoformat()},
        "daily_prices_pit": {
            "rows": len(prices),
            "sha256": price_sha,
            "ohlc_state_counts": dict(sorted(ohlc_states.items())),
            "distinct_sessions": len({r["session_date"] for r in prices}),
            "distinct_symbols": len({(r["market"], r["symbol"]) for r in prices}),
            "source_columns_seen": columns,
        },
        "corporate_actions_pit": {
            "rows": len(actions),
            "sha256": action_sha,
            "missing_announcement_date": missing_announcement,
            "distinct_symbols": len({(r["market"], r["symbol"]) for r in actions}),
            "markets": sorted({r["market"] for r in actions}),
        },
        "notes": [
            "Prices are raw official and unadjusted; no adjusted series is "
            "derived here, and none may be without a documented method.",
            "Missing OHLC is preserved with a reason and never filled.",
            "TPEx corporate actions come from MOPS per-symbol documents and "
            "are not in this table yet; they remain in staging.",
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
