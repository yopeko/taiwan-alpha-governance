"""M4: derive tick sizes and price limits, separating ETFs and corporate actions.

v1 pooled every four-digit code, which mixed ETFs (00xx) into the common-stock
bands even though ETFs use a finer tick table, and counted ex-right price gaps
as if they were ordinary daily moves.

v2 splits ETFs out and cross-checks every apparent price-limit breach against
the ex-right / ex-dividend records captured in M3.1e.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
WINDOW = RAW / "m3_window_2025-01-01_2026-08-03"
ACTIONS = RAW / "m3_actions_2025-01-01_2026-08-03"

BANDS = [
    (Decimal("0"), Decimal("10")),
    (Decimal("10"), Decimal("50")),
    (Decimal("50"), Decimal("100")),
    (Decimal("100"), Decimal("500")),
    (Decimal("500"), Decimal("1000")),
    (Decimal("1000"), Decimal("1000000")),
]
LIMIT = Decimal("0.10")
TOLERANCE = Decimal("0.0005")


def blob_text(root: Path, blob_id: str) -> str:
    blob = root / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
    raw = blob.read_bytes()
    try:
        return gzip.decompress(raw).decode("utf-8")
    except (OSError, gzip.BadGzipFile):
        return raw.decode("utf-8-sig", errors="replace")


def to_decimal(value: object) -> Decimal | None:
    text = str(value).replace(",", "").strip()
    if not text or text in {"--", "-", "N/A"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def band_of(price: Decimal) -> tuple[Decimal, Decimal] | None:
    for lo, hi in BANDS:
        if lo <= price < hi:
            return (lo, hi)
    return None


def parse_roc_any(text: str) -> str | None:
    """Accept 114年08月01日, 114/08/01 and 1140801."""

    digits = "".join(ch for ch in str(text) if ch.isdigit())
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None


def load_action_dates() -> tuple[set[tuple[str, str]], dict[str, object]]:
    """(symbol, date) pairs plus a direct check of the official limit prices."""

    pairs: set[tuple[str, str]] = set()
    limit_rows = 0
    limit_matches = 0
    limit_mismatch: list[dict[str, str]] = []
    for path in (ACTIONS / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(path.read_bytes())
        payload = json.loads(blob_text(ACTIONS, str(manifest["blob_id"])))
        fields = [str(f) for f in (payload.get("fields") or [])]
        rows = payload.get("data")
        if not isinstance(rows, list) or not fields:
            continue
        date_i = next((i for i, f in enumerate(fields) if "資料日期" in f), None)
        code_i = next((i for i, f in enumerate(fields) if "股票代號" in f), None)
        ref_i = next((i for i, f in enumerate(fields) if "除權息參考價" in f), None)
        up_i = next((i for i, f in enumerate(fields) if "漲停價格" in f), None)
        down_i = next((i for i, f in enumerate(fields) if "跌停價格" in f), None)
        if date_i is None or code_i is None:
            continue
        for row in rows:
            if len(row) <= max(date_i, code_i):
                continue
            iso = parse_roc_any(row[date_i])
            if not iso:
                continue
            pairs.add((str(row[code_i]).strip(), iso))

            # The publisher states the limit prices explicitly, so the +/-10%
            # rule can be checked directly instead of inferred from moves.
            if None in (ref_i, up_i, down_i) or len(row) <= max(ref_i, up_i, down_i):
                continue
            ref = to_decimal(row[ref_i])
            up = to_decimal(row[up_i])
            down = to_decimal(row[down_i])
            if not (ref and up and down) or ref <= 0:
                continue
            limit_rows += 1
            up_pct = (up - ref) / ref
            down_pct = (ref - down) / ref
            if abs(up_pct - LIMIT) <= Decimal("0.006") and abs(
                down_pct - LIMIT
            ) <= Decimal("0.006"):
                limit_matches += 1
            elif len(limit_mismatch) < 8:
                limit_mismatch.append(
                    {
                        "symbol": str(row[code_i]).strip(),
                        "date": iso,
                        "reference": str(ref),
                        "limit_up": str(up),
                        "limit_down": str(down),
                        "up_pct": f"{up_pct * 100:.2f}",
                        "down_pct": f"{down_pct * 100:.2f}",
                    }
                )
    return pairs, {
        "rows_with_official_limit_prices": limit_rows,
        "consistent_with_10pct": limit_matches,
        "inconsistent": limit_rows - limit_matches,
        "inconsistent_sample": limit_mismatch,
    }


def main() -> None:
    sessions: list[tuple[str, str]] = []
    for path in (WINDOW / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(path.read_bytes())
        period = str(manifest["logical_period"])
        if period.startswith("session:") and "TWSE" in str(path):
            sessions.append((period.split(":", 1)[1], str(manifest["blob_id"])))
    sessions.sort()

    granularity: dict[str, dict[tuple[Decimal, Decimal], set[Decimal]]] = {
        "common": defaultdict(set),
        "etf": defaultdict(set),
    }
    series: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)

    for day, blob_id in sessions:
        payload = json.loads(blob_text(WINDOW, blob_id))
        tables = [
            t for t in payload.get("tables", [])
            if isinstance(t.get("data"), list) and t["data"]
        ]
        if not tables:
            continue
        table = max(tables, key=lambda t: len(t["data"]))
        fields = [str(f) for f in (table.get("fields") or [])]
        try:
            code_i = next(i for i, f in enumerate(fields) if "證券代號" in f)
            close_i = next(i for i, f in enumerate(fields) if "收盤價" in f)
        except StopIteration:
            continue
        for row in table["data"]:
            if len(row) <= max(code_i, close_i):
                continue
            symbol = str(row[code_i]).strip()
            if not (symbol.isdigit() and len(symbol) == 4):
                continue
            close = to_decimal(row[close_i])
            if close is None or close <= 0:
                continue
            kind = "etf" if symbol.startswith("00") else "common"
            band = band_of(close)
            if band:
                granularity[kind][band].add(close)
            if kind == "common":
                series[symbol].append((day, close))

    tick_report: dict[str, dict[str, object]] = {}
    for kind in ("common", "etf"):
        entry: dict[str, object] = {}
        for band in BANDS:
            values = sorted(granularity[kind].get(band, set()))
            if len(values) < 2:
                entry[f"{band[0]}~{band[1]}"] = {"distinct": len(values), "tick": None}
                continue
            diffs = {values[i + 1] - values[i] for i in range(len(values) - 1)}
            diffs.discard(Decimal("0"))
            entry[f"{band[0]}~{band[1]}"] = {
                "distinct": len(values),
                "tick": str(min(diffs)),
            }
        tick_report[kind] = entry

    action_pairs, limit_check = load_action_dates()
    breaches: list[dict[str, object]] = []
    total_moves = 0
    for symbol, points in series.items():
        points.sort()
        for i in range(1, len(points)):
            _, prev = points[i - 1]
            day, close = points[i]
            if prev <= 0:
                continue
            total_moves += 1
            move = (close - prev) / prev
            if abs(move) > LIMIT + TOLERANCE:
                breaches.append(
                    {
                        "symbol": symbol,
                        "date": day,
                        "move_pct": f"{move * 100:.2f}",
                        "explained_by_corporate_action": (symbol, day) in action_pairs,
                    }
                )

    explained = sum(1 for b in breaches if b["explained_by_corporate_action"])
    report = {
        "sessions": len(sessions),
        "common_stock_symbols": len(series),
        "tick_by_band": tick_report,
        "official_limit_price_check": limit_check,
        "price_limit_check": {
            "daily_moves_examined": total_moves,
            "breaches_beyond_10pct": len(breaches),
            "breach_rate": f"{len(breaches) / total_moves * 100:.4f}%"
            if total_moves
            else None,
            "explained_by_captured_corporate_action": explained,
            "unexplained": len(breaches) - explained,
            "corporate_action_pairs_loaded": len(action_pairs),
        },
        "unexplained_sample": [
            b for b in breaches if not b["explained_by_corporate_action"]
        ][:15],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
