"""Capture the exchanges' own trading-status lists (D11).

Until now a security that stopped being quoted was recorded as
`suspension-inferred-from-price-absence`: a policy inference, not an
observation. These six endpoints are what the exchanges actually publish
about it.

    TWSE-DELISTING                   終止上市公司 -- every delisting, dated
    TPEX-DELISTING-HIST              下櫃公司
    TWSE-TRADING-ALTERED-TRADING     集中市場證券變更交易
    TWSE-TRADING-SUSPENSION          集中市場暫停交易證券
    TPEX-TRADING-ALTERED-TRADING     上櫃變更交易、分盤、管理股票與停止交易
    TPEX-TRADING-SUSPENSION-HISTORY  上櫃歷史公布暫停/恢復交易股票

All six were already on the M2 P0 allowlist. None had ever been captured, so
the warehouse inferred what the exchanges were publishing outright.

What they can and cannot do is asymmetric, and the asymmetry is the finding:

* the TWSE delisting list is **historical** -- 264 rows going back years -- so
  a delisting stops being a vendor claim and becomes an official fact;
* TPEx publishes a `SuspensionOfTrading` flag, so a long-term suspension is
  observable there;
* TWSE publishes no suspension list at all. Eight guesses at an
  announcement-style path redirected, and the OpenAPI catalogue has none.
  For TWSE the inference stays -- but bounded, because the delisting list can
  now rule out the other explanation.

Four of the six are current-state. Each capture is therefore a
dated snapshot with `coverage_state = current-only`, which is why this script
records the snapshot date in the logical period rather than pretending to a
range it cannot support.

Writes only into an isolated shadow root; protected stores are fingerprinted
before and after and never written.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from source_state import PRODUCER_COMMIT, SOURCE_STATE_FINGERPRINT  # noqa: E402
from capture_window import protected_fingerprints  # noqa: E402
from retry_policy import OFFICIAL_JSON, headers_of, status_of  # noqa: E402
from market_status_sources import build_m3_registry  # noqa: E402
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
from tw_sepa_screener.sources.captured_http import CapturedSession  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-trading-status-capture/1.0.0"

# Source ids are the ones the M2 P0 allowlist already carries. Every one of
# these was registered and never captured, so the gap this closes is capture,
# not registration -- re-declaring them made each URL resolve to two sources
# and the store refused, which is the allowlist working as designed.
# Method and parameters come from the allowlist entry, not from taste: the
# TPEx delisting archive is a POST needing date=ALL, and calling it as a GET
# resolves to no source at all.
SOURCES: tuple[dict[str, object], ...] = (
    {
        "source_id": "TWSE-DELISTING",
        "url": "https://openapi.twse.com.tw/v1/company/suspendListingCsvAndHtml",
    },
    {
        "source_id": "TPEX-DELISTING-HIST",
        "url": "https://www.tpex.org.tw/www/zh-tw/company/deListed",
        "method": "POST",
        "params": {"date": "ALL", "response": "json"},
    },
    {
        "source_id": "TWSE-TRADING-ALTERED-TRADING",
        "url": "https://openapi.twse.com.tw/v1/exchangeReport/TWT85U",
    },
    {
        "source_id": "TWSE-TRADING-SUSPENSION",
        "url": "https://openapi.twse.com.tw/v1/exchangeReport/TWTAWU",
    },
    {
        "source_id": "TPEX-TRADING-ALTERED-TRADING",
        "url": "https://www.tpex.org.tw/openapi/v1/tpex_cmode",
    },
    {
        "source_id": "TPEX-TRADING-SUSPENSION-HISTORY",
        "url": "https://www.tpex.org.tw/openapi/v1/tpex_spendi_history",
    },
)


def fetch(
    store: RawCaptureStore,
    spec: dict[str, Any],
    period: str,
    *,
    base_session: requests.Session,
    retry_limit: int,
) -> tuple[dict[str, Any], Any]:
    source_id = str(spec["source_id"])
    url = str(spec["url"])
    method = str(spec.get("method") or "GET")
    params = dict(spec.get("params") or {})
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
            transport_context={"attempt": attempt, "client_id": "m3-trading-status"},
        )
        try:
            response = captured.request(method, url, params=params, timeout=60)
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
                }, None
            time.sleep(OFFICIAL_JSON.delay_for(attempt=attempt, headers=headers_of(exc)))
            continue
        except ValueError as exc:
            return {
                "outcome": "payload-error",
                "attempts": attempt,
                "error": str(exc)[:200],
            }, None

        # The OpenAPI hosts answer with a bare JSON array; TPEx answers with
        # its usual {stat, tables} envelope. Emptiness is refused rather than
        # archived as "nothing to report": there are always delisted
        # companies, and a silent empty is how a gap gets recorded as a fact.
        if isinstance(payload, dict):
            stat = str(payload.get("stat", ""))
            if stat and stat.lower() != "ok":
                return {"outcome": "official-not-ok", "attempts": attempt,
                        "stat": stat[:60]}, None
            tables = payload.get("tables")
            rows = (
                len(tables[0].get("data") or [])
                if isinstance(tables, list) and tables
                else None
            )
        else:
            rows = len(payload) if isinstance(payload, list) else None
        if rows == 0 or (isinstance(payload, list) and not payload):
            return {"outcome": "empty-payload", "attempts": attempt}, None
        return {"outcome": "captured", "attempts": attempt, "rows": rows}, payload
    return {"outcome": "transport-error", "attempts": retry_limit}, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--retry-limit", type=int, default=4)
    args = parser.parse_args(argv)

    out_root = Path(args.out_root)
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")
    out_root.mkdir(parents=True, exist_ok=True)

    before = protected_fingerprints()
    snapshot_day = date.today().isoformat()
    period = f"snapshot:{snapshot_day}"

    producer = {
        "name": "tw-sepa-screener",
        "commit": PRODUCER_COMMIT,
        "dirty_fingerprint": SOURCE_STATE_FINGERPRINT,
    }
    store = RawCaptureStore(out_root, build_m3_registry(), producer=producer)
    session = requests.Session()
    session.headers.update({"User-Agent": "tw-alpha-m3-trading-status/1.0"})

    results: list[dict[str, Any]] = []
    for spec in SOURCES:
        outcome, _payload = fetch(
            store, spec, period, base_session=session, retry_limit=args.retry_limit
        )
        results.append({**{k: v for k, v in spec.items() if k != "params"}, **outcome})
        print(f"{spec['source_id']:34s} {outcome.get('outcome')} rows={outcome.get('rows')}")

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "logical_period": period,
        "coverage_state": "current-only",
        "producer": {
            "name": "tw-sepa-screener",
            "commit": PRODUCER_COMMIT,
            "dirty_fingerprint": SOURCE_STATE_FINGERPRINT,
        },
        "results": results,
        "protected_stores_unchanged": before == after,
        "notes": [
            "Four of the six endpoints are current-state. Coverage is "
            "current-only for all of them and the logical period is the "
            "snapshot day; only the two delisting lists carry dates that "
            "can be used point in time.",
            "TWSE publishes no long-term suspension list. TPEx does, as the "
            "SuspensionOfTrading flag of tpex_cmode.",
        ],
    }
    if not manifest["protected_stores_unchanged"]:
        raise SystemExit("protected stores changed during capture; refusing to finish")
    (out_root / "capture_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(r.get("outcome") == "captured" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
