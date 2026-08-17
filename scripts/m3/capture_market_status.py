"""M3.1d: capture official historical disposal and attention data.

These endpoints serve date ranges, so the fixed window is captured in monthly
chunks rather than one request per day. Every response is checked against the
range that was actually requested, because TPEx silently returns the current
week for an unrecognised parameter instead of failing.

Writes only into an isolated temporary shadow root; protected production
stores are fingerprinted before and after and are never written.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_window import protected_fingerprints  # noqa: E402
from market_status_sources import (  # noqa: E402
    SOURCE_SPECS,
    build_m3_registry,
    echoed_range_matches,
    request_parameters,
)
from tw_sepa_screener.m2_daily_price_pilot import (  # noqa: E402
    require_daily_price_output_root,
)
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-market-status-capture/1.0.0"


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        if cursor.month == 12:
            following = date(cursor.year + 1, 1, 1)
        else:
            following = date(cursor.year, cursor.month + 1, 1)
        chunks.append((cursor, min(following - timedelta(days=1), end)))
        cursor = following
    return chunks


def count_rows(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    best = 0
    data = payload.get("data")
    if isinstance(data, list):
        best = len(data)
    tables = payload.get("tables")
    if isinstance(tables, list):
        for table in tables:
            if isinstance(table, dict) and isinstance(table.get("data"), list):
                best = max(best, len(table["data"]))
    return best


def already_captured(root: Path) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    observations = root / "raw_observations"
    if not observations.is_dir():
        return done
    for path in observations.rglob("manifest.json"):
        try:
            manifest = json.loads(path.read_bytes())
        except (ValueError, OSError):
            continue
        if str(manifest.get("capture_status")) == "hash-verified":
            done.add(
                (str(manifest.get("source_id")), str(manifest.get("logical_period")))
            )
    return done


def capture_chunk(
    store: RawCaptureStore,
    source_id: str,
    start: date,
    end: date,
    *,
    base_session: requests.Session,
    retry_limit: int,
) -> dict[str, Any]:
    period = f"range:{start.isoformat()}:{end.isoformat()}"
    url = str(SOURCE_SPECS[source_id]["url"])
    params = request_parameters(source_id, start, end)

    def resolve_period(
        source: Any, _fetched_at: datetime, _parameters: Mapping[str, Any]
    ) -> str:
        if source.source_id != source_id:
            raise ValueError(f"capture resolved unexpected source {source.source_id}")
        return period

    for attempt in range(1, retry_limit + 1):
        captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=resolve_period,
            transport_context={"attempt": attempt, "client_id": "m3-status-capture"},
        )
        try:
            response = captured.get(url, params=params, timeout=60)
            response.raise_for_status()
            response.encoding = "utf-8-sig"
            payload = response.json()
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            retryable = status is None or status == 429 or status >= 500
            if not retryable or attempt == retry_limit:
                return {
                    "outcome": "transport-error",
                    "attempts": attempt,
                    "error": str(exc)[:200],
                }
            time.sleep(min(2.0 ** (attempt - 1), 10.0))
            continue
        except ValueError as exc:
            return {
                "outcome": "payload-error",
                "attempts": attempt,
                "observations": len(captured.observations),
                "error": str(exc)[:200],
            }

        # Fail closed if the publisher served a different range than requested.
        if not echoed_range_matches(payload, start, end):
            return {
                "outcome": "range-mismatch",
                "attempts": attempt,
                "observations": len(captured.observations),
                "echoed_range": str(payload.get("date"))[:40],
                "requested": f"{start.isoformat()}..{end.isoformat()}",
            }
        rows = count_rows(payload)
        return {
            "outcome": "captured" if rows else "official-empty-range",
            "attempts": attempt,
            "observations": len(captured.observations),
            "rows": rows,
            "echoed_range": str(payload.get("date"))[:40]
            if isinstance(payload, dict)
            else None,
        }
    return {"outcome": "transport-error", "attempts": retry_limit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument(
        "--producer-commit", default="fb87f62f8c2c68e2b85982cd102a35fd935bc0a4"
    )
    parser.add_argument(
        "--dirty-fingerprint",
        default="d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9",
    )
    args = parser.parse_args(argv)

    root = require_daily_price_output_root(args.output_root)
    producer = {
        "name": "tw-sepa-screener",
        "commit": args.producer_commit,
        "dirty_fingerprint": args.dirty_fingerprint,
    }
    store = RawCaptureStore(root, build_m3_registry(), producer=producer)

    before = protected_fingerprints()
    started_at = datetime.now(timezone.utc)
    done = already_captured(root)
    ledger_path = root / "status_capture_ledger.jsonl"
    counts: dict[str, int] = {}
    base_session = requests.Session()
    chunks = month_chunks(args.start, args.end)

    for source_id in SOURCE_SPECS:
        for start, end in chunks:
            period = f"range:{start.isoformat()}:{end.isoformat()}"
            if (source_id, period) in done:
                entry = {"outcome": "already-captured", "attempts": 0}
            else:
                entry = capture_chunk(
                    store,
                    source_id,
                    start,
                    end,
                    base_session=base_session,
                    retry_limit=args.retry_limit,
                )
                time.sleep(args.interval)
            record = {
                "source_id": source_id,
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                **entry,
            }
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
            print(
                f"{source_id:28} {start} .. {end}  -> {entry['outcome']}"
                f"  rows={entry.get('rows', '-')}",
                flush=True,
            )

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "output_root": str(root),
        "window": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "sources": list(SOURCE_SPECS),
        "chunk_count": len(chunks),
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outcome_counts": counts,
        "producer": producer,
        "protected_before": before,
        "protected_after": after,
        "production_unchanged": before == after,
        "output_policy": "temporary-shadow-only-no-production-writer",
        "ledger_path": str(ledger_path),
    }
    (root / "status_capture_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest["outcome_counts"], ensure_ascii=False))
    print("production_unchanged:", manifest["production_unchanged"])
    failures = sum(
        counts.get(key, 0)
        for key in ("transport-error", "payload-error", "range-mismatch")
    )
    return 0 if manifest["production_unchanged"] and failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
