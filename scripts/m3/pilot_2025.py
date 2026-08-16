"""Read-only pilot: do the official historical endpoints serve 2025 dates?

Makes a small number of polite GET requests. Stores nothing.
"""

from __future__ import annotations

import json
import time
from datetime import date

from tw_sepa_screener.sources.tpex import TpexClient
from tw_sepa_screener.sources.twse import TwseClient

PROBES = [
    date(2025, 1, 2),   # expected first trading day of 2025
    date(2025, 1, 1),   # expected national holiday -> no session
    date(2025, 6, 16),  # ordinary Monday
    date(2025, 12, 31),
    date(2026, 3, 16),  # ordinary Monday inside the window
]
INTERVAL = 0.7


def probe(label: str, client, session_date: date) -> dict[str, object]:
    try:
        payload = client.get_market_day_payload(session_date)
    except Exception as exc:  # noqa: BLE001 - pilot records the failure shape
        return {
            "market": label,
            "date": session_date.isoformat(),
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:200],
        }
    result: dict[str, object] = {
        "market": label,
        "date": session_date.isoformat(),
        "ok": True,
        "payload_type": type(payload).__name__,
    }
    if isinstance(payload, dict):
        result["keys"] = sorted(payload)[:12]
        for key in ("stat", "date", "total", "iTotalRecords"):
            if key in payload:
                result[key] = payload[key]
        rows = 0
        for key, value in payload.items():
            if isinstance(value, list) and value and isinstance(value[0], list):
                rows = max(rows, len(value))
            if key in {"aaData", "data", "tables"} and isinstance(value, list):
                rows = max(rows, len(value))
        result["max_list_rows"] = rows
    return result


def main() -> None:
    twse = TwseClient()
    tpex = TpexClient()
    out = []
    for session_date in PROBES:
        out.append(probe("TWSE", twse, session_date))
        time.sleep(INTERVAL)
        out.append(probe("TPEX", tpex, session_date))
        time.sleep(INTERVAL)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
