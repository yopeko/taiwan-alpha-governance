"""Retry the TPEx action detail fetches that failed with a transient error.

The main capture retries the listing request but not the per-announcement
detail requests, so a MOPS 502 leaves a symbol-year with a captured listing
and missing details. Resume in the main script is keyed on the listing, so it
would skip those symbol-years entirely. This pass targets them directly.

It re-derives the announcement parameters from the already-captured listing
blob rather than re-requesting the listing, so the retry cannot silently pick
up a different set of announcements than the one originally observed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402
from tw_sepa_screener.sources.mops_tpex_actions import BASE, _listing_rows  # noqa: E402
from tw_sepa_screener.sources.raw_registry import (  # noqa: E402
    build_p0_formal_registry,
)

DETAIL_SOURCE = "MOPS-TPEX-ACTIONS-DETAIL"


def blob_text(root: Path, blob_id: str) -> str:
    blob = root / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
    raw = blob.read_bytes()
    try:
        return gzip.decompress(raw).decode("utf-8")
    except (OSError, gzip.BadGzipFile):
        return raw.decode("utf-8", errors="replace")


def listing_blob_for(root: Path, symbol: str, roc_year: int) -> str | None:
    target = f"company:TPEX:{symbol}:year:{roc_year}"
    for path in (root / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(path.read_bytes())
        if (
            str(manifest.get("logical_period")) == target
            and str(manifest.get("capture_status")) == "hash-verified"
        ):
            return str(manifest["blob_id"])
    return None


def captured_details(root: Path) -> set[str]:
    done: set[str] = set()
    for path in (root / "raw_observations").rglob("manifest.json"):
        manifest = json.loads(path.read_bytes())
        if (
            str(manifest.get("source_id")) == DETAIL_SOURCE
            and str(manifest.get("capture_status")) == "hash-verified"
        ):
            done.add(str(manifest["logical_period"]))
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--retry-limit", type=int, default=5)
    parser.add_argument(
        "--producer-commit", default="fb87f62f8c2c68e2b85982cd102a35fd935bc0a4"
    )
    parser.add_argument(
        "--dirty-fingerprint",
        default="d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9",
    )
    args = parser.parse_args(argv)

    root = args.root
    ledger = root / "tpex_actions_ledger.jsonl"
    targets = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("outcome") == "detail-partial"
    ]
    if not targets:
        print(json.dumps({"verdict": "nothing-to-retry"}, ensure_ascii=False))
        return 0

    producer = {
        "name": "tw-sepa-screener",
        "commit": args.producer_commit,
        "dirty_fingerprint": args.dirty_fingerprint,
    }
    store = RawCaptureStore(root, build_p0_formal_registry(), producer=producer)
    already = captured_details(root)
    base_session = requests.Session()

    results: list[dict[str, Any]] = []
    for target in targets:
        symbol = str(target["symbol"])
        roc_year = int(target["roc_year"])
        blob_id = listing_blob_for(root, symbol, roc_year)
        if blob_id is None:
            results.append(
                {"symbol": symbol, "roc_year": roc_year, "outcome": "listing-missing"}
            )
            continue
        rows = _listing_rows(blob_text(root, blob_id))
        for announce_date, params in rows:
            period = f"company:TPEX:{symbol}:announced:{announce_date.isoformat()}"
            if period in already:
                continue

            def resolver(
                source: Any, _fetched_at: datetime, _p: Mapping[str, Any]
            ) -> str:
                if source.source_id != DETAIL_SOURCE:
                    raise ValueError(f"unexpected source {source.source_id}")
                return period

            outcome = "retry-failed"
            for attempt in range(1, args.retry_limit + 1):
                captured = CapturedSession(
                    base_session,
                    store,
                    logical_period_resolver=resolver,
                    transport_context={
                        "attempt": attempt,
                        "client_id": "m3-tpex-detail-retry",
                    },
                )
                try:
                    response = captured.post(
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
                    outcome = "captured"
                    break
                except requests.RequestException:
                    time.sleep(min(2.0 ** attempt, 30.0))
            results.append(
                {
                    "symbol": symbol,
                    "roc_year": roc_year,
                    "announced": announce_date.isoformat(),
                    "outcome": outcome,
                }
            )
            print(f"{symbol}/{roc_year} {announce_date} -> {outcome}", flush=True)
            time.sleep(args.interval)

    counts: dict[str, int] = {}
    for item in results:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    report = {
        "retried_at": datetime.now(timezone.utc).isoformat(),
        "targets": len(targets),
        "attempts": len(results),
        "outcome_counts": counts,
        "results": results,
    }
    (root / "tpex_detail_retry.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(counts, ensure_ascii=False))
    return 0 if counts.get("retry-failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
