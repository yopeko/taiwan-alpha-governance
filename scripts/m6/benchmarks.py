"""M0 section 9.1's minimum comparison set, in one table.

The contract lists what every challenger has to be reported against:

    現金、適當市場指數或 ETF benchmark、合資格股票池等權、
    equal-size same-pool random selection、簡單動能／相對強度策略、
    目前 champion 及 challenger

Four of those seven were reachable before this file existed. The random
selection arrived with control 001, momentum and inverse volatility are
rankings in the backtester, and the challenger is the run itself. **Cash, the
index and the equal-weight universe were listed and never built**, so no
candidate report has ever carried them and none could have.

WHAT EACH ONE ANSWERS

    cash                did holding nothing beat it
    index               did the market give this away
    equal-weight pool   did picking anything at all beat picking these

They are different questions and a report needs all three. M0 requires them
jointly, not as alternatives.

TWO OF THEM ARE GROSS, AND THAT IS NOT A DETAIL

The index is published, not traded: nobody pays commission to hold TAIEX. The
equal-weight eligible universe is roughly two thousand names, which at the M0
scale is a few tens of TWD a position -- below one share of most of them and
far below the 20 TWD minimum commission.

The discretionary track ran exactly this benchmark through the real cost model
on 2026-09-03 and got **-24.63% against a true +25.47%**: fifty points, in the
direction that flatters the picks. Charging an execution model to a portfolio
nobody can execute measures the fee schedule, not the market.

So both are gross and say so, and every row carries `basis`. A report that
puts a net strategy return next to them has to state the mismatch rather than
let a reader assume it away.

PRICE INDEX OR TOTAL RETURN

The research dataset carries official **unadjusted** closes, so a strategy run
on it never receives a dividend. The price index does not include dividends
either, which makes it the consistent comparison; the total-return index is
what the market actually paid, which makes it the honest one.

Both are reported. Neither is the default, because picking one silently is how
a benchmark ends up chosen to suit the answer.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))

SCHEMA_ID = "tw-alpha-m6-benchmarks/1.0.0"

# M0 section 9.1, verbatim, so a reader can check the list rather than trust
# that it was read correctly. `covered_here` is what this file supplies.
MINIMUM_SET = {
    "cash": "covered here",
    "market index or ETF benchmark": "covered here",
    "equal-weight eligible universe": "covered here",
    "equal-size same-pool random selection": "run_ledger_backtest random-seed-N",
    "simple momentum / relative strength": "run_ledger_backtest momentum-12-1",
    "current champion": "none exists -- nothing is `validated`",
    "challenger": "the run being reported",
}


def load_prices(dataset: Path, entry: str, exit_session: str):
    """Eligible names on the entry session, and closes at both ends.

    Delisted names keep their last observed close instead of being dropped.
    The universe is the one that existed on the entry session -- taking it
    later removes whatever died in between, which flatters anything compared
    against it.
    """

    import pyarrow.parquet as pq

    path = dataset / "research_dataset.parquet"
    if not path.is_file():
        raise SystemExit(f"no research_dataset.parquet in {dataset}")
    table = pq.read_table(
        path,
        columns=["market", "symbol", "session_date", "close", "tradability_state"],
    )

    eligible: list[tuple[str, str]] = []
    entry_close: dict[tuple[str, str], float] = {}
    last_close: dict[tuple[str, str], tuple[str, float]] = {}
    for row in table.to_pylist():
        session = row["session_date"]
        if session < entry or session > exit_session:
            continue
        key = (row["market"], row["symbol"])
        close = row["close"]
        if close is None:
            continue
        if session == entry:
            entry_close[key] = float(close)
            if row["tradability_state"] == "eligible":
                eligible.append(key)
        prior = last_close.get(key)
        if prior is None or session > prior[0]:
            last_close[key] = (session, float(close))
    return sorted(eligible), entry_close, last_close


def equal_weight_universe(
    eligible, entry_close, last_close, exit_session
) -> dict[str, Any]:
    """Gross, equal-weight, held. The mean of the individual returns."""

    returns = []
    delisted = 0
    for key in eligible:
        start = entry_close.get(key)
        end = last_close.get(key)
        if not start or start <= 0 or end is None:
            continue
        if end[0] != exit_session:
            delisted += 1
        returns.append(end[1] / start - 1)
    if not returns:
        return {"return_pct": None, "names": 0, "delisted_in_window": delisted}
    return {
        "return_pct": st.mean(returns) * 100,
        "median_name_return_pct": st.median(returns) * 100,
        "basis": "gross",
        "names": len(returns),
        "delisted_in_window": delisted,
    }


def index_returns(index_root: Path, entry: str, exit_session: str) -> dict[str, Any]:
    import pyarrow.parquet as pq

    path = index_root / "index_benchmarks_pit.parquet"
    if not path.is_file():
        raise SystemExit(
            f"no index_benchmarks_pit.parquet in {index_root}. Build it with "
            f"scripts/m3/build_index_benchmarks.py -- M0 section 9.1 requires "
            f"this column and a report without it is incomplete"
        )
    rows = pq.read_table(path).to_pylist()

    out: dict[str, Any] = {}
    for key in sorted({f"{r['index_id']}:{r['basis']}" for r in rows}):
        index_id, basis = key.split(":")
        series = {
            r["session_date"]: r["close"]
            for r in rows
            if r["index_id"] == index_id and r["basis"] == basis
        }
        start, end = series.get(entry), series.get(exit_session)
        if start is None or end is None:
            # Named rather than omitted: a benchmark that quietly disappears
            # for a window is indistinguishable from one that was never asked
            # for, and M0 requires this column to be present.
            out[key] = {
                "return_pct": None,
                "basis": "gross",
                "missing": [
                    s for s, v in (("entry", start), ("exit", end)) if v is None
                ],
            }
            continue
        out[key] = {
            "return_pct": (end / start - 1) * 100,
            "basis": "gross",
            "entry_close": start,
            "exit_close": end,
        }
    return out


def build(
    dataset: Path, index_root: Path, entry: str, exit_session: str
) -> dict[str, Any]:
    if exit_session <= entry:
        raise SystemExit(f"exit {exit_session} is not after entry {entry}")

    eligible, entry_close, last_close = load_prices(dataset, entry, exit_session)
    if not eligible:
        raise SystemExit(
            f"no eligible names on {entry}. An empty universe would make the "
            f"equal-weight column read as 0% rather than as absent"
        )

    return {
        "schema_id": SCHEMA_ID,
        "entry_session": entry,
        "exit_session": exit_session,
        "eligible_universe_size": len(eligible),
        "arms": {
            # Nominal. A deposit rate would be a claim about an account this
            # project does not have, and M0 lists cash, not a cash yield.
            "cash": {"return_pct": 0.0, "basis": "nominal"},
            "equal_weight_eligible_universe": equal_weight_universe(
                eligible, entry_close, last_close, exit_session
            ),
            **{f"index_{k}": v for k, v in index_returns(index_root, entry, exit_session).items()},
        },
        "minimum_comparison_set": MINIMUM_SET,
        "reading_note": (
            "Every arm here is gross. A strategy return from the backtester is "
            "net of commission, tax and slippage, so a report placing them side "
            "by side has to say so. The index is published rather than traded, "
            "and the equal-weight universe is about two thousand names, which "
            "at the M0 scale is a position too small to buy one share of -- "
            "charging it a cost model measures the fee schedule, not the "
            "market. Measured 2026-09-03: doing that cost 50 percentage points, "
            "in the direction that flatters the strategy."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--entry-session", required=True)
    parser.add_argument("--exit-session", required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build(args.dataset, args.index_root, args.entry_session, args.exit_session),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
