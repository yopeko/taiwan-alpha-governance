"""Every TPEx symbol the exchange printed a quote for during one year.

`capture_tpex_actions` needs a symbol list before it can start, because MOPS
answers one symbol-year at a time. Where that list comes from decides what the
capture can ever find, and `derive_tpex_action_universe` records why: the
2024-2026 lane used today's membership, and asking today's list about 2019
would have missed 55 names that traded in the window and have since delisted.

So the list is the union of everything that had a printed close in the year,
across every price table given -- not today's membership, and not one table's.

A monthly refresh of the current year is the case this was written for. The
existing 2024-2026 lane holds announcements captured up to late August; the
capture skips symbol-years it already has, so picking up September's
announcements means a fresh output root and the whole year re-queried. This
produces the list that run needs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def symbols_in_year(roots: list[Path], year: str) -> list[str]:
    import pyarrow.parquet as pq

    found: set[str] = set()
    for root in roots:
        path = root / "daily_prices_pit.parquet"
        if not path.is_file():
            path = root / "research_dataset.parquet"
        if not path.is_file():
            raise SystemExit(f"no price table in {root}")
        table = pq.read_table(
            path, columns=["market", "symbol", "session_date", "close"]
        )
        for row in table.to_pylist():
            if (
                row["market"] == "TPEX"
                and row["close"] is not None
                and str(row["session_date"]).startswith(year)
            ):
                found.add(str(row["symbol"]))
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices-root",
        type=Path,
        action="append",
        required=True,
        help="repeatable; every table that covers part of the year",
    )
    parser.add_argument("--year", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    symbols = symbols_in_year(args.prices_root, args.year)
    if not symbols:
        raise SystemExit(
            f"no TPEx symbols with a printed close in {args.year} across "
            f"{[str(r) for r in args.prices_root]}. An empty list would make "
            f"the capture do nothing and report success"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(symbols, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{args.year}  {len(symbols)} 檔 TPEx  ->  {args.out}")
    print(f"  來源 {[str(r) for r in args.prices_root]}")
    print(f"  約 {len(symbols)} 次列表查詢，加每則公告一次明細")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
