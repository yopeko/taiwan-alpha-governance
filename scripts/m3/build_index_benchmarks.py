"""The official index closes, from blobs that were already on disk.

M0 section 9.1 requires every challenger to be compared against, among other
things, "an appropriate market index or ETF benchmark". Nothing implemented
it, and the backtester's only arms were momentum, inverse volatility and
twenty random seeds.

WHY NOT THE ETF

0050 is in the research dataset with 1,857 closes, which makes it look like
the cheap answer. It is not:

* it **split 1:4 on 2025-06-18** (188.65 -> 47.57) and the corporate-action
  table has no split for it, because Owner decisions D1/D3 put ETFs out of
  M3's scope. A buy-and-hold return across that session reads as -75%;
* it pays dividends the unadjusted price series does not carry.

Neither is a warehouse defect -- M3 never claimed to cover ETF actions -- but
both make the ETF unusable as a benchmark without work M3 has not done.

The index has neither problem. It does not split, and the exchange publishes
the total-return series alongside the price series.

WHERE THE DATA WAS

Already captured. `MI_INDEX` is the endpoint the six-year price history came
from, and TWSE returns ten tables in one response. Staging parses table 8,
the closing quotations. Tables 0 and 3 -- the price and total-return index
boards -- were in every blob the whole time, hash-verified and archived under
the M2 retention rules.

So this builder captures nothing. It re-reads archives read-only, verifies
each blob against the hash the observation recorded, and parses the two tables
staging leaves alone.

WHY BOTH BASES ARE WRITTEN

The research dataset uses official **unadjusted** closes, so a strategy run on
it does not receive dividends. Compared against a total-return index it would
lose by the dividend yield of the whole market and the gap would read as
underperformance.

Compared against the price index the two are consistent -- but then neither
number is what the market actually paid.

Both are therefore written, labelled, and it is the caller's job to say which
it used. The same lesson the discretionary contract learned on 2026-09-03,
when its equal-weight benchmark turned out to be measuring the fee schedule:
a benchmark that is wrong in the flattering direction is the expensive kind.

WHY THIS DOES NOT GO THROUGH STAGING

The parser registry lives in Taiwan Core. This lane reads the same archives,
verifies the same hashes and carries the same lineage, and adding it here
needed no change to a repository that currently has 120 uncommitted files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA_ID = "tw-alpha-m3-index-benchmarks/1.0.0"
SOURCE_ID = "TWSE-PRICE-HIST"

# Title of the board, and the basis every row parsed from it carries. Matched
# on a substring because the exchange prefixes the first one with the ROC date
# ("115年06月30日 價格指數(臺灣證券交易所)") and not the others.
BOARDS = (
    ("價格指數(臺灣證券交易所)", "price"),
    ("報酬指數(臺灣證券交易所)", "total-return"),
)

# The two families M0 section 9.1 can be satisfied with, and their two bases.
# Named rather than taken wholesale: the board carries fifty-odd indices and a
# benchmark nobody chose in advance is a benchmark chosen after the fact.
WANTED = {
    "發行量加權股價指數": ("TAIEX", "price"),
    "發行量加權股價報酬指數": ("TAIEX", "total-return"),
    "臺灣50指數": ("TW50", "price"),
    "臺灣50報酬指數": ("TW50", "total-return"),
    # 2019-04-29 only. On that one session out of 1,862 the exchange printed
    # the short labels -- `寶島指數` for `寶島股價指數` on the same board -- and
    # TAIEX came out of the first build with 1,861 sessions against TW50's
    # 1,862.
    #
    # Checked rather than assumed to be the same index: 10,939.06 that day
    # sits between 10,952.47 on 04-26 and 10,967.73 on 04-30, and the
    # total-return label moved with it. A benchmark missing one session in the
    # middle is the kind of hole that reads as a real move.
    "加權股價指數": ("TAIEX", "price"),
    "加權股價報酬指數": ("TAIEX", "total-return"),
}

SCHEMA = pa.schema(
    [
        pa.field("index_id", pa.string(), nullable=False),
        pa.field("index_name", pa.string(), nullable=False),
        pa.field("basis", pa.string(), nullable=False),
        pa.field("session_date", pa.string(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("board_title", pa.string(), nullable=False),
        pa.field("source_id", pa.string(), nullable=False),
        pa.field("snapshot_id", pa.string(), nullable=False),
        pa.field("blob_sha256", pa.string(), nullable=False),
        pa.field("evidence_state", pa.string(), nullable=False),
    ]
)


def number(text: str) -> Decimal | None:
    """The exchange prints thousands separators and marks absence with a dash."""

    cleaned = str(text).replace(",", "").replace("−", "-").strip()
    if cleaned in {"", "-", "--", "---", "N/A"}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def observations(
    archive: Path, sources: tuple[str, ...] = (SOURCE_ID,)
) -> list[tuple[Path, dict[str, Any]]]:
    """Every observation in an archive belonging to the given sources.

    `sources` defaults to this module's own, so existing callers are
    unchanged; the institutional lane passes its two.
    """

    wanted = set(sources)
    found = []
    for path in sorted((archive / "raw_observations").rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("source_id") in wanted:
            found.append((path, record))
    return found


def blob_for(archive: Path, record: dict[str, Any]) -> bytes:
    blob_id = record["blob_id"]
    path = archive / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = record.get("payload_sha256")
    if expected and digest != expected:
        raise SystemExit(
            f"{path} hashes to {digest}, the observation recorded {expected}. "
            f"An archive that does not verify is not evidence"
        )
    return raw


def rows_from(record: dict[str, Any], payload: bytes) -> list[dict[str, Any]]:
    period = str(record.get("logical_period") or "")
    if not period.startswith("session:"):
        return []
    session = period.split(":", 1)[1]

    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # A non-trading day answers with something that is not this document.
        # Not an error: the response was preserved as evidence and carries no
        # index board, which is the correct answer for a day with no session.
        return []

    tables = document.get("tables")
    if not isinstance(tables, list):
        return []

    out: list[dict[str, Any]] = []
    for table in tables:
        title = str((table or {}).get("title") or "")
        basis = next((b for fragment, b in BOARDS if fragment in title), None)
        if basis is None:
            continue
        for row in table.get("data") or []:
            if not row:
                continue
            name = str(row[0]).strip()
            wanted = WANTED.get(name)
            if wanted is None:
                continue
            index_id, declared = wanted
            if declared != basis:
                # The name says one basis and the board it sits on says
                # another. Refused rather than guessed: this is the field that
                # decides whether a benchmark includes dividends.
                raise SystemExit(
                    f"{session}: {name!r} was found on the {basis!r} board but "
                    f"is registered as {declared!r}. One of the two is wrong "
                    f"and neither may be assumed"
                )
            close = number(row[1] if len(row) > 1 else "")
            if close is None:
                continue
            out.append(
                {
                    "index_id": index_id,
                    "index_name": name,
                    "basis": basis,
                    "session_date": session,
                    "close": float(close),
                    "board_title": title,
                    "source_id": SOURCE_ID,
                    "snapshot_id": str(record.get("snapshot_id") or ""),
                    "blob_sha256": str(record.get("payload_sha256") or ""),
                    "evidence_state": str(record.get("evidence_state") or ""),
                }
            )
    return out


def build(archives: list[Path], out_root: Path) -> dict[str, Any]:
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    stats = {"observations": 0, "with_index_board": 0, "no_board": 0}

    for archive in archives:
        if not archive.is_dir():
            raise SystemExit(f"not an archive root: {archive}")
        for _, record in observations(archive):
            stats["observations"] += 1
            produced = rows_from(record, blob_for(archive, record))
            if not produced:
                stats["no_board"] += 1
                continue
            stats["with_index_board"] += 1
            for row in produced:
                key = (row["index_id"], row["basis"], row["session_date"])
                if key in seen:
                    # Two archives overlapping on a session. The first wins and
                    # the second is dropped, which is safe only because both
                    # came from a hash-verified capture of the same publisher.
                    continue
                seen.add(key)
                rows.append(row)

    if not rows:
        raise SystemExit(
            f"no index rows from {[str(a) for a in archives]}. An empty table "
            f"would let a benchmark column read as present and be silent"
        )

    rows.sort(key=lambda r: (r["index_id"], r["basis"], r["session_date"]))
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / "index_benchmarks_pit.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path)

    series: dict[str, Any] = {}
    for row in rows:
        key = f"{row['index_id']}:{row['basis']}"
        entry = series.setdefault(
            key, {"sessions": 0, "first": row["session_date"], "last": row["session_date"]}
        )
        entry["sessions"] += 1
        entry["last"] = max(entry["last"], row["session_date"])
        entry["first"] = min(entry["first"], row["session_date"])

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "archives": [str(a) for a in archives],
        "rows": len(rows),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "series": dict(sorted(series.items())),
        **stats,
        "notes": [
            "Captured nothing. Re-reads M2/M3 archives read-only and verifies "
            "every blob against the hash its observation recorded.",
            "Both bases are written. The research dataset carries unadjusted "
            "closes, so a strategy run on it receives no dividends and is "
            "consistent with the price index, not the total-return one. "
            "Whichever a report uses, it has to say which.",
            "0050 is deliberately not used. It split 1:4 on 2025-06-18 and "
            "M3 does not cover ETF corporate actions, so a buy-and-hold "
            "return across that session reads as -75%. 臺灣50報酬指數 is the "
            "same exposure without the gap.",
        ],
    }
    (out_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        action="append",
        required=True,
        dest="archives",
        help="repeatable; an M2/M3 archive root holding TWSE-PRICE-HIST",
    )
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.archives, args.out_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
