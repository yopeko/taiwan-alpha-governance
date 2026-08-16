"""Inventory the logical periods available in the durable M2 archives."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOTS = {
    "m2_main": Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03"),
    "m2_dailyprice96": Path(
        r"C:\project\tw-sepa-screener\data\raw_v2\m2_dailyprice96_2026-08-03"
    ),
}


def main() -> None:
    output: dict[str, dict[str, object]] = {}
    for label, root in ROOTS.items():
        grouped: dict[str, dict[str, object]] = defaultdict(
            lambda: {"periods": set(), "endpoints": set(), "count": 0}
        )
        for path in (root / "raw_observations").rglob("manifest.json"):
            manifest = json.loads(path.read_bytes())
            key = str(manifest["endpoint_id"])
            item = grouped[key]
            item["periods"].add(str(manifest["logical_period"]))
            item["endpoints"].add(str(manifest.get("source_id", "")))
            item["count"] += 1
        output[label] = {
            endpoint: {
                "observations": item["count"],
                "period_count": len(item["periods"]),
                "periods": sorted(item["periods"])[:6],
                "period_min": min(item["periods"]),
                "period_max": max(item["periods"]),
            }
            for endpoint, item in sorted(grouped.items())
        }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
