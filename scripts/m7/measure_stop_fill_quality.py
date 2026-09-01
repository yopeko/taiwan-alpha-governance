"""Where the stops actually filled, against where the design assumed they would.

Diagnostic plan 003. M0 section 8's 7.50% total open risk cap rests on an
assumption nobody had checked: that a stop fills at the stop price. Ten
positions at 9.375% of NAV each, all stopped at 8%, is 7.50% -- but only if
each of those exits happens at the stop.

The momentum run refused 152 exits (57 `limit-price-above-limit-up`, 95
`not-tradable-restricted`) against 285 completed trades, so the assumption is
worth checking rather than believing.

WHAT THIS DOES NOT ANSWER

Not "how much of the drawdown happened while positions could not be sold".
That needs per-session refusal records and the run manifests carry only a
whole-run total, so answering it means changing the backtest driver and
re-running everything. Plan section 0 says so rather than letting the swapped
question pass as the original one.

NO FREE PARAMETERS

The designed exit is `entry_price * (1 - stop_pct)` with `stop_pct` read from
the run's own manifest. Nothing here is chosen.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any


def measure(result: dict[str, Any]) -> dict[str, Any]:
    stop_pct = float(result["strategy"]["stop_pct"])
    opening = float(result["opening_cash"])
    stops = [t for t in result["trades"] if t["exit_reason"] == "stop"]

    if not stops:
        return {
            "stops": 0,
            "filled_worse_than_stop": 0,
            "filled_better_than_stop": 0,
            "share_worse_pct": None,
            "median_slippage_pct": None,
            "worst_slippage_pct": None,
            "excess_loss_as_pct_of_opening_nav": 0.0,
            "open_at_end_excluded": result.get("open_at_end", 0),
        }

    worse = better = 0
    excess = 0.0
    slippage: list[float] = []

    for t in stops:
        entry = float(t["entry_price"])
        exit_price = float(t["exit_price"])
        qty = float(t["quantity"])
        designed = entry * (1 - stop_pct)
        # Negative means the fill was below the stop, i.e. worse than designed.
        slippage.append((exit_price - designed) / entry * 100)
        if exit_price < designed:
            worse += 1
            excess += (designed - exit_price) * qty
        elif exit_price > designed:
            better += 1

    return {
        "stops": len(stops),
        "filled_worse_than_stop": worse,
        # Reported because looking only at the bad side would answer a
        # different question than the one asked.
        "filled_better_than_stop": better,
        "share_worse_pct": worse / len(stops) * 100,
        "median_slippage_pct": st.median(slippage),
        "worst_slippage_pct": min(slippage),
        "excess_loss_as_pct_of_opening_nav": excess / opening * 100,
        # Positions still open at the end have no exit price and are left out
        # rather than treated as having filled at the stop.
        "open_at_end_excluded": result.get("open_at_end", 0),
        "rebalance_exits_excluded": len(result["trades"]) - len(stops),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    result = json.loads(args.result.read_text(encoding="utf-8"))
    out = measure(result)
    out["label"] = args.label or args.result.stem
    out["ranking_function"] = result["strategy"].get("ranking_function", "")
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
