"""Freeze the day's eligible universe, with a hash and an evidence state.

Contract section 3.2: the population the random baskets are drawn from is the
universe **on the day of the purchase**. A population chosen after the exit is
a chosen control, and one taken later has already dropped whatever delisted in
between -- which flatters the picks by exactly the amount that matters.

So the snapshot has to be written before the order, and it has to say what it
knows.

TWO EVIDENCE STATES, AND THEY ARE NOT INTERCHANGEABLE

    warehouse-tradability   The M3.6 verdict: membership, session, market
                            status, price and corporate action combined into
                            `tradability_state`. Disposal and attention names
                            are already excluded. This is the real answer.

    published-close-only    Only "the exchange published a close for this
                            security today". No disposal filter, no corporate
                            action filter. Weaker, and usable when the
                            warehouse does not reach the date yet.

The second is not a degraded version of the first, it is a different claim. A
snapshot carries which one it is so a comparison built on it can say so too --
M0 section 4.2 forbids letting an assumption read as a verified fact, and a
list of symbols reads as verified unless something next to it says otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_ID = "tw-alpha-universe-snapshot/1.0.0"
CONTRACT_VERSION = "discretionary-research-v1.2.0"

EVIDENCE_STATES = ("warehouse-tradability", "published-close-only")


def collect(prices_root: Path, session: str) -> tuple[list[list[str]], str]:
    """The names available on `session`, and which claim that rests on."""

    import pyarrow.parquet as pq

    path = prices_root / "research_dataset.parquet"
    if not path.is_file():
        path = prices_root / "daily_prices_pit.parquet"
    if not path.is_file():
        raise SystemExit(
            f"neither research_dataset.parquet nor daily_prices_pit.parquet is "
            f"in {prices_root}"
        )

    columns = ["market", "symbol", "session_date", "close"]
    available = pq.read_schema(path).names
    # Only the research dataset carries the M3.6 verdict. A raw price table
    # can say a close exists and nothing more.
    has_verdict = "tradability_state" in available
    if has_verdict:
        columns.append("tradability_state")

    rows = pq.read_table(path, columns=columns).to_pylist()
    names: set[tuple[str, str]] = set()
    for row in rows:
        if row["session_date"] != session or row["close"] is None:
            continue
        if has_verdict and row["tradability_state"] != "eligible":
            continue
        names.add((row["market"], row["symbol"]))

    state = "warehouse-tradability" if has_verdict else "published-close-only"
    return [[m, s] for m, s in sorted(names)], state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices-root", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    names, state = collect(args.prices_root, args.session)
    if not names:
        raise SystemExit(
            f"no securities for {args.session} in {args.prices_root}. An empty "
            f"universe is not a snapshot -- it means the source does not reach "
            f"that date, and a decision recorded against it would have no "
            f"control to be compared with"
        )

    # Over the sorted list only, so the hash names the population and nothing
    # about when it was written. Two snapshots of the same day must agree.
    payload = json.dumps(names, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    snapshot: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "contract_version": CONTRACT_VERSION,
        "session_date": args.session,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(args.prices_root),
        "evidence_state": state,
        "universe_size": len(names),
        "universe_sha256": digest,
        "universe": names,
        "reading_note": (
            "warehouse-tradability excludes disposal, attention and "
            "corporate-action-blocked names; published-close-only does not. "
            "A comparison built on the second must say so."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"{args.session}  {len(names)} 檔  {state}")
    print(f"  sha256 {digest}")
    print(f"  寫入 {args.out}")
    print()
    print("record_decision.py 的 --universe-snapshot 用這個值：")
    print(f"  {args.session}:{state}:sha256:{digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
