"""M3.1f: capture TPEx historical ex-right actions via legacy MOPS.

TPEx publishes no range-based historical ex-right endpoint, so its only
official historical route is MOPS, queried one symbol-year at a time. Each
listing response is followed by one detail request per announcement.

The symbol universe is taken from securities that actually traded inside the
fixed window, not from today's master, so delisted securities are included.

Resumable: a symbol-year already captured as `hash-verified` is skipped.
Writes only into an isolated temporary shadow root.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
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
from retry_policy import MOPS_HTML, headers_of, status_of  # noqa: E402
from tw_sepa_screener.m2_daily_price_pilot import (  # noqa: E402
    require_daily_price_output_root,
)
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402
from tw_sepa_screener.sources.mops_tpex_actions import (  # noqa: E402
    BASE,
    _listing_rows,
)
from tw_sepa_screener.sources.raw_registry import (  # noqa: E402
    build_p0_formal_registry,
)

SCHEMA_ID = "tw-alpha-m3-tpex-action-capture/1.0.0"
LIST_SOURCE = "MOPS-TPEX-ACTIONS-LIST"
DETAIL_SOURCE = "MOPS-TPEX-ACTIONS-DETAIL"


def already_captured(root: Path) -> set[str]:
    done: set[str] = set()
    observations = root / "raw_observations"
    if not observations.is_dir():
        return done
    for path in observations.rglob("manifest.json"):
        try:
            manifest = json.loads(path.read_bytes())
        except (ValueError, OSError):
            continue
        if str(manifest.get("capture_status")) != "hash-verified":
            continue
        if str(manifest.get("source_id")) == LIST_SOURCE:
            done.add(str(manifest.get("logical_period")))
    return done


def capture_symbol_year(
    store: RawCaptureStore,
    symbol: str,
    roc_year: int,
    *,
    base_session: requests.Session,
    interval: float,
    retry_limit: int,
) -> dict[str, Any]:
    list_period = f"company:TPEX:{symbol}:year:{roc_year}"

    def list_period_resolver(
        source: Any, _fetched_at: datetime, _params: Mapping[str, Any]
    ) -> str:
        if source.source_id != LIST_SOURCE:
            raise ValueError(f"unexpected source {source.source_id}")
        return list_period

    listing_text: str | None = None
    for attempt in range(1, retry_limit + 1):
        captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=list_period_resolver,
            transport_context={"attempt": attempt, "client_id": "m3-tpex-actions"},
        )
        try:
            response = captured.post(
                f"{BASE}/ajax_t108sb19",
                data={
                    "step": "1",
                    "firstin": "true",
                    "TYPEK": "otc",
                    "isnew": "false",
                    "co_id": symbol,
                    "year": str(roc_year),
                    "month": "all",
                    "b_date": "",
                    "e_date": "",
                },
                timeout=60,
            )
            response.raise_for_status()
            response.encoding = "utf-8"
            listing_text = response.text
            break
        except requests.RequestException as exc:
            if not MOPS_HTML.should_retry(
                attempt=attempt, status=status_of(exc)
            ) or attempt == retry_limit:
                return {
                    "outcome": "list-transport-error",
                    "attempts": attempt,
                    "error": str(exc)[:160],
                }
            time.sleep(MOPS_HTML.delay_for(attempt=attempt, headers=headers_of(exc)))
    if listing_text is None:
        return {"outcome": "list-transport-error", "attempts": retry_limit}

    try:
        rows = _listing_rows(listing_text)
    except Exception as exc:  # noqa: BLE001 - parser defects are evidence
        return {"outcome": "list-parse-error", "error": str(exc)[:160]}

    if not rows:
        return {"outcome": "official-no-announcements", "announcements": 0}

    captured_details = 0
    failures: list[str] = []
    for announce_date, params in rows:
        detail_period = (
            f"company:TPEX:{symbol}:announced:{announce_date.isoformat()}"
        )

        def detail_period_resolver(
            source: Any, _fetched_at: datetime, _params: Mapping[str, Any]
        ) -> str:
            if source.source_id != DETAIL_SOURCE:
                raise ValueError(f"unexpected source {source.source_id}")
            return detail_period

        time.sleep(interval)
        detail_captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=detail_period_resolver,
            transport_context={"client_id": "m3-tpex-actions-detail"},
        )
        try:
            response = detail_captured.post(
                f"{BASE}/ajax_t108sb22",
                data={
                    "firstin": "true",
                    "TYPEK": "otc",
                    "isnew": "false",
                    "kind": "",
                    "SKIND": "G",
                    "step": "2",
                    **params,
                },
                timeout=60,
            )
            response.raise_for_status()
            captured_details += 1
        except requests.RequestException as exc:
            failures.append(f"{announce_date.isoformat()}:{str(exc)[:60]}")

    return {
        "outcome": "captured" if not failures else "detail-partial",
        "announcements": len(rows),
        "details_captured": captured_details,
        "detail_failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument(
        "--roc-years", default="113,114,115", help="ROC years to query"
    )
    # 6s floor: a 0.7s interval over a six-year backfill got this IP
    # blocked from the whole of www.twse.com.tw, prices included, and the
    # block outlasted a day. Politeness here is cheaper than a lockout.
    parser.add_argument("--interval", type=float, default=6.0)
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="pilot: first N symbols")
    parser.add_argument(
        "--producer-commit", default=PRODUCER_COMMIT
    )
    parser.add_argument(
        "--dirty-fingerprint",
        default=SOURCE_STATE_FINGERPRINT,
    )
    args = parser.parse_args(argv)

    symbols = json.loads(args.symbols.read_text(encoding="utf-8"))
    if args.limit:
        symbols = symbols[: args.limit]
    years = [int(y) for y in args.roc_years.split(",") if y.strip()]

    root = require_daily_price_output_root(args.output_root)
    producer = {
        "name": "tw-sepa-screener",
        "commit": args.producer_commit,
        "dirty_fingerprint": args.dirty_fingerprint,
    }
    store = RawCaptureStore(root, build_p0_formal_registry(), producer=producer)

    before = protected_fingerprints()
    started_at = datetime.now(timezone.utc)
    done = already_captured(root)
    ledger_path = root / "tpex_actions_ledger.jsonl"
    counts: dict[str, int] = {}
    announcements = 0
    index = 0
    total = len(symbols) * len(years)

    base_session = requests.Session()
    for symbol in symbols:
        for roc_year in years:
            index += 1
            period = f"company:TPEX:{symbol}:year:{roc_year}"
            if period in done:
                entry = {"outcome": "already-captured"}
            else:
                entry = capture_symbol_year(
                    store,
                    symbol,
                    roc_year,
                    base_session=base_session,
                    interval=args.interval,
                    retry_limit=args.retry_limit,
                )
                time.sleep(args.interval)
            announcements += int(entry.get("announcements", 0) or 0)
            record = {
                "symbol": symbol,
                "roc_year": roc_year,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                **entry,
            }
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
            if index % 200 == 0:
                print(
                    f"[{index}/{total}] {symbol}/{roc_year} announcements={announcements} {counts}",
                    flush=True,
                )

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "output_root": str(root),
        "symbol_count": len(symbols),
        "roc_years": years,
        "symbol_year_requests": total,
        "total_announcements": announcements,
        "symbol_universe_note": (
            "Symbols are those that actually traded inside the fixed window, "
            "taken from the official TPEx daily quote captures, so delisted "
            "securities are included."
        ),
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
    (root / "tpex_actions_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(counts, ensure_ascii=False), "announcements=", announcements)
    print("production_unchanged:", manifest["production_unchanged"])
    failures = sum(
        counts.get(k, 0)
        for k in ("list-transport-error", "list-parse-error", "detail-partial")
    )
    return 0 if manifest["production_unchanged"] and failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
