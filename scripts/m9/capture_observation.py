"""Record what was actually visible on a trading day, for later comparison.

The shadow observation contract's other half. `observe_session.py` compares an
observation against the warehouse's as-of reconstruction; nothing produced the
observation, so the count could never leave 0 no matter how many days passed.

What makes this an observation rather than a reconstruction is *when* it runs.
The same code executed a week later reads the same tables and produces the
same file -- and that file would be worthless, because the thing being tested
is whether the warehouse's later answer matches what the day actually showed.
Contract section 4: a day cannot be counted retroactively.

So this refuses to observe a session that is not today's. The refusal is the
feature; without it the ledger fills with reconstructions wearing an
observation's name, the count reaches 60, and it measures nothing.

What it captures is deliberately narrow: session state, the traded universe,
tradability, and the bar. Those are the four the contract compares, and
capturing more would invite a later temptation to compare something that was
not part of the claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))

from current_build import PRICES, STATUS  # noqa: E402

CONTRACT_VERSION = "shadow-observation-v1.0.0"
SCHEMA_ID = "tw-alpha-m9-observation/1.0.0"
MARKETS = ("TWSE", "TPEX")


def observe(session: str, prices_root: Path, status_root: Path) -> dict[str, Any]:
    """Read today's published state straight from the capture tables."""

    pq = __import__("pyarrow.parquet", fromlist=["read_table"])

    prices = pq.read_table(
        prices_root / "daily_prices_pit.parquet",
        columns=[
            "market",
            "symbol",
            "session_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    ).to_pylist()
    today = [row for row in prices if row["session_date"] == session]
    # How far the source actually reaches. An empty `today` has two causes
    # that look identical in the output and are not the same thing at all:
    # the market was closed, or the table stops before this date. Only the
    # first is an observation; the second is a table with nothing to say.
    latest_in_source = max((row["session_date"] for row in prices), default="")

    session_states: dict[str, str] = {}
    for market in MARKETS:
        rows = [r for r in today if r["market"] == market]
        # A closing table with rows in it is the exchange saying the session
        # happened. Absence is not the opposite -- it could be a capture that
        # has not run yet -- so it is reported as `unobserved` rather than as
        # `official-closed`, which is a claim only the calendar can make.
        session_states[market] = "official-open" if rows else "unobserved"

    universe = [[r["market"], r["symbol"]] for r in today]
    bars = {
        json.dumps([r["market"], r["symbol"]], ensure_ascii=False): [
            r["open"],
            r["high"],
            r["low"],
            r["close"],
        ]
        for r in today
    }

    return {
        "schema_id": SCHEMA_ID,
        "contract_version": CONTRACT_VERSION,
        "session_date": session,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "session_states": session_states,
        "universe": universe,
        # Left empty: tradability is a warehouse judgement built from status
        # and corporate actions, not something the closing table states. An
        # observation that filled it would be reconstructing, which is the
        # side being compared against.
        "tradability": {},
        "bars": bars,
        "source_roots": {
            "prices": str(prices_root),
            "status": str(status_root),
        },
        "latest_session_in_source": latest_in_source,
        "reading_note": (
            "Captured on the session date. The same code run later would "
            "produce a reconstruction, not an observation, and the contract's "
            "section 4 forbids counting one as the other."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--session",
        help="defaults to today. A past date is refused unless --backfill-unusable",
    )
    parser.add_argument("--prices-root", type=Path, default=PRICES)
    parser.add_argument("--status-root", type=Path, default=STATUS)
    parser.add_argument(
        "--backfill-unusable",
        action="store_true",
        help=(
            "capture a past session anyway, marking the file so it can never "
            "be counted. For inspecting the format, not for the ledger"
        ),
    )
    args = parser.parse_args(argv)

    session = args.session or date.today().isoformat()
    if session != date.today().isoformat() and not args.backfill_unusable:
        raise SystemExit(
            f"{session} is not today. An observation made after the day is a "
            "reconstruction, and the warehouse's reconstruction is the thing "
            "it would be compared against -- the comparison would be of one "
            "answer with itself. Contract section 4 forbids counting such a "
            "day. Pass --backfill-unusable only to inspect the format."
        )

    payload = observe(session, args.prices_root, args.status_root)

    # An observation of a session the source does not reach is empty, and an
    # empty observation diverges from nothing, so it counts towards the 60
    # while measuring nothing. That is the exact failure this file's docstring
    # was written against, arriving through the other door: not a
    # reconstruction wearing an observation's name, but a blank one.
    #
    # Found on 2026-09-01, before scheduling anything: the warehouse's last
    # session was 2026-08-03 and the date was 2026-09-01, so every run would
    # have produced the same empty file and the count would have climbed.
    #
    # The two causes of an empty day are told apart by the source's own reach.
    # Behind it, the market may simply have been closed, and that is a real
    # observation. Past it, there is nothing to observe.
    latest = payload["latest_session_in_source"]
    if latest and session > latest and not args.backfill_unusable:
        raise SystemExit(
            f"the price table stops at {latest} and the session is {session}, "
            f"so there is nothing from that day to observe. Every field would "
            f"be empty and the observation would still count towards the 60. "
            f"Rebuild the warehouse through {session} first, or pass "
            f"--backfill-unusable to inspect the format."
        )

    if args.backfill_unusable:
        payload["unusable"] = (
            "captured after the session date; a reconstruction, not an "
            "observation. Must not be passed to observe_session.py"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"{session}  觀察寫入 {args.out}")
    for market, state in payload["session_states"].items():
        count = sum(1 for k in payload["universe"] if k[0] == market)
        print(f"    {market:<6} {state:<16} {count:>5} 檔")
    if args.backfill_unusable:
        print("\n**已標記為不可用**：晚於場次日擷取，不得用於計數")
    return 0


if __name__ == "__main__":
    sys.exit(main())
