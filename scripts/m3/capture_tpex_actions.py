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
from dataclasses import replace
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
from retry_policy import MOPS_HTML, request_with_retry  # noqa: E402
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


def lane_summary(ledger_path: Path) -> dict[str, Any]:
    """What this lane holds, read from the append-only ledger.

    The manifest used to describe whichever process wrote it last. A resume
    that finds everything already captured is a legitimate run, and it was
    overwriting the completed capture's numbers with its own zeroes -- the
    ledger was made append-only for exactly that reason and the manifest was
    not. So the lane is summarised from the ledger, and any run, including a
    no-op resume, produces the same true totals.

    A symbol-year is counted by its first real outcome; `already-captured` is
    a statement about a later run, not about the lane.
    """

    first: dict[str, str] = {}
    announcements: dict[str, int] = {}
    resumes = 0
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        key = f"{record['symbol']}:{record['roc_year']}"
        if record["outcome"] == "already-captured":
            resumes += 1
            continue
        if key in first:
            continue
        first[key] = record["outcome"]
        announcements[key] = int(record.get("announcements") or 0)

    counts: dict[str, int] = {}
    for outcome in first.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    return {
        "symbol_years_captured": len(first),
        "outcome_counts": dict(sorted(counts.items())),
        "total_announcements": sum(announcements.values()),
        "resume_skips": resumes,
    }


def reconcile(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """Does the ledger account for every listing the store actually holds?

    The observation is written before its ledger line, so a process killed
    between the two leaves data that no ledger entry describes -- and the
    resume, which keys on the observation, then skips it forever. It happened
    once here: 3276/108 was stored as the machine went to sleep, and the lane
    was one line short with nothing to say so.

    Reported rather than repaired. The bytes are the evidence; a count that
    disagrees with them is a question for a person, not something to paper
    over by inventing a ledger line.
    """

    listings = len(already_captured(root))
    return {
        "listing_observations": listings,
        "ledger_reconciled": listings == summary["symbol_years_captured"],
        "symbol_years_without_ledger_outcome": listings
        - summary["symbol_years_captured"],
    }


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

    policy = replace(MOPS_HTML, max_attempts=retry_limit)
    listing_attempts: list[int] = []

    def send_listing(attempt: int) -> Any:
        listing_attempts.append(attempt)
        captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=list_period_resolver,
            transport_context={"attempt": attempt, "client_id": "m3-tpex-actions"},
        )
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
        return response

    try:
        response, _ = request_with_retry(
            policy, send_listing, retry_on=requests.RequestException
        )
    except requests.RequestException as exc:
        return {
            "outcome": "list-transport-error",
            "attempts": listing_attempts[-1] if listing_attempts else 0,
            "error": str(exc)[:160],
        }
    response.encoding = "utf-8"
    listing_text = response.text

    try:
        rows = _listing_rows(listing_text)
    except Exception as exc:  # noqa: BLE001 - parser defects are evidence
        return {"outcome": "list-parse-error", "error": str(exc)[:160]}

    if not rows:
        return {"outcome": "official-no-announcements", "announcements": 0}

    captured_details = 0
    failures: list[str] = []
    for announce_date, params in rows:
        # `(symbol, announce_date)` is not an identity. A company may publish
        # two ex-right announcements on one day, and two MOPS records with
        # different DATE1 may parse to the same announced date; both shapes
        # occur. MOPS identifies a record by DATE1 and SEQ_NO, so that pair
        # goes in the key.
        #
        # The `announced:` segment stays exactly where it was because the
        # downstream build reads the announced date out of this string and
        # writes it to `announced_at`, which decides point-in-time
        # visibility. The suffix is additive so the two lanes captured under
        # the older, coarser key still parse.
        detail_period = (
            f"company:TPEX:{symbol}:announced:{announce_date.isoformat()}"
            f":src:{params.get('DATE1', '')}-{params.get('SEQ_NO', '')}"
        )

        def detail_period_resolver(
            source: Any, _fetched_at: datetime, _params: Mapping[str, Any]
        ) -> str:
            if source.source_id != DETAIL_SOURCE:
                raise ValueError(f"unexpected source {source.source_id}")
            return detail_period

        def send_detail(attempt: int) -> Any:
            detail_captured = CapturedSession(
                base_session,
                store,
                logical_period_resolver=detail_period_resolver,
                transport_context={
                    "attempt": attempt,
                    "client_id": "m3-tpex-actions-detail",
                },
            )
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
            return response

        time.sleep(interval)
        try:
            # Retried like the listing above. Previously this was the one
            # request kind with no retry at all, and because resume keys on
            # the listing observation, each 502 here became a corporate
            # action that no re-run would ever go back for.
            request_with_retry(
                policy, send_detail, retry_on=requests.RequestException
            )
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
    # Defaults to the MOPS policy's own ceiling rather than a second number
    # kept here. A publisher policy that a call site may quietly cap is not a
    # policy; MOPS was given five attempts because it returns intermittent
    # 502s under exactly this kind of sustained per-symbol querying.
    parser.add_argument("--retry-limit", type=int, default=MOPS_HTML.max_attempts)
    parser.add_argument("--limit", type=int, default=0, help="pilot: first N symbols")
    parser.add_argument(
        "--rewrite-manifest",
        action="store_true",
        help="recompute the lane manifest from the ledger and exit",
    )
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
    ledger_path = root / "tpex_actions_ledger.jsonl"

    if args.rewrite_manifest:
        # Repairs a manifest without spending a single request, for a lane
        # whose ledger is complete but whose summary was written by a run
        # that did nothing. Re-running the capture would also rebuild it, at
        # the cost of thousands of pointless resume lines in the ledger.
        summary = lane_summary(ledger_path)
        summary.update(reconcile(root, summary))
        existing = json.loads((root / "tpex_actions_manifest.json").read_bytes())
        existing.update(summary)
        existing["rewritten_at"] = datetime.now(timezone.utc).isoformat()
        existing["rewritten_note"] = (
            "Totals recomputed from the append-only ledger; no requests made."
        )
        for stale in ("started_at", "completed_at", "protected_before",
                      "protected_after", "production_unchanged"):
            existing.pop(stale, None)
        (root / "tpex_actions_manifest.json").write_text(
            json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    before = protected_fingerprints()
    started_at = datetime.now(timezone.utc)
    done = already_captured(root)
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
    # Name what moved instead of collapsing it to a boolean. `False` cannot
    # tell a capture writing where it must not from the legacy daily pipeline
    # updating its own stores, and those need opposite responses.
    changed = sorted(name for name in after if before.get(name) != after[name])
    run_record = {
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "run_outcome_counts": dict(sorted(counts.items())),
        "run_announcements": announcements,
        "protected_changed": changed,
        "protected_before": before,
        "protected_after": after,
    }
    # Append-only, like the ledger. Every run's own record survives the next.
    with (root / "capture_runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run_record, ensure_ascii=False) + "\n")

    manifest = {
        "schema_id": SCHEMA_ID,
        "output_root": str(root),
        "symbol_count": len(symbols),
        "roc_years": years,
        "symbol_year_requests": total,
        "symbol_universe_note": (
            "Symbols are those that actually traded inside the fixed window, "
            "taken from the official TPEx daily quote captures, so delisted "
            "securities are included."
        ),
        "producer": producer,
        "output_policy": "temporary-shadow-only-no-production-writer",
        "ledger_path": str(ledger_path),
        **lane_summary(ledger_path),
        **reconcile(root, lane_summary(ledger_path)),
        "latest_run": run_record,
    }
    (root / "tpex_actions_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(counts, ensure_ascii=False), "announcements=", announcements)
    print("lane totals:", json.dumps(lane_summary(ledger_path), ensure_ascii=False))
    if changed:
        print("PROTECTED STORES CHANGED DURING THIS RUN:", ", ".join(changed))
    failures = sum(
        counts.get(k, 0)
        for k in ("list-transport-error", "list-parse-error", "detail-partial")
    )
    # A protected store that moved is reported loudly but does not make this
    # a failed capture. The legacy production pipeline owns those stores and
    # writes them on its own daily schedule; any run long enough to straddle
    # it would exit non-zero, and a supervisor would relaunch a capture that
    # had in fact succeeded. That is how this lane's manifest was lost once.
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
