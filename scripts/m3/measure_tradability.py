"""What the warehouse says it knows, counted rather than assumed.

`tradability_state` is the M3.6 verdict every consumer reads: the discretionary
track draws its random-basket population from `eligible`, and a backtest that
cannot trade a name is refused by this field. So how the verdict is distributed
-- and specifically how much of it is `unknown` -- decides what any of those
results can claim.

The five states are not a quality ranking. `ineligible` is mostly the correct,
boring answer that a security was not on this market that session. `unknown` is
the one that matters: it means an input was not covered, and the warehouse said
so instead of guessing. A month with a corporate-action gap should show as
`unknown` and not quietly as `eligible`.

Every count is broken down by the component state that produced it, because
"12% unknown" and "12% unknown, all of it one market's corporate actions in one
month" are different facts and only the second one can be acted on.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))

STATES = ("eligible", "restricted", "blocked", "unknown", "ineligible")

# asof.py reaches `unknown` from exactly two places. Named here so the
# breakdown is a decomposition of the rule and not a guess at it.
UNKNOWN_CAUSES = {
    "membership": "membership_state",
    "coverage": ("market_status_state", "corporate_action_state"),
}


def load(dataset: Path):
    import pyarrow.parquet as pq

    path = dataset / "research_dataset.parquet"
    if not path.is_file():
        raise SystemExit(f"no research_dataset.parquet in {dataset}")
    return pq.read_table(
        path,
        columns=[
            "market",
            "session_date",
            "symbol",
            "membership_state",
            "session_state",
            "market_status_state",
            "corporate_action_state",
            "price_state",
            "tradability_state",
            "reason_codes",
        ],
    )


def distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    counts = Counter(r["tradability_state"] for r in rows)
    out: dict[str, Any] = {
        "rows": total,
        "counts": {s: counts.get(s, 0) for s in STATES},
        "share": {
            s: (round(100.0 * counts.get(s, 0) / total, 2) if total else 0.0)
            for s in STATES
        },
    }
    unseen = set(counts) - set(STATES)
    if unseen:
        # A state this script does not know about is a change in asof.py that
        # nothing here would otherwise report.
        out["states_not_in_this_script"] = sorted(unseen)
    return out


def why_unknown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Which input was uncovered, for the rows the warehouse refused to judge."""

    unknown = [r for r in rows if r["tradability_state"] == "unknown"]
    membership = [r for r in unknown if r["membership_state"] == "unknown"]
    status_gap = [
        r for r in unknown if r["market_status_state"] == "no-coverage"
    ]
    action_gap = [
        r for r in unknown if r["corporate_action_state"] == "no-coverage"
    ]
    both = [r for r in status_gap if r["corporate_action_state"] == "no-coverage"]
    return {
        "unknown_rows": len(unknown),
        "membership_unknown": len(membership),
        "market_status_no_coverage": len(status_gap),
        "corporate_action_no_coverage": len(action_gap),
        "both_no_coverage": len(both),
        "by_market": dict(Counter(r["market"] for r in unknown)),
        "sessions": {
            "first": min((r["session_date"] for r in unknown), default=None),
            "last": max((r["session_date"] for r in unknown), default=None),
            "distinct": len({r["session_date"] for r in unknown}),
        },
    }


def per_session(rows: list[dict[str, Any]], session: str) -> dict[str, Any]:
    day = [r for r in rows if r["session_date"] == session]
    if not day:
        raise SystemExit(
            f"{session} is not in this dataset. An empty day would report a "
            f"clean distribution for a session that was never built"
        )
    out = {"session": session, "all_markets": distribution(day)}
    for market in sorted({r["market"] for r in day}):
        out[market] = distribution([r for r in day if r["market"] == market])
    out["why_unknown"] = why_unknown(day)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--session",
        action="append",
        default=None,
        help="repeatable; report one day in full as well as the whole table",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="also report the window from this session onward, by market",
    )
    args = parser.parse_args(argv)

    rows = load(args.dataset).to_pylist()
    report: dict[str, Any] = {
        "dataset": str(args.dataset),
        "sessions": {
            "first": min(r["session_date"] for r in rows),
            "last": max(r["session_date"] for r in rows),
            "distinct": len({r["session_date"] for r in rows}),
        },
        "whole_table": distribution(rows),
        "whole_table_why_unknown": why_unknown(rows),
    }
    for market in sorted({r["market"] for r in rows}):
        report[f"whole_table_{market}"] = distribution(
            [r for r in rows if r["market"] == market]
        )

    if args.since:
        window = [r for r in rows if r["session_date"] >= args.since]
        report[f"since_{args.since}"] = {
            "all_markets": distribution(window),
            "why_unknown": why_unknown(window),
            **{
                m: distribution([r for r in window if r["market"] == m])
                for m in sorted({r["market"] for r in window})
            },
        }

    for session in args.session or []:
        report[f"session_{session}"] = per_session(rows, session)

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
