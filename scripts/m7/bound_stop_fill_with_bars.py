"""How much could minute data change diagnostic 003? Bounded from daily bars.

Diagnostic 003 measured stop-fill quality from daily data and found 75.6% of
stops filled worse than the designed stop, a median 0.80% short, and excess
loss of 18.86% of opening NAV. The obvious next question is whether that is
right, and the obvious answer is "buy minute data and check".

**That answer is more expensive than it needs to be.** The true fill has to
lie inside the session's own high-low range, and the range is already in the
warehouse. So the answer minute data would give is bounded before any is
bought, and the width of that bound decides whether buying it is worth it.

THE TWO ENDS

A stop-sell triggers when the price reaches the stop, then executes.

    open <= stop   the session gapped through it. The order triggers at the
                   open and the best it can do is the open.
    open >  stop   the price fell through the stop during the session, so the
                   best it can do is the stop itself.

    worst          the session low, in both cases.

The truth is somewhere in between, and only tick data would pin it exactly --
minute bars narrow the window from a day to a minute, they do not close it.
That is the same ambiguity the run manifest already declares as
`stop_assumed_to_precede_target_within_a_session`.

SLIPPAGE IS REMOVED BEFORE COMPARING

The ledger's recorded `exit_price` already has the 0.20% baseline slippage
subtracted, and the published low does not. Comparing them directly would
count the cost model as if it were market movement, so the recorded price is
divided back out first. That correction is small and it is in the direction
that makes the current model look worse, which is why it is done rather than
waved away.

WHAT A NARROW BAND WOULD MEAN

That the daily approximation is already close, and minute data would buy
precision this question does not need. A wide band means the opposite. The
measurement is the same either way; only the decision changes.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

SCHEMA_ID = "tw-alpha-m7-stop-fill-bound/1.0.0"

# `m5/ledger.py`'s own default, the rate the recorded exit price already
# carries. Imported rather than restated so the two cannot drift.
def baseline_slippage() -> float:
    import inspect

    from m5.ledger import Ledger

    return float(inspect.signature(Ledger.__init__).parameters["slippage_rate"].default)


def load_bars(dataset: Path, wanted: set[tuple[str, str, str]]) -> dict:
    import pyarrow.parquet as pq

    path = dataset / "research_dataset.parquet"
    if not path.is_file():
        raise SystemExit(f"no research_dataset.parquet in {dataset}")
    table = pq.read_table(
        path, columns=["market", "symbol", "session_date", "open", "high", "low", "close"]
    )
    bars = {}
    for row in table.to_pylist():
        key = (row["market"], row["symbol"], row["session_date"])
        if key in wanted and row["low"] is not None:
            bars[key] = row
    return bars


def bound(result: dict[str, Any], bars: dict, slippage: float) -> dict[str, Any]:
    """How far the session's own range could move the reported result.

    The reference is the stop **the order was actually submitted at**, not
    `entry x (1 - stop_pct)`. Those two differ, and the difference is the
    defect diagnostic 003 already found -- the stop is set from the signal
    price while the position is entered at the next session's price. Using the
    second as the reference here would fold that old defect into this new
    measurement and report the sum as if it were fill quality.

    The submitted stop is recovered from the recorded fill, which the ledger
    wrote as `stop x (1 - slippage)`.
    """

    opening = float(result["opening_cash"])
    stops = [t for t in result["trades"] if t["exit_reason"] == "stop"]

    modelled_total = 0.0
    best_total = 0.0
    worst_total = 0.0
    bands: list[float] = []
    priced = gapped = missing = 0

    for trade in stops:
        bar = bars.get((trade["market"], trade["symbol"], trade["exit_session"]))
        if bar is None or bar["open"] is None or bar["low"] is None:
            missing += 1
            continue
        quantity = int(trade["quantity"])
        modelled_fill = float(trade["exit_price"])
        submitted_stop = modelled_fill / (1 - slippage)
        opened, low = float(bar["open"]), float(bar["low"])

        # A stop-sell becomes a market order once touched. If the session
        # opened at or below the stop it was already through before anyone
        # could act, and the best available price is the open.
        best = opened if opened <= submitted_stop else submitted_stop
        if opened <= submitted_stop:
            gapped += 1
        worst = low
        if best < worst:
            # An open below the published low cannot happen. Reported rather
            # than clamped into agreement.
            missing += 1
            continue
        priced += 1

        modelled_total += modelled_fill * quantity
        best_total += best * quantity
        worst_total += worst * quantity
        bands.append((best - worst) / submitted_stop * 100)

    def shortfall(total: float) -> float:
        """Proceeds the model assumed, minus proceeds this end would give."""

        return (modelled_total - total) / opening * 100

    return {
        "schema_id": SCHEMA_ID,
        "stop_pct": float(result["strategy"]["stop_pct"]),
        "stops": len(stops),
        "stops_priced": priced,
        "stops_without_a_comparable_bar": missing,
        "gapped_through_the_stop_at_open": gapped,
        "gapped_share_pct": (gapped / priced * 100) if priced else None,
        "proceeds_vs_the_model_pct_of_opening_nav": {
            "best_case_fill_at_stop_or_open": -shortfall(best_total),
            "as_modelled": 0.0,
            "worst_case_fill_at_session_low": -shortfall(worst_total),
        },
        "band_width_pct_of_opening_nav": shortfall(worst_total) - shortfall(best_total),
        "per_trade_band_pct_of_stop": {
            "median": st.median(bands) if bands else None,
            "mean": st.mean(bands) if bands else None,
            "max": max(bands) if bands else None,
        },
        "slippage_removed_to_recover_the_submitted_stop": slippage,
        "reading_note": (
            "The band is a logical bound, not a distribution: a stop order "
            "does not systematically fill at the session low, so the truth "
            "sits nearer the modelled end than the worst one. What the band "
            "shows is that daily bars cannot say where in it the truth is, "
            "and the model picks one point without the data to justify that "
            "choice over any other. A gapped open is the one case granularity "
            "cannot help at all -- the stop was passed before the session "
            "began and no intraday detail recovers a price that never traded."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="a backtest result JSON")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    result = json.loads(args.run.read_text(encoding="utf-8"))
    stops = [t for t in result["trades"] if t["exit_reason"] == "stop"]
    if not stops:
        raise SystemExit(
            f"{args.run} has no stop exits. A bound over nothing would report "
            f"a zero band and read as agreement"
        )
    wanted = {(t["market"], t["symbol"], t["exit_session"]) for t in stops}
    report = bound(result, load_bars(args.dataset, wanted), baseline_slippage())
    report["run"] = str(args.run)
    report["dataset"] = str(args.dataset)

    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
