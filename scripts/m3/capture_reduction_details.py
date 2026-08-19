"""Capture the per-announcement capital-reduction detail documents.

The two reduction listings both end in a 詳細資料 column holding
"STK_NO,FILE_DATE", which addresses one announcement document. That document
is the only official place carrying two facts the listings omit:

* 停止買賣日期 for a reduction that has already resumed — the resumption table
  publishes only 恢復買賣日期, so without this the halt interval has an end and
  no beginning;
* FILE_DATE, the exchange's own date stamp on the announcement, which is the
  only publisher-supplied date that precedes the halt.

Keys are derived from an already-captured listing archive, never enumerated.
Requesting an arbitrary (code, date) pair would either invent announcements
that do not exist or miss ones nobody thought to guess; the listing states
exactly which documents exist.

Writes only into an isolated temporary shadow root; protected production
stores are fingerprinted before and after and are never written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from capture_window import protected_fingerprints  # noqa: E402
from retry_policy import OFFICIAL_JSON, headers_of, status_of  # noqa: E402
from market_status_sources import (  # noqa: E402
    TWSE_REDUCTION_DETAIL_URL,
    build_m3_registry,
    detail_parameters,
    detail_period,
)
from tw_sepa_screener.m2_daily_price_pilot import (  # noqa: E402
    require_daily_price_output_root,
)
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-reduction-detail-capture/1.0.0"
SOURCE_ID = "TWSE-REDUCTION-DETAIL-HIST"

LISTING_ENDPOINTS = (
    "capital-reduction-resumption-history",
    "capital-reduction-forecast-history",
)

# The listing page builds the link by stripping every character outside
# [\w,.-] and the detail page splits the remainder on commas, taking the first
# field as STK_NO and the second as FILE_DATE. This mirrors that exactly.
DETAIL_CELL = re.compile(r"(\d{4,6}),(\d{8})(?:,\d{8})*")
STRIPPED = re.compile(r"[^\w,.-]")


def detail_keys(archive: Path) -> list[dict[str, str]]:
    """Every (STK_NO, FILE_DATE) named by a captured reduction listing."""

    found: dict[tuple[str, str], dict[str, str]] = {}
    for manifest_path in sorted((archive / "raw_observations").rglob("manifest.json")):
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("endpoint_id") not in LISTING_ENDPOINTS:
            continue
        if str(manifest.get("capture_status")) != "hash-verified":
            continue
        blob_id = str(manifest["blob_id"])
        payload = (
            archive / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
        )
        if not payload.is_file():
            continue
        document = json.loads(payload.read_bytes().decode("utf-8-sig"))
        for row in document.get("data") or []:
            for cell in row:
                match = DETAIL_CELL.fullmatch(STRIPPED.sub("", str(cell)))
                if not match:
                    continue
                stk_no, file_date = match.group(1), match.group(2)
                found.setdefault(
                    (stk_no, file_date),
                    {
                        "stk_no": stk_no,
                        "file_date": file_date,
                        "endpoint_id": str(manifest["endpoint_id"]),
                    },
                )
    return [found[key] for key in sorted(found)]


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


def capture_one(
    store: RawCaptureStore,
    stk_no: str,
    file_date: str,
    *,
    base_session: requests.Session,
    retry_limit: int,
) -> dict[str, Any]:
    period = detail_period(stk_no, file_date)
    params = detail_parameters(stk_no, file_date)

    def resolve_period(
        source: Any, _fetched_at: datetime, _parameters: Mapping[str, Any]
    ) -> str:
        if source.source_id != SOURCE_ID:
            raise ValueError(f"capture resolved unexpected source {source.source_id}")
        return period

    for attempt in range(1, retry_limit + 1):
        captured = CapturedSession(
            base_session,
            store,
            logical_period_resolver=resolve_period,
            transport_context={"attempt": attempt, "client_id": "m3-reduction-detail"},
        )
        try:
            response = captured.get(
                TWSE_REDUCTION_DETAIL_URL, params=params, timeout=60
            )
            response.raise_for_status()
            response.encoding = "utf-8-sig"
            payload = response.json()
        except requests.RequestException as exc:
            if not OFFICIAL_JSON.should_retry(
                attempt=attempt, status=status_of(exc)
            ) or attempt == retry_limit:
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

        stat = str(payload.get("stat", "")) if isinstance(payload, dict) else ""
        rows = payload.get("data") if isinstance(payload, dict) else None
        row_count = len(rows) if isinstance(rows, list) else 0
        if stat.lower() != "ok":
            # Preserved as evidence, not discarded: an announcement the listing
            # names but the detail service will not serve is a real finding.
            return {
                "outcome": "official-not-ok",
                "attempts": attempt,
                "observations": len(captured.observations),
                "stat": stat[:80],
            }
        return {
            "outcome": "captured" if row_count else "official-empty-document",
            "attempts": attempt,
            "observations": len(captured.observations),
            "rows": row_count,
        }
    return {"outcome": "transport-error", "attempts": retry_limit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--listing-archive",
        type=Path,
        required=True,
        help="captured reduction listing archive the detail keys come from",
    )
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

    keys = detail_keys(args.listing_archive)
    if not keys:
        print("no detail keys found in listing archive", file=sys.stderr)
        return 2

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
    ledger_path = root / "reduction_detail_ledger.jsonl"
    counts: dict[str, int] = {}

    base_session = requests.Session()
    for key in keys:
        period = detail_period(key["stk_no"], key["file_date"])
        if period in done:
            entry = {"outcome": "already-captured", "attempts": 0}
        else:
            entry = capture_one(
                store,
                key["stk_no"],
                key["file_date"],
                base_session=base_session,
                retry_limit=args.retry_limit,
            )
            time.sleep(args.interval)
        record = {
            "source_id": SOURCE_ID,
            "stk_no": key["stk_no"],
            "file_date": key["file_date"],
            "named_by": key["endpoint_id"],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **entry,
        }
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        print(
            f"{key['stk_no']:>6} {key['file_date']} -> {entry['outcome']}"
            f"  rows={entry.get('rows', '-')}",
            flush=True,
        )

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "output_root": str(root),
        "listing_archive": str(args.listing_archive),
        "source_id": SOURCE_ID,
        "key_count": len(keys),
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outcome_counts": counts,
        "producer": producer,
        "protected_before": before,
        "protected_after": after,
        "production_unchanged": before == after,
        "output_policy": "temporary-shadow-only-no-production-writer",
        "ledger_path": str(ledger_path),
        "key_derivation": "detail-column-of-captured-listing-never-enumerated",
    }
    (root / "reduction_detail_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
