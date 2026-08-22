"""Capture archived TPEx market announcements for corporate-action events.

TPEx publishes no historical reduction or par-value table. Its four dedicated
endpoints — `bulletin/revivt`, `decap`, `pvChgAnn`, `pvChgRslt` — each ignore
the requested date and echo a rolling window of the next few days, so none of
them can say what happened last year.

The history exists only in the market-announcement archive, which does take a
real date range. Category 2 covers 除權、除息、增資、減資、換股, and each
announcement's detail document states the halt window, the resumption date and
the exchange ratio in a strongly templated form.

Two stages, as with every other detail lane here:

* the listing is captured per month, so a failure resumes rather than restarts;
* detail keys are derived from the captured listing, never enumerated — the
  listing is what states which announcements exist.

Writes only into an isolated temporary shadow root; protected production stores
are fingerprinted before and after and are never written.
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from source_state import (  # noqa: E402
    PRODUCER_COMMIT,
    SOURCE_STATE_FINGERPRINT,
)
from capture_window import protected_fingerprints  # noqa: E402
from retry_policy import OFFICIAL_JSON, headers_of, status_of  # noqa: E402
from market_status_parsers import _ANN_LINK  # noqa: E402
from market_status_sources import (  # noqa: E402
    TPEX_ANNOUNCEMENT_DETAIL_URL,
    TPEX_ANNOUNCEMENT_URL,
    announcement_detail_parameters,
    announcement_detail_period,
    build_m3_registry,
    request_parameters,
)
from tw_sepa_screener.m2_daily_price_pilot import (  # noqa: E402
    require_daily_price_output_root,
)
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-tpex-announcement-capture/1.0.0"
LIST_SOURCE = "TPEX-ANNOUNCEMENT-HIST"
DETAIL_SOURCE = "TPEX-ANNOUNCEMENT-DETAIL"


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        following = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        chunks.append((cursor, min(following - timedelta(days=1), end)))
        cursor = following
    return chunks


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


def _fetch(
    store: RawCaptureStore,
    source_id: str,
    url: str,
    params: dict[str, str],
    period: str,
    *,
    base_session: requests.Session,
    retry_limit: int,
) -> tuple[dict[str, Any], Any]:
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
            transport_context={"attempt": attempt, "client_id": "m3-tpex-announcement"},
        )
        try:
            response = captured.get(url, params=params, timeout=60)
            response.raise_for_status()
            response.encoding = "utf-8-sig"
            payload = response.json()
        except requests.RequestException as exc:
            if not OFFICIAL_JSON.should_retry(
                attempt=attempt, status=status_of(exc)
            ) or attempt == retry_limit:
                return {"outcome": "transport-error", "attempts": attempt,
                        "error": str(exc)[:200]}, None
            time.sleep(OFFICIAL_JSON.delay_for(attempt=attempt, headers=headers_of(exc)))
            continue
        except ValueError as exc:
            return {"outcome": "payload-error", "attempts": attempt,
                    "error": str(exc)[:200]}, None

        stat = str(payload.get("stat", "")) if isinstance(payload, dict) else ""
        if stat.lower() != "ok":
            # TPEx answers a malformed date with 日期參數錯誤 and HTTP 200.
            # Treating that as an empty result would silently drop a month.
            return {"outcome": "official-not-ok", "attempts": attempt,
                    "stat": stat[:60]}, None
        return {"outcome": "captured", "attempts": attempt}, payload
    return {"outcome": "transport-error", "attempts": retry_limit}, None


def listing_rows(payload: Any) -> list[list[Any]]:
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, list) or not tables:
        return []
    data = tables[0].get("data")
    return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    # 6s floor: a 0.7s interval over a six-year backfill got this IP
    # blocked from the whole of www.twse.com.tw, prices included, and the
    # block outlasted a day. Politeness here is cheaper than a lockout.
    parser.add_argument("--interval", type=float, default=6.0)
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument(
        "--producer-commit", default=PRODUCER_COMMIT
    )
    parser.add_argument(
        "--dirty-fingerprint",
        default=SOURCE_STATE_FINGERPRINT,
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
    ledger_path = root / "tpex_announcement_ledger.jsonl"
    counts: dict[str, int] = {}
    base_session = requests.Session()

    def record(entry: dict[str, Any], **extra: Any) -> None:
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {**extra, "recorded_at": datetime.now(timezone.utc).isoformat(), **entry},
                    ensure_ascii=False,
                )
                + "\n"
            )

    detail_keys: dict[str, str] = {}
    for start, end in month_chunks(args.start, args.end):
        period = f"range:{start.isoformat()}:{end.isoformat()}"
        if (LIST_SOURCE, period) in done:
            entry, payload = {"outcome": "already-captured", "attempts": 0}, None
        else:
            entry, payload = _fetch(
                store,
                LIST_SOURCE,
                TPEX_ANNOUNCEMENT_URL,
                request_parameters(LIST_SOURCE, start, end),
                period,
                base_session=base_session,
                retry_limit=args.retry_limit,
            )
            time.sleep(args.interval)
        rows = listing_rows(payload) if payload else []
        for raw_row in rows:
            for cell in raw_row:
                match = _ANN_LINK.search(str(cell))
                if match:
                    from urllib.parse import unquote

                    detail_keys[unquote(match.group(2))] = unquote(match.group(1))
                    break
        record(entry, source_id=LIST_SOURCE, range_start=start.isoformat(),
               range_end=end.isoformat(), rows=len(rows))
        print(f"{LIST_SOURCE:26} {start} .. {end} -> {entry['outcome']} rows={len(rows)}",
              flush=True)

    print(f"\ndetail keys derived from listings: {len(detail_keys)}", flush=True)
    for doc_id, content_file in sorted(detail_keys.items()):
        period = announcement_detail_period(doc_id)
        if (DETAIL_SOURCE, period) in done:
            entry = {"outcome": "already-captured", "attempts": 0}
        else:
            entry, _ = _fetch(
                store,
                DETAIL_SOURCE,
                TPEX_ANNOUNCEMENT_DETAIL_URL,
                announcement_detail_parameters(content_file, doc_id),
                period,
                base_session=base_session,
                retry_limit=args.retry_limit,
            )
            time.sleep(args.interval)
        record(entry, source_id=DETAIL_SOURCE, doc_id=doc_id)
        print(f"{DETAIL_SOURCE:26} {doc_id[:24]:26} -> {entry['outcome']}", flush=True)

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "output_root": str(root),
        "window": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "sources": [LIST_SOURCE, DETAIL_SOURCE],
        "detail_key_count": len(detail_keys),
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outcome_counts": counts,
        "producer": producer,
        "protected_before": before,
        "protected_after": after,
        "production_unchanged": before == after,
        "output_policy": "temporary-shadow-only-no-production-writer",
        "ledger_path": str(ledger_path),
        "key_derivation": "detail-link-of-captured-listing-never-enumerated",
    }
    (root / "tpex_announcement_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
