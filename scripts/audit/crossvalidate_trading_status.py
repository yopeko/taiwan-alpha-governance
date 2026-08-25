"""Official trading-status lists against the vendor lifecycle (D11).

Until this capture, every delisting in the warehouse was a TEJ claim carrying
`licensed-vendor-snapshot`, and every suspension was
`suspension-inferred-from-price-absence` -- a policy inference. Both exchanges
publish the facts; nobody had asked them.

    python scripts/audit/crossvalidate_trading_status.py \\
        --capture-root C:/tmp/tw-alpha-m3-trading-status-01

Three questions:

  delisting   Do the exchanges' own lists agree with the vendor on which
              securities delisted, and on which date?
  suspension  Which securities do the exchanges currently flag as suspended
              or on altered trading, and does the warehouse say the same?
  gaps        Which securities stopped being quoted, are on neither delisting
              list, and are therefore suspended rather than gone?
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
from typing import Any

WINDOW = ("2025-01-02", "2026-08-03")


def roc_to_iso(value: str) -> str:
    """Both lists date in ROC years, in two different punctuations."""

    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def payloads(capture_root: Path) -> dict[str, Any]:
    """Every captured observation, keyed by source id."""

    out: dict[str, Any] = {}
    for manifest_path in (capture_root / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        blob = manifest.get("blob_id") or manifest.get("payload_sha256")
        if not blob:
            continue
        path = (
            capture_root / "raw_blobs" / "sha256" / blob[:2] / blob / "payload.bin"
        )
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = gzip.decompress(raw).decode("utf-8")
        except (OSError, gzip.BadGzipFile):
            text = raw.decode("utf-8", "replace")
        out[str(manifest["source_id"])] = json.loads(text)
    return out


def official_delistings(data: dict[str, Any]) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in data.get("TWSE-DELISTING") or []:
        out[("TWSE", str(row["Code"]))] = {
            "date": roc_to_iso(row["DelistingDate"]),
            "name": str(row.get("Company") or ""),
            "reason": "",
        }
    tables = (data.get("TPEX-DELISTING-HIST") or {}).get("tables") or []
    for row in (tables[0].get("data") if tables else []) or []:
        out[("TPEX", str(row[0]))] = {
            "date": roc_to_iso(row[2]),
            "name": str(row[1]),
            # The exchange cites the rule it acted under. A delisting for a
            # board transfer and one for financial failure are different
            # facts, and only the reason distinguishes them.
            "reason": str(row[3])[:80],
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    # Defaults from current_build. Written as literals they named the
    # 2025-2026 generation, and a default is what almost every run uses.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m3"))
    from current_build import CALENDAR, PRICES

    parser.add_argument(
        "--lifecycle",
        type=Path,
        default=CALENDAR / "security_intervals.csv",
    )
    parser.add_argument(
        "--prices",
        type=Path,
        default=PRICES / "daily_prices_pit.parquet",
    )
    args = parser.parse_args(argv)

    data = payloads(args.capture_root)
    print("captured sources:", ", ".join(sorted(data)))
    official = official_delistings(data)

    with args.lifecycle.open(encoding="utf-8") as handle:
        vendor = {
            (row["market"], row["symbol"]): row for row in csv.DictReader(handle)
        }

    print()
    print("=" * 70)
    print("1. DELISTING: exchange vs vendor, inside the window")
    print("=" * 70)
    inside = {
        key: row for key, row in official.items() if WINDOW[0] <= row["date"] <= WINDOW[1]
    }
    agree = disagree = vendor_silent = 0
    for key, row in sorted(inside.items(), key=lambda kv: kv[1]["date"]):
        theirs = (vendor.get(key) or {}).get("delisting_date") or ""
        if not theirs:
            mark, vendor_silent = "VENDOR SILENT", vendor_silent + 1
        elif theirs == row["date"]:
            mark, agree = "agree", agree + 1
        else:
            mark, disagree = f"DISAGREE vendor={theirs}", disagree + 1
        print(f"  {key[0]:5s} {key[1]:6s} {row['name'][:14]:16s} {row['date']}  {mark}")
        if row["reason"]:
            print(f"        {row['reason']}")
    print()
    print(f"  agree {agree}   disagree {disagree}   vendor silent {vendor_silent}")

    print()
    print("=" * 70)
    print("2. SUSPENSION AND ALTERED TRADING, as the exchanges flag it today")
    print("=" * 70)
    suspended: set[tuple[str, str]] = set()
    altered: set[tuple[str, str]] = set()
    for row in data.get("TWSE-TRADING-ALTERED-TRADING") or []:
        altered.add(("TWSE", str(row["Code"])))
    for row in data.get("TPEX-TRADING-ALTERED-TRADING") or []:
        key = ("TPEX", str(row["SecuritiesCompanyCode"]))
        if str(row.get("AlteredTrading") or "").strip():
            altered.add(key)
        if str(row.get("SuspensionOfTrading") or "").strip():
            suspended.add(key)
    print(f"  altered trading (變更交易): {len(altered)}  {sorted(altered)}")
    print(f"  suspended (停止交易):       {len(suspended)}  {sorted(suspended)}")
    print("  TWSE publishes no long-term suspension list; only TPEx flags it.")

    print()
    print("=" * 70)
    print("3. STOPPED BEING QUOTED, AND NOT ON EITHER DELISTING LIST")
    print("=" * 70)
    import pyarrow.parquet as pq

    table = pq.read_table(args.prices, columns=["market", "symbol", "session_date"])
    last: dict[tuple[str, str], str] = {}
    for market, symbol, session in zip(
        table["market"].to_pylist(),
        table["symbol"].to_pylist(),
        table["session_date"].to_pylist(),
    ):
        key = (market, symbol)
        if session > last.get(key, ""):
            last[key] = session
    stale = {k: v for k, v in last.items() if v < "2026-06-15"}
    for key, when in sorted(stale.items(), key=lambda kv: kv[1]):
        if key in official:
            continue
        verdict = "OFFICIALLY SUSPENDED" if key in suspended else "no official record"
        print(f"  {key[0]:5s} {key[1]:6s} last quote {when}   {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
