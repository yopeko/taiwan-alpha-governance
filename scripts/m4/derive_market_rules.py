"""M4: derive Taiwan tick sizes and price limits from captured official data.

Rather than asserting the rule table from memory, this reads the 382 sessions
of official TWSE closing quotes captured in M3.1b and measures what the
exchange actually published: the observed price granularity in each price
band, and the observed distribution of daily moves against the previous close.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

WINDOW = Path(
    r"C:\project\tw-sepa-screener\data\raw_v2\m3_window_2025-01-01_2026-08-03"
)
# Candidate band edges for the published six-tier table.
BANDS = [
    (Decimal("0"), Decimal("10")),
    (Decimal("10"), Decimal("50")),
    (Decimal("50"), Decimal("100")),
    (Decimal("100"), Decimal("500")),
    (Decimal("500"), Decimal("1000")),
    (Decimal("1000"), Decimal("1000000")),
]


def blob_text(blob_id: str) -> str:
    blob = WINDOW / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
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


def main() -> None:
    sessions: list[tuple[str, str]] = []
    for path in (WINDOW / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(path.read_bytes())
        period = str(manifest["logical_period"])
        if period.startswith("session:") and "TWSE" in str(path):
            sessions.append((period.split(":", 1)[1], str(manifest["blob_id"])))
    sessions.sort()

    granularity: dict[tuple[Decimal, Decimal], set[Decimal]] = defaultdict(set)
    prices_by_symbol: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)
    observed_rows = 0

    for day, blob_id in sessions:
        payload = json.loads(blob_text(blob_id))
        tables = [
            t
            for t in payload.get("tables", [])
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
            observed_rows += 1
            band = band_of(close)
            if band:
                granularity[band].add(close)
            prices_by_symbol[symbol].append((day, close))

    # Tick size = smallest non-zero difference between distinct observed prices
    # inside a band. With hundreds of thousands of observations per band this
    # converges on the published tick.
    tick_report = {}
    for band in BANDS:
        values = sorted(granularity.get(band, set()))
        if len(values) < 2:
            tick_report[f"{band[0]}~{band[1]}"] = {
                "distinct_prices": len(values),
                "observed_tick": None,
            }
            continue
        diffs = {values[i + 1] - values[i] for i in range(len(values) - 1)}
        diffs.discard(Decimal("0"))
        tick_report[f"{band[0]}~{band[1]}"] = {
            "distinct_prices": len(values),
            "observed_tick": str(min(diffs)),
            "price_range": [str(values[0]), str(values[-1])],
        }

    # Daily move distribution against the previous observed close.
    moves: list[tuple[Decimal, str, str]] = []
    for symbol, series in prices_by_symbol.items():
        series.sort()
        for i in range(1, len(series)):
            prev_day, prev = series[i - 1]
            day, close = series[i]
            if prev <= 0:
                continue
            moves.append(((close - prev) / prev, symbol, day))
    moves.sort(key=lambda m: m[0])

    def pct(value: Decimal) -> str:
        return f"{value * 100:.4f}%"

    up = [m for m in moves if m[0] > 0]
    down = [m for m in moves if m[0] < 0]
    near_limit_up = [m for m in moves if m[0] >= Decimal("0.0985")]
    near_limit_down = [m for m in moves if m[0] <= Decimal("-0.0985")]
    over_limit = [m for m in moves if abs(m[0]) > Decimal("0.1005")]

    report = {
        "sessions": len(sessions),
        "observed_close_rows": observed_rows,
        "distinct_symbols": len(prices_by_symbol),
        "tick_by_band": tick_report,
        "daily_moves": {
            "observations": len(moves),
            "max_up": pct(moves[-1][0]) if moves else None,
            "max_down": pct(moves[0][0]) if moves else None,
            "count_up": len(up),
            "count_down": len(down),
            "at_or_above_9.85pct_up": len(near_limit_up),
            "at_or_below_9.85pct_down": len(near_limit_down),
            "beyond_10.05pct_either_way": len(over_limit),
        },
        "limit_exceptions_sample": [
            {"symbol": s, "date": d, "move": pct(m)} for m, s, d in over_limit[:10]
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
