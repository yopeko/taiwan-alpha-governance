"""M3.1b: capture official TWSE and TPEx daily prices for a fixed date window.

Extends what `m2_daily_price_shadow` could do: both markets, arbitrary date
ranges, resumable, and it preserves non-trading-day responses as evidence
instead of retrying them away.

Writes only into an isolated temporary shadow root. Protected production
stores are fingerprinted before and after and are never written.

Usage (from the tw-sepa-screener checkout, using its venv):

    ./.venv/Scripts/python.exe <this file> \
        --output-root C:\\tmp\\tw-alpha-m3-capture-20260816-01 \
        --start 2025-01-01 --end 2026-08-03
"""

from __future__ import annotations

import argparse
import hashlib
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
from retry_policy import OFFICIAL_JSON, status_of  # noqa: E402
from tw_sepa_screener.m2_daily_price_pilot import require_daily_price_output_root
from tw_sepa_screener.raw_capture import RawCaptureStore
from tw_sepa_screener.sources.captured_http import CapturedSession
from tw_sepa_screener.sources.raw_registry import build_p0_formal_registry
from tw_sepa_screener.sources.tpex import TpexClient
from tw_sepa_screener.sources.twse import TwseClient

SCHEMA_ID = "tw-alpha-m3-window-capture/1.0.0"

MARKETS: dict[str, dict[str, Any]] = {
    "TWSE": {"source_id": "TWSE-PRICE-HIST", "client": TwseClient},
    "TPEX": {"source_id": "TPEX-PRICE-HIST", "client": TpexClient},
}

PROTECTED = {
    "duckdb": Path(r"C:\project\tw-sepa-screener\data\tw_sepa.duckdb"),
    "legacy_raw": Path(r"C:\project\tw-sepa-screener\data\raw"),
    "stock_master": Path(r"C:\project\tw-sepa-screener\data\stock_master.csv"),
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_fingerprints() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, path in PROTECTED.items():
        if path.is_dir():
            lines = []
            total = 0
            files = sorted(p for p in path.rglob("*") if p.is_file())
            for item in files:
                lines.append(f"{item.relative_to(path).as_posix()}|{file_sha256(item)}")
                total += item.stat().st_size
            payload = "".join(f"{line}\n" for line in sorted(lines)).encode("utf-8")
            out[name] = {
                "files": len(files),
                "bytes": total,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        else:
            out[name] = {
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
    return out


def count_rows(payload: Any) -> int:
    """Largest data table in the payload, which is the full-market quote table."""

    if not isinstance(payload, dict):
        return 0
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return 0
    best = 0
    for table in tables:
        if isinstance(table, dict) and isinstance(table.get("data"), list):
            best = max(best, len(table["data"]))
    return best


def already_captured(root: Path) -> set[tuple[str, str]]:
    """Resume support: (source_id, logical_period) pairs already stored."""

    done: set[tuple[str, str]] = set()
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
        done.add((str(manifest.get("source_id")), str(manifest.get("logical_period"))))
    return done


def retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Kept as a thin wrapper so the shared policy owns the actual decision."""

    headers = response.headers if response is not None else None
    return OFFICIAL_JSON.delay_for(attempt=attempt, headers=headers)


def capture_one(
    store: RawCaptureStore,
    market: str,
    session_date: date,
    *,
    base_session: requests.Session,
    retry_limit: int,
) -> dict[str, Any]:
    """Capture one market-date. Non-trading-day responses are evidence, not errors."""

    spec = MARKETS[market]
    expected_source = spec["source_id"]
    period = f"session:{session_date.isoformat()}"

    def resolve_period(
        source: Any,
        _fetched_at: datetime,
        _parameters: Mapping[str, Any],
    ) -> str:
        if source.source_id != expected_source:
            raise ValueError(
                f"capture resolved an unexpected source: {source.source_id}"
            )
        return period

    last_error: Exception | None = None
    for attempt in range(1, retry_limit + 1):
        captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=resolve_period,
            transport_context={"attempt": attempt, "client_id": "m3-window-capture"},
        )
        client = spec["client"](session=captured)
        try:
            payload = client.get_market_day_payload(session_date)
        except requests.RequestException as exc:
            last_error = exc
            if not OFFICIAL_JSON.should_retry(
                attempt=attempt, status=status_of(exc)
            ) or attempt == retry_limit:
                return {
                    "outcome": "transport-error",
                    "attempts": attempt,
                    "observations": len(captured.observations),
                    "error": str(exc)[:200],
                }
            time.sleep(retry_delay(exc.response, attempt))
            continue
        except ValueError as exc:
            # The bytes were captured before the adapter parsed them, so an
            # official "no matching data" reply is preserved evidence.
            return {
                "outcome": "official-no-data"
                if captured.observations
                else "parse-error-uncaptured",
                "attempts": attempt,
                "observations": len(captured.observations),
                "detail": str(exc)[:200],
            }
        rows = count_rows(payload)
        return {
            "outcome": "captured" if rows > 0 else "official-zero-rows",
            "attempts": attempt,
            "observations": len(captured.observations),
            "rows": rows,
        }
    return {
        "outcome": "transport-error",
        "attempts": retry_limit,
        "observations": 0,
        "error": str(last_error)[:200] if last_error else "unknown",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--markets", default="TWSE,TPEX")
    # 6s floor: a 0.7s interval over a six-year backfill got this IP
    # blocked from the whole of www.twse.com.tw, prices included, and the
    # block outlasted a day. Politeness here is cheaper than a lockout.
    parser.add_argument("--interval", type=float, default=6.0)
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument("--producer-commit", default=PRODUCER_COMMIT)
    parser.add_argument(
        "--dirty-fingerprint",
        default=SOURCE_STATE_FINGERPRINT,
    )
    args = parser.parse_args(argv)

    if args.end < args.start:
        raise SystemExit("end must not precede start")
    markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
    unknown = [m for m in markets if m not in MARKETS]
    if unknown:
        raise SystemExit(f"unknown markets: {unknown}")

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
    ledger_path = root / "capture_ledger.jsonl"
    counts: dict[str, int] = {}

    base_session = requests.Session()
    total_days = (args.end - args.start).days + 1
    index = 0
    current = args.start
    while current <= args.end:
        for market in markets:
            index += 1
            key = (MARKETS[market]["source_id"], f"session:{current.isoformat()}")
            if key in done:
                entry = {"outcome": "already-captured", "attempts": 0}
            else:
                entry = capture_one(
                    store,
                    market,
                    current,
                    base_session=base_session,
                    retry_limit=args.retry_limit,
                )
                time.sleep(args.interval)
            record = {
                "market": market,
                "date": current.isoformat(),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                **entry,
            }
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
            if index % 50 == 0:
                print(
                    f"[{index}/{total_days * len(markets)}] {current} {market} "
                    f"-> {entry['outcome']}  {counts}",
                    flush=True,
                )
        current += timedelta(days=1)

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "output_root": str(root),
        "window": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "markets": markets,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "request_interval_seconds": args.interval,
        "retry_limit": args.retry_limit,
        "producer": producer,
        "outcome_counts": counts,
        "protected_before": before,
        "protected_after": after,
        "production_unchanged": before == after,
        "output_policy": "temporary-shadow-only-no-production-writer",
        "ledger_path": str(ledger_path),
    }
    manifest_path = root / "capture_run_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    failures = counts.get("transport-error", 0) + counts.get("parse-error-uncaptured", 0)
    return 0 if manifest["production_unchanged"] and failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
