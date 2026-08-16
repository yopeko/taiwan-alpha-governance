from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq


ROOT = Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03")
TEMPORAL_COLUMNS = {
    "date",
    "session_date",
    "listed_at",
    "event_date",
    "action_date",
    "period_end",
    "available_at",
    "announced_at",
    "published_at",
    "effective_date",
}


def normalized(value: object) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def main() -> None:
    raw_by_snapshot = {}
    for path in (ROOT / "raw_observations").glob("**/manifest.json"):
        manifest = json.loads(path.read_bytes())
        raw_by_snapshot[str(manifest["snapshot_id"])] = manifest

    grouped = defaultdict(
        lambda: {
            "observations": 0,
            "rows": 0,
            "rejects": 0,
            "parser_ids": set(),
            "endpoint_ids": set(),
            "columns": set(),
            "logical_periods": set(),
            "fetched_at": [],
            "temporal": defaultdict(list),
        }
    )
    for path in (ROOT / "parsed_observations").glob("**/parse_manifest.json"):
        manifest = json.loads(path.read_bytes())
        source_id = str(manifest["source_id"])
        item = grouped[source_id]
        item["observations"] += 1
        item["rows"] += int(manifest["row_count"])
        item["rejects"] += int(manifest["reject_count"])
        item["parser_ids"].add(str(manifest["parser_id"]))
        item["endpoint_ids"].add(str(manifest["endpoint_id"]))
        item["logical_periods"].add(str(manifest["logical_period"]))
        raw = raw_by_snapshot[str(manifest["snapshot_id"])]
        item["fetched_at"].append(str(raw["fetched_at"]))

        table = pq.read_table(path.parent / str(manifest["rows_path"]))
        item["columns"].update(table.column_names)
        for column_name in TEMPORAL_COLUMNS & set(table.column_names):
            values = [
                normalized(value)
                for value in table[column_name].to_pylist()
                if value is not None
            ]
            item["temporal"][column_name].extend(values)

    output = {}
    for source_id, item in sorted(grouped.items()):
        output[source_id] = {
            "observations": item["observations"],
            "rows": item["rows"],
            "rejects": item["rejects"],
            "parser_ids": sorted(item["parser_ids"]),
            "endpoint_ids": sorted(item["endpoint_ids"]),
            "columns": sorted(item["columns"]),
            "logical_period_count": len(item["logical_periods"]),
            "fetched_at": {
                "min": min(item["fetched_at"]),
                "max": max(item["fetched_at"]),
            },
            "temporal": {
                name: {"min": min(values), "max": max(values), "non_null": len(values)}
                for name, values in sorted(item["temporal"].items())
                if values
            },
            "has_row_available_at": "available_at" in item["columns"],
        }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
