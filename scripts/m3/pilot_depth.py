"""Inspect the real row depth of the historical payloads for 2025 dates."""

from __future__ import annotations

import json
import time
from datetime import date

from tw_sepa_screener.sources.tpex import TpexClient
from tw_sepa_screener.sources.twse import TwseClient


def describe(payload: dict) -> dict:
    out: dict[str, object] = {"stat": payload.get("stat"), "date": payload.get("date")}
    tables = payload.get("tables")
    if isinstance(tables, list):
        summary = []
        for table in tables:
            if not isinstance(table, dict):
                continue
            data = table.get("data")
            summary.append(
                {
                    "title": str(table.get("title", ""))[:40],
                    "fields": (table.get("fields") or [])[:6],
                    "rows": len(data) if isinstance(data, list) else 0,
                    "first_row": (data[0][:6] if isinstance(data, list) and data else None),
                }
            )
        out["tables"] = summary
        out["total_rows"] = sum(t["rows"] for t in summary)
    return out


def main() -> None:
    twse = TwseClient()
    tpex = TpexClient()
    probes = [date(2025, 1, 2), date(2025, 6, 16), date(2025, 1, 1)]
    result = {}
    for d in probes:
        entry = {}
        try:
            entry["TWSE"] = describe(twse.get_market_day_payload(d))
        except Exception as exc:  # noqa: BLE001
            entry["TWSE"] = {"error": str(exc)[:120]}
        time.sleep(0.7)
        try:
            entry["TPEX"] = describe(tpex.get_market_day_payload(d))
        except Exception as exc:  # noqa: BLE001
            entry["TPEX"] = {"error": str(exc)[:120]}
        time.sleep(0.7)
        result[d.isoformat()] = entry
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
