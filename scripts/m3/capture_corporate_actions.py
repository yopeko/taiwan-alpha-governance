"""M3.1e: capture official TWSE ex-right / ex-dividend history for a window.

TWSE serves this as a date range (TWT49U), so the window is captured in
monthly chunks. TPEx has no equivalent range endpoint — its only historical
route is MOPS per-symbol-per-year — so TPEx is out of scope here and stays
`unknown` rather than being silently filled from a current-only source.

Licence context: TWSE-ACTIONS-HIST is the source that M2 initially
quarantined as `license-owner-approval-required` and then released under
decision M2-OWNER-APPROVAL-20260803-01, whose scope is TWT49U retention for
project-internal M3 research validation. This capture stays inside that scope.
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

from capture_window import protected_fingerprints  # noqa: E402
from retry_policy import OFFICIAL_JSON, headers_of, status_of  # noqa: E402
from tw_sepa_screener.corporate_actions import (  # noqa: E402
    TWSE_EXRIGHT_HISTORY_URL,
)
from tw_sepa_screener.m2_daily_price_pilot import (  # noqa: E402
    require_daily_price_output_root,
)
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402
from tw_sepa_screener.sources.raw_registry import (  # noqa: E402
    build_p0_formal_registry,
)

SCHEMA_ID = "tw-alpha-m3-corporate-action-capture/1.0.0"
SOURCE_ID = "TWSE-ACTIONS-HIST"
NO_DATA_STAT = "很抱歉，沒有符合條件的資料!"


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
        if str(manifest.get("capture_status")) == "hash-verified":
            done.add(str(manifest.get("logical_period")))
    return done


def capture_chunk(
    store: RawCaptureStore,
    start: date,
    end: date,
    *,
    base_session: requests.Session,
    retry_limit: int,
) -> dict[str, Any]:
    period = f"range:{start.isoformat()}:{end.isoformat()}"

    def resolve_period(
        source: Any, _fetched_at: datetime, parameters: Mapping[str, Any]
    ) -> str:
        if source.source_id != SOURCE_ID:
            raise ValueError(f"capture resolved unexpected source {source.source_id}")
        if str(parameters.get("startDate", "")) != start.strftime("%Y%m%d"):
            raise ValueError("request start date does not match target chunk")
        return period

    for attempt in range(1, retry_limit + 1):
        captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=resolve_period,
            transport_context={"attempt": attempt, "client_id": "m3-actions-capture"},
        )
        try:
            response = captured.get(
                TWSE_EXRIGHT_HISTORY_URL,
                params={
                    "startDate": start.strftime("%Y%m%d"),
                    "endDate": end.strftime("%Y%m%d"),
                    "response": "json",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            if not OFFICIAL_JSON.should_retry(attempt=attempt, status=status_of(exc)) or attempt == retry_limit:
                return {
                    "outcome": "transport-error",
                    "attempts": attempt,
                    "error": str(exc)[:200],
                }
            time.sleep(OFFICIAL_JSON.delay_for(attempt=attempt, headers=headers_of(exc)))
            continue
        except ValueError as exc:
            return {
                "outcome": "payload-error",
                "attempts": attempt,
                "observations": len(captured.observations),
                "error": str(exc)[:200],
            }

        stat = payload.get("stat") if isinstance(payload, dict) else None
        if stat == NO_DATA_STAT:
            return {
                "outcome": "official-no-data",
                "attempts": attempt,
                "observations": len(captured.observations),
                "rows": 0,
            }
        if stat != "OK":
            return {
                "outcome": "unexpected-stat",
                "attempts": attempt,
                "observations": len(captured.observations),
                "stat": str(stat)[:80],
            }
        rows = payload.get("data")
        count = len(rows) if isinstance(rows, list) else 0
        return {
            "outcome": "captured" if count else "official-empty-range",
            "attempts": attempt,
            "observations": len(captured.observations),
            "rows": count,
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
    store = RawCaptureStore(root, build_p0_formal_registry(), producer=producer)

    before = protected_fingerprints()
    started_at = datetime.now(timezone.utc)
    done = already_captured(root)
    ledger_path = root / "actions_capture_ledger.jsonl"
    counts: dict[str, int] = {}
    total_rows = 0
    base_session = requests.Session()

    for start, end in month_chunks(args.start, args.end):
        period = f"range:{start.isoformat()}:{end.isoformat()}"
        if period in done:
            entry = {"outcome": "already-captured", "attempts": 0}
        else:
            entry = capture_chunk(
                store,
                start,
                end,
                base_session=base_session,
                retry_limit=args.retry_limit,
            )
            time.sleep(args.interval)
        total_rows += int(entry.get("rows", 0) or 0)
        record = {
            "source_id": SOURCE_ID,
            "range_start": start.isoformat(),
            "range_end": end.isoformat(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **entry,
        }
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        print(
            f"{start} .. {end}  -> {entry['outcome']}  rows={entry.get('rows', '-')}",
            flush=True,
        )

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "source_id": SOURCE_ID,
        "output_root": str(root),
        "window": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "markets_covered": ["TWSE"],
        "markets_out_of_scope": ["TPEX"],
        "tpex_note": (
            "TPEx has no range-based historical ex-right endpoint; its only "
            "historical route is MOPS per-symbol-per-year. TPEx corporate "
            "actions therefore remain `unknown` and are not filled from the "
            "current-only prepost/daily sources."
        ),
        "licence_scope": (
            "TWT49U retained under M2-OWNER-APPROVAL-20260803-01 for "
            "project-internal M3 research validation."
        ),
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outcome_counts": counts,
        "total_rows": total_rows,
        "producer": producer,
        "protected_before": before,
        "protected_after": after,
        "production_unchanged": before == after,
        "output_policy": "temporary-shadow-only-no-production-writer",
        "ledger_path": str(ledger_path),
    }
    (root / "actions_capture_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(counts, ensure_ascii=False), "total_rows=", total_rows)
    print("production_unchanged:", manifest["production_unchanged"])
    failures = sum(
        counts.get(key, 0)
        for key in ("transport-error", "payload-error", "unexpected-stat")
    )
    return 0 if manifest["production_unchanged"] and failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
