"""Capture the exchanges' daily institutional net-buy reports, one session at a time.

A strategy phrased as "投信買超前幾名" needs one number per security per
session. Both exchanges publish it, it is official rather than vendor, and
nothing in this warehouse captured it until now.

WHY ONE REQUEST PER SESSION

Every other historical source in this repository takes a date range, so one
request covers a year. **These two do not.** The feasibility probe on
2026-09-04 established the shape: `T86` and TPEx's `dailyTrade` each answer
for a single date. Six years of both markets is about 3,724 requests, which at
the six-second floor is roughly six hours.

That floor is not negotiable. A 0.7-second interval over the six-year price
backfill got this machine's address refused by twse.com.tw for more than a
day.

WHAT THE PROBE ALREADY SETTLED, SO THIS DOES NOT RE-ASK

    TWSE answers back to 2012, seven years before M3's window opens.
    TWSE's layout changed twice: 12 fields, then 16, then 19.
    TPEx's `openapi` route returns HTML; the `rwd` route returns 23 fields.
    A delisted security appears during its listed period and not after --
    checked on 3202, which is why the survivorship lane exists.

**The layout change is the reason this captures rather than parses.** Bytes
are preserved as they arrived and given a `logical_period`; deciding what the
columns mean is the builder's problem, on data that will still be here when
the decision changes.

RESUMABLE, AND WHY THAT MATTERS HERE

Six hours is longer than this machine reliably stays awake -- M3.17 records a
staging build killed after six minutes and a TPEx capture that died at 655 of
4,310. A session already held as hash-verified is skipped, so the lane can be
re-run and will pick up where it stopped. Wrap it in `keep_awake.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from source_state import PRODUCER_COMMIT, SOURCE_STATE_FINGERPRINT  # noqa: E402
from retry_policy import OFFICIAL_JSON, status_of  # noqa: E402
from market_status_sources import (  # noqa: E402
    INSTITUTIONAL_SPECS,
    build_m3_registry,
    institutional_parameters,
)
from capture_window import protected_fingerprints  # noqa: E402
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-institutional-capture/1.0.0"

MARKETS = {
    "TWSE": "TWSE-INSTITUTIONAL-DAILY",
    "TPEX": "TPEX-INSTITUTIONAL-DAILY",
}

# The floor every capture lane in this repository uses.
INTERVAL_FLOOR = 6.0


def sessions_between(start: date, end: date) -> list[date]:
    """Every weekday in the window.

    Holidays are asked about and their answers preserved: an exchange's
    non-trading reply is evidence that the day had no session, and the
    warehouse distinguishes that from a day nobody captured. Weekends are
    skipped because they carry no such publication.
    """

    days, cursor = [], start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def payload_is_json(store_root: Path, record: dict[str, Any]) -> bool:
    """Did this observation store an answer, or an error page?

    Both are captured faithfully and both are `hash-verified` -- that status
    is about the bytes matching their hash, not about what the bytes say. A
    200 carrying TPEx's HTML error page verifies perfectly.
    """

    blob_id = str(record.get("blob_id") or "")
    if not blob_id:
        return False
    path = store_root / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
    try:
        head = path.read_bytes()[:1]
    except OSError:
        return False
    return head in (b"{", b"[")


def already_held(store_root: Path) -> set[tuple[str, str]]:
    """Sessions this root holds **a usable answer for**.

    Not merely "an observation exists". TPEx intermittently answers a valid
    request with a 7,343-byte HTML error page and HTTP 200 -- measured twice
    in the first 76 observations of the six-year run, on sessions whose
    neighbours answered normally. Those bytes are stored, hash-verified, and
    are not the report.

    **Counting them as held would make the hole permanent**: the resume would
    skip the session forever and the lane would carry a gap that nothing
    downstream could tell from a genuine non-trading day.
    """

    held: set[tuple[str, str]] = set()
    observations = store_root / "raw_observations"
    if not observations.is_dir():
        return held
    for path in observations.rglob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("capture_status") != "hash-verified":
            continue
        source, period = record.get("source_id"), str(record.get("logical_period") or "")
        if source not in MARKETS.values() or not period.startswith("session:"):
            continue
        if not payload_is_json(store_root, record):
            continue
        held.add((str(source), period))
    return held


def row_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    tables = payload.get("tables")
    if isinstance(tables, list) and tables:
        data = (tables[0] or {}).get("data")
        return len(data) if isinstance(data, list) else 0
    data = payload.get("data") or payload.get("aaData")
    return len(data) if isinstance(data, list) else 0


def capture_one(
    store: RawCaptureStore,
    market: str,
    session: date,
    *,
    base_session: requests.Session,
    retry_limit: int,
) -> dict[str, Any]:
    """One market-session. A non-trading reply is evidence, not an error."""

    source_id = MARKETS[market]
    period = f"session:{session.isoformat()}"
    url = str(INSTITUTIONAL_SPECS[source_id]["url"])
    parameters = institutional_parameters(source_id, session)

    def resolve_period(source: Any, _fetched_at: datetime, _params: Any) -> str:
        if source.source_id != source_id:
            raise ValueError(f"capture resolved an unexpected source: {source.source_id}")
        return period

    last: Exception | None = None
    for attempt in range(1, retry_limit + 1):
        captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=resolve_period,
            transport_context={"attempt": attempt, "client_id": "m3-institutional"},
        )
        try:
            response = captured.get(url, params=parameters, timeout=60)
        except requests.RequestException as exc:
            last = exc
            if (
                not OFFICIAL_JSON.should_retry(attempt=attempt, status=status_of(exc))
                or attempt == retry_limit
            ):
                return {"outcome": "transport-error", "attempts": attempt,
                        "error": str(exc)[:200]}
            time.sleep(OFFICIAL_JSON.delay_for(attempt=attempt, headers=None))
            continue
        try:
            payload = response.json()
        except ValueError:
            # The bytes were stored before this line ran, so the error page is
            # preserved as evidence either way.
            #
            # **Retried, not accepted.** A 200 carrying HTML is not the
            # publisher saying "no session that day" -- it is the site
            # failing, and the neighbouring sessions answered normally. The
            # request loop only ever retried transport exceptions, so this
            # would have been stored as the final answer for two sessions in
            # the first eighty of a 4,004-request run.
            if attempt == retry_limit:
                return {"outcome": "not-json", "attempts": attempt,
                        "observations": len(captured.observations)}
            time.sleep(OFFICIAL_JSON.delay_for(attempt=attempt, headers=None))
            continue
        rows = row_count(payload)
        return {
            "outcome": "captured" if rows else "official-zero-rows",
            "attempts": attempt,
            "rows": rows,
            "observations": len(captured.observations),
        }
    return {"outcome": "transport-error", "attempts": retry_limit,
            "error": str(last)[:200] if last else ""}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--interval", type=float, default=INTERVAL_FLOOR)
    parser.add_argument("--retry-limit", type=int, default=4)
    parser.add_argument(
        "--markets",
        default="TWSE,TPEX",
        help="comma separated; both by default",
    )
    args = parser.parse_args(argv)

    if args.interval < INTERVAL_FLOOR:
        raise SystemExit(
            f"--interval {args.interval} is below the {INTERVAL_FLOOR}s floor. A "
            f"0.7s interval over the six-year price backfill got this address "
            f"refused by twse.com.tw for more than a day"
        )
    root = args.output_root.resolve()
    if root.is_relative_to(Path(__file__).resolve().parents[2]):
        raise SystemExit(f"{root} is inside the repository; captures go to an isolated root")

    markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
    unknown = [m for m in markets if m not in MARKETS]
    if unknown:
        raise SystemExit(f"unknown markets: {unknown}")

    before = protected_fingerprints()
    producer = {
        "name": "tw-sepa-screener",
        "commit": PRODUCER_COMMIT,
        "dirty_fingerprint": SOURCE_STATE_FINGERPRINT,
    }
    store = RawCaptureStore(root, build_m3_registry(), producer=producer)
    held = already_held(root)
    days = sessions_between(args.start, args.end)
    todo = [
        (market, day)
        for day in days
        for market in markets
        if (MARKETS[market], f"session:{day.isoformat()}") not in held
    ]

    print(f"{len(days):,} 個平日 × {len(markets)} 個市場")
    print(f"  已持有 {len(held):,}，待擷取 {len(todo):,}")
    print(f"  間隔 {args.interval}s，預估 {len(todo) * args.interval / 3600:.1f} 小時")

    counts: dict[str, int] = {}
    started = datetime.now(timezone.utc)
    base = requests.Session()
    for index, (market, day) in enumerate(todo):
        if index:
            time.sleep(args.interval)
        result = capture_one(
            store, market, day, base_session=base, retry_limit=args.retry_limit
        )
        counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
        if index % 50 == 0 or result["outcome"] not in ("captured", "official-zero-rows"):
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            print(
                f"  [{index + 1:>5}/{len(todo)}] {day} {market:5s} "
                f"{result['outcome']:18s} rows={result.get('rows')}  "
                f"{elapsed / 60:>5.1f}m",
                flush=True,
            )

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "captured_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "markets": markets,
        "weekdays_in_window": len(days),
        "already_held_at_start": len(held),
        "attempted": len(todo),
        "outcomes": dict(sorted(counts.items())),
        "request_interval_seconds": args.interval,
        "producer_commit": PRODUCER_COMMIT,
        "source_state_fingerprint": SOURCE_STATE_FINGERPRINT,
        "protected_unchanged": before == after,
        "notes": [
            "One request per market-session: these endpoints take no date range.",
            "Non-trading replies are preserved as evidence. A day nobody asked "
            "about and a day the exchange said had no session are different "
            "facts, and only the second is in here.",
            "TWSE's layout changed twice inside this window (12, 16 then 19 "
            "fields) and TPEx carries 23. Nothing is parsed here; the bytes "
            "keep their shape for a builder to read.",
        ],
    }
    (root / "capture_run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if not manifest["protected_unchanged"]:
        raise SystemExit("a protected production store changed during the capture")
    print(json.dumps(manifest["outcomes"], ensure_ascii=False))
    print(f"寫入 {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
