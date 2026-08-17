"""Extract disposal intervals and altered-trading state from the status capture.

Disposal announcements carry both an announcement date and an effective
interval, so they support point-in-time reconstruction directly. The measures
text additionally states whether the security was placed on 全額交割
(altered trading method), which recovers part of a state that has no
historical endpoint of its own.
"""

from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(r"C:\tmp\tw-alpha-m3-status-20260816-01")
WINDOW = (date(2025, 1, 1), date(2026, 8, 3))

ALTERED_PATTERNS = (
    "變更交易方法",
    "全額交割",
)


def roc_to_iso(text: str) -> str | None:
    """Accept 113/12/26 and 114.01.06 style ROC dates."""

    match = re.match(r"^\s*(\d{2,3})[/.](\d{1,2})[/.](\d{1,2})\s*$", str(text))
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year + 1911, month, day).isoformat()
    except ValueError:
        return None


def parse_interval(text: str) -> tuple[str | None, str | None]:
    """Parse '113/12/26～114/01/09' into ISO start and end."""

    parts = re.split(r"[~～]", str(text))
    if len(parts) != 2:
        return None, None
    return roc_to_iso(parts[0]), roc_to_iso(parts[1])


def load_payloads() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for manifest_path in sorted((ROOT / "raw_observations").rglob("manifest.json")):
        manifest = json.loads(manifest_path.read_bytes())
        blob_id = str(manifest["blob_id"])
        blob = ROOT / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
        raw = blob.read_bytes()
        try:
            text = gzip.decompress(raw).decode("utf-8")
        except (OSError, gzip.BadGzipFile):
            text = raw.decode("utf-8-sig", errors="replace")
        grouped.setdefault(str(manifest["source_id"]), []).append(json.loads(text))
    return grouped


def rows_of(payload: dict) -> list[tuple[list, list]]:
    """Return (fields, rows) pairs from either TWSE or TPEx payload shapes."""

    out: list[tuple[list, list]] = []
    if isinstance(payload.get("data"), list):
        out.append((payload.get("fields") or [], payload["data"]))
    for table in payload.get("tables") or []:
        if isinstance(table, dict) and isinstance(table.get("data"), list):
            out.append((table.get("fields") or [], table["data"]))
    return out


def main() -> None:
    grouped = load_payloads()
    report: dict[str, object] = {"sources": {}}

    disposals: list[dict] = []
    attention_days: dict[str, set[str]] = {"TWSE": set(), "TPEX": set()}

    for source_id, payloads in sorted(grouped.items()):
        market = "TPEX" if source_id.startswith("TPEX") else "TWSE"
        kind = "disposal" if ("PUNISH" in source_id or "DISPOSAL" in source_id) else "attention"
        total = 0
        parsed = 0
        altered = 0
        seen: set[tuple] = set()
        for payload in payloads:
            for fields, rows in rows_of(payload):
                names = [str(f) for f in fields]
                interval_idx = next(
                    (i for i, n in enumerate(names) if "處置起" in n), None
                )
                announce_idx = next(
                    (i for i, n in enumerate(names) if "公布日期" in n or "公告日期" in n),
                    None,
                )
                date_idx = next(
                    (i for i, n in enumerate(names) if n.strip() in {"日期"}), None
                )
                code_idx = next(
                    (i for i, n in enumerate(names) if "證券代號" in n), None
                )
                for row in rows:
                    if code_idx is None or len(row) <= code_idx:
                        continue
                    code = str(row[code_idx]).strip()
                    if not code or not code[:4].isdigit():
                        continue
                    total += 1
                    if kind == "attention":
                        idx = announce_idx if announce_idx is not None else date_idx
                        iso = roc_to_iso(row[idx]) if idx is not None and len(row) > idx else None
                        if iso:
                            parsed += 1
                            attention_days[market].add(iso)
                        continue
                    if interval_idx is None or len(row) <= interval_idx:
                        continue
                    start, end = parse_interval(row[interval_idx])
                    announced = (
                        roc_to_iso(row[announce_idx])
                        if announce_idx is not None and len(row) > announce_idx
                        else None
                    )
                    if not (start and end):
                        continue
                    body = " ".join(str(c) for c in row)
                    is_altered = any(p in body for p in ALTERED_PATTERNS)
                    altered += int(is_altered)
                    key = (market, code[:4], start, end)
                    if key in seen:
                        continue
                    seen.add(key)
                    parsed += 1
                    disposals.append(
                        {
                            "market": market,
                            "symbol": code[:4],
                            "announced_at": announced,
                            "effective_from": start,
                            "effective_to": end,
                            "altered_trading": is_altered,
                        }
                    )
        report["sources"][source_id] = {
            "payloads": len(payloads),
            "candidate_rows": total,
            "usable_rows": parsed,
            "altered_trading_rows": altered if kind == "disposal" else None,
        }

    lo, hi = WINDOW
    in_window = [
        d
        for d in disposals
        if d["effective_to"] >= lo.isoformat() and d["effective_from"] <= hi.isoformat()
    ]
    covered_days: dict[str, set[str]] = {"TWSE": set(), "TPEX": set()}
    for item in in_window:
        start = date.fromisoformat(item["effective_from"])
        end = date.fromisoformat(item["effective_to"])
        cursor = max(start, lo)
        stop = min(end, hi)
        while cursor <= stop:
            covered_days[item["market"]].add(cursor.isoformat())
            cursor = date.fromordinal(cursor.toordinal() + 1)

    report["disposal_records"] = len(disposals)
    report["disposal_records_in_window"] = len(in_window)
    report["disposal_with_announcement_date"] = sum(
        1 for d in in_window if d["announced_at"]
    )
    report["altered_trading_records"] = sum(1 for d in in_window if d["altered_trading"])
    report["distinct_securities_disposed"] = len(
        {(d["market"], d["symbol"]) for d in in_window}
    )
    report["calendar_days_with_active_disposal"] = {
        m: len(v) for m, v in covered_days.items()
    }
    report["attention_announcement_days"] = {
        m: len(v) for m, v in attention_days.items()
    }
    report["attention_day_range"] = {
        m: [min(v), max(v)] if v else [] for m, v in attention_days.items()
    }
    report["announcement_lead_days"] = dict(
        Counter(
            (
                date.fromisoformat(d["effective_from"])
                - date.fromisoformat(d["announced_at"])
            ).days
            for d in in_window
            if d["announced_at"]
        ).most_common(5)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
