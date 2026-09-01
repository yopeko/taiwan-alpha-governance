"""When M0 section 8.1's halts would have fired, and nothing about afterwards.

Diagnostic plan 002. `run_ledger_backtest.py` tracks a high-water mark and a
drawdown and never stops on either; section 8.1's 5% watchlist and 8% hard
stop have existed since 2026-08-02 and no run has ever applied them. So the
54.06% drawdown control 001 reported is a number this account could not
experience: a canary halts at 8% and the rest of that curve never happens.

WHAT THIS DELIBERATELY DOES NOT MEASURE

Not the equity curve after a halt, and not how many halts there were.

Section 8.1 ends a halt with "要求人工決定是否退回 paper" -- the resumption
rule does not exist, by design, because it is a person's judgement. Producing
a post-halt return would mean inventing one, and inventing it now would mean
choosing a free parameter after seeing the results. Counting halts needs the
same invented rule to say when one ended.

So everything here is a first crossing or a share of sessions, and both are
parameter-free.

THE ANCHOR

Sessions are counted from the first session whose NAV differs from the opening
cash -- the first time money moved. Counting from the run's first session
would hand a 252-session warm-up to the momentum candidate and none to a
control that needs no warm-up, and the question is "once it is trading, how
long until it hard-stops", not "how long is its warm-up".
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# M0 section 8.1. Both predate every dataset this project has looked at, so
# applying them adds no free parameter and no multiplicity.
WATCHLIST_DRAWDOWN = 0.05
HARD_STOP_DRAWDOWN = 0.08

# M0 section 9.2: canary is observed for at least 60 trading days before
# formal. A hard stop before then means the observation period cannot finish.
CANARY_MINIMUM_SESSIONS = 60


def first_move(equity: list[dict[str, Any]], opening_cash: float) -> int | None:
    """Index of the first session whose NAV is not still the opening cash."""

    for i, row in enumerate(equity):
        if float(row["nav"]) != opening_cash:
            return i
    return None


def measure(result: dict[str, Any]) -> dict[str, Any]:
    equity = result["equity"]
    opening_cash = float(result["opening_cash"])

    anchor = first_move(equity, opening_cash)
    if anchor is None:
        # Nothing ever traded. Reported rather than treated as "never halted",
        # which is what a null would read as in a summary table.
        return {
            "traded": False,
            "sessions_after_anchor": 0,
            "sessions_until_first_5pct": None,
            "sessions_until_first_8pct": None,
            "date_of_first_5pct": None,
            "date_of_first_8pct": None,
            "return_at_first_8pct": None,
            "share_of_sessions_below_5pct": None,
            "share_of_sessions_below_8pct": None,
            "first_8pct_before_session_60": None,
            "max_drawdown_pct": None,
            "final_drawdown_pct_from_run": result.get("drawdown_pct"),
        }

    live = equity[anchor:]
    high_water = opening_cash
    first_5 = first_8 = None
    date_5 = date_8 = None
    nav_at_8 = None
    below_5 = below_8 = 0
    max_drawdown = 0.0

    for offset, row in enumerate(live):
        nav = float(row["nav"])
        high_water = max(high_water, nav)
        drawdown = 0.0 if high_water <= 0 else (high_water - nav) / high_water
        max_drawdown = max(max_drawdown, drawdown)
        if drawdown >= WATCHLIST_DRAWDOWN:
            below_5 += 1
            if first_5 is None:
                first_5, date_5 = offset, row["session"]
        if drawdown >= HARD_STOP_DRAWDOWN:
            below_8 += 1
            if first_8 is None:
                first_8, date_8, nav_at_8 = offset, row["session"], nav

    return {
        "traded": True,
        "anchor_session": live[0]["session"],
        "sessions_after_anchor": len(live),
        "sessions_until_first_5pct": first_5,
        "sessions_until_first_8pct": first_8,
        "date_of_first_5pct": date_5,
        "date_of_first_8pct": date_8,
        # Against opening cash, which is what the account actually started with.
        "return_at_first_8pct": (
            None if nav_at_8 is None else (nav_at_8 / opening_cash - 1) * 100
        ),
        "share_of_sessions_below_5pct": below_5 / len(live) * 100,
        "share_of_sessions_below_8pct": below_8 / len(live) * 100,
        "first_8pct_before_session_60": (
            None if first_8 is None else first_8 < CANARY_MINIMUM_SESSIONS
        ),
        # Recomputed here rather than taken from the run. `drawdown_pct` in a
        # run manifest is the drawdown **at the last session**, not the worst
        # one: momentum finishes at a new high water and reports 0.00 while
        # having been 54.06% down along the way. A field of this script was
        # called `reported_max_drawdown_pct` and carried that 0.00 until
        # 2026-09-01, which is a name promising something the value was not.
        "max_drawdown_pct": max_drawdown * 100,
        "final_drawdown_pct_from_run": result.get("drawdown_pct"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True, help="run_ledger_backtest --out JSON")
    parser.add_argument("--label", default="")
    # Required, not read from the manifest: the run manifest does not carry
    # the participation rate, and `.get(..., 0)` would have written a zero
    # that reads like a measurement. A field that must be stated cannot be
    # silently wrong.
    parser.add_argument("--participation-rate", required=True)
    args = parser.parse_args(argv)

    result = json.loads(args.result.read_text(encoding="utf-8"))
    out = measure(result)
    out["label"] = args.label or args.result.stem
    out["ranking_function"] = result["strategy"].get("ranking_function", "")
    out["opening_cash"] = float(result["opening_cash"])
    out["participation_rate"] = float(args.participation_rate)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
