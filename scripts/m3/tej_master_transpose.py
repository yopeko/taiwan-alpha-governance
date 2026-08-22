"""Turn a TEJ company-master export into the wide form `tej_import.py` reads.

TEJ's 公司基本資料 export is one security per file, laid out as label/value
pairs down a column. The importer reads tables, so this transposes the pairs
into a single wide row and leaves every downstream rule -- date normalisation,
market mapping, board-column folding, rejection -- to the importer that
already has them.

Why this exists at all. The lifecycle table was built from a TEJ *financial
statements* export, so its universe is "securities that filed a financial
statement in the queried periods". 3202 樺晟 filed none: its own TEJ record
gives 危機事件 = 財報未出具或遲交, and failing to file is what got it
delisted. A company that stops filing disappears from a filings export, and
the thing that makes it disappear is the thing a backtest most needs to see.
The company master is keyed on the company existing, not on it reporting.

    python scripts/m3/tej_master_transpose.py EXPORT.xlsx --out rows.csv

Market is derived, not asserted, and only when the evidence is unambiguous:
exactly one board listing date present. A security with both a TSE and an OTC
listing date transferred between boards and needs one row per leg, which is a
judgement this script refuses to make silently.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

import openpyxl

# TEJ label -> the column name `tej_import.py` already knows how to find.
FIELDS = {
    "下市日期": "下市日期",
    "TSE上市日": "TSE上市日",
    "OTC上市日": "OTC上市日",
    "公司中文簡稱": "證券名稱",
}

# Board columns, in the order a market is derived from them.
BOARDS = (("TSE上市日", "TSE"), ("OTC上市日", "OTC"), ("創新版上市日", "TIB"))

NULL = {"", ".", "-", "na", "n/a", "none", "null"}


def read_pairs(path: Path) -> tuple[str, dict[str, str]]:
    """Return (title cell, {label: value}) from a key/value export."""

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book.worksheets[0]
    title = ""
    pairs: dict[str, str] = {}
    for row in sheet.iter_rows(values_only=True):
        cells = [("" if cell is None else str(cell)).strip() for cell in row]
        if not any(cells):
            continue
        if not title:
            title = cells[0]
            continue
        if len(cells) >= 2 and cells[0]:
            pairs.setdefault(cells[0], cells[1])
    return title, pairs


def derive_market(pairs: dict[str, str]) -> tuple[str, str]:
    """Return (market, basis), or raise when the export cannot say."""

    present = [
        (label, board)
        for label, board in BOARDS
        if (pairs.get(label) or "").strip().lower() not in NULL
    ]
    if not present:
        raise SystemExit(
            "no board listing date in the export, so the market cannot be "
            "derived; supply --market explicitly if you have other evidence"
        )
    if len(present) > 1:
        boards = ", ".join(f"{label}={pairs[label]}" for label, _ in present)
        raise SystemExit(
            f"the export carries several board listing dates ({boards}). That "
            "is a board transfer and needs one row per leg with its own "
            "interval; refusing to collapse it into a single market"
        )
    label, board = present[0]
    return board, f"single-board-column:{label}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--market",
        help="override the derived market; recorded as operator-asserted",
    )
    args = parser.parse_args(argv)

    title, pairs = read_pairs(args.export)
    if not title:
        raise SystemExit("no title cell: the export does not name its security")

    if args.market:
        market, basis = args.market, "operator-asserted"
    else:
        market, basis = derive_market(pairs)

    row: dict[str, Any] = {"證券代碼": title, "市場別": market}
    for label, column in FIELDS.items():
        value = (pairs.get(label) or "").strip()
        row[column] = "" if value.lower() in NULL else value

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    print(f"{title} -> {market} ({basis})")
    for column, value in row.items():
        print(f"  {column}: {value!r}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
