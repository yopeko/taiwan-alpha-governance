"""Split the research dataset into a development half and a sealed half.

The nested validation contract's section 2 in executable form. A rule saying
"do not look at the sealed period" is a rule about a person's discipline; a
development dataset that physically lacks those rows cannot produce results
for them, whatever anyone intends.

The boundary is 2025-01-01, a calendar year rather than a percentage. 20%,
25% and 30% can all be argued for, and anything that can be argued for can be
argued again once the results are in.

What is sealed is outcomes, not price history. The development file keeps
every session up to 2024-12-31, which is all the warmup a candidate needs to
start trading on the first sealed session -- a 252-session momentum score for
2025-01-02 reads 2024 prices, and those were known on the day. Sealing them
too would cost 252 of the 382 sealed sessions and buy nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))

from current_build import RESEARCH_DATASET  # noqa: E402

SPLIT_VERSION = "sealed-split-2025-01-01/1.0.0"
SEAL_FROM = "2025-01-01"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split(source: Path, out_root: Path) -> dict:
    table = pq.read_table(source / "research_dataset.parquet")
    sessions = table.column("session_date")

    development = table.filter(pc.less(sessions, SEAL_FROM))
    sealed = table.filter(pc.greater_equal(sessions, SEAL_FROM))

    if development.num_rows == 0 or sealed.num_rows == 0:
        raise SystemExit(
            f"the boundary {SEAL_FROM} leaves one side empty "
            f"(development={development.num_rows}, sealed={sealed.num_rows}); "
            "a split that seals everything or nothing is not a split"
        )

    source_manifest = json.loads((source / "dataset_manifest.json").read_bytes())
    written = {}
    for name, part in (("development", development), ("sealed", sealed)):
        root = out_root / name
        root.mkdir(parents=True, exist_ok=True)
        path = root / "research_dataset.parquet"
        pq.write_table(part, path)
        dates = sorted(set(part.column("session_date").to_pylist()))
        manifest = {
            "schema_id": "tw-alpha-m7-split/1.0.0",
            "split_version": SPLIT_VERSION,
            "segment": name,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "rows": part.num_rows,
            "sessions": len(dates),
            "window": {"start": dates[0], "end": dates[-1]},
            "sha256": digest(path),
            "source_dataset_root": str(source),
            "source_dataset_sha256": source_manifest.get("sha256"),
            "warehouse_dataset_id": source_manifest.get("warehouse_dataset_id"),
            "reading_note": (
                "Nested validation contract section 3.3: a candidate evaluated "
                "on the sealed segment may not then be adjusted. Any parameter "
                "change after an opening makes a new candidate whose "
                "development work starts again."
                if name == "sealed"
                else "Development segment. Every session here is fair game for "
                "selection, tuning and discarding. Nothing after "
                f"{SEAL_FROM} is present, so nothing after it can be selected on."
            ),
        }
        (root / "dataset_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        written[name] = manifest
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=RESEARCH_DATASET)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    written = split(args.dataset, args.out)
    for name, manifest in written.items():
        print(
            f"{name:<12} {manifest['rows']:>9,} 列  {manifest['sessions']:>5} 場次  "
            f"{manifest['window']['start']} → {manifest['window']['end']}"
        )
        print(f"             {manifest['sha256'][:16]}…")
    print(f"\n切分版本 {SPLIT_VERSION}")
    print(f"寫入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
