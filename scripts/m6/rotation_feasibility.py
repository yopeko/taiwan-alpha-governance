"""Can a rotating strategy afford its own turnover? Measured, not simulated.

The question was whether replacing a weak holding with a better candidate
improves things. Answering it with a backtest would have meant building a
ranking, a replacement rule, a control arm and a report -- and the arithmetic
that decides it needs none of those.

Full re-ranking makes turnover a property of the ranking, not a choice: the
book is whatever the ranking says each session, so how often the ranking
changes is how often the account trades. That is measurable from the frozen
dataset alone.

Three passes, each answering the objection the previous one raised:

1. `churn` -- how much a top-N changes from session to session, per ranking.
2. `cost`  -- what that turnover costs at each of ADR-0002's two scales.
3. `gate`  -- whether requiring the score gap to exceed the round-trip cost
   brings it back into reach.

The cost model here is deliberately an upper bound. It assumes every intended
rotation executes, while the ledger would refuse many of them for cost, cash
or liquidity. A refused rotation is cheaper and also not the strategy that was
designed, so neither reading rescues it.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

SLOTS = 10

# Round-trip cost as a share of turnover, measured on the M6.1 runs rather
# than assumed: 3.12% at the M0 execution scale, 0.42% at the reference scale.
SCALES = ((10_000, 3.12), (150_000, 0.42))

# Position size as a share of NAV under M0 section 8: the 0.75% planned risk
# over the 8% median stop distance measured in M6 Phase 0. An approximation,
# and stated as one -- the exact figure moves with the stop of each signal.
POSITION_SHARE = 0.09375


def load(dataset: Path) -> dict[tuple[str, str], list[tuple[str, float, str]]]:
    table = pq.read_table(
        dataset / "research_dataset.parquet",
        columns=["session_date", "market", "symbol", "close", "tradability_state"],
    )
    bars: dict[tuple[str, str], list[tuple[str, float, str]]] = defaultdict(list)
    for row in table.to_pylist():
        if row["close"] is not None:
            bars[(row["market"], row["symbol"])].append(
                (row["session_date"], float(row["close"]), row["tradability_state"])
            )
    for series in bars.values():
        series.sort()
    return bars


def breakout_strength(closes: list[float], i: int, n: int = 20) -> float | None:
    """How far today's close sits above the previous n closes. A same-day event."""

    if i < n:
        return None
    high = max(closes[i - n : i])
    return (closes[i] - high) / high if closes[i] > high and high > 0 else None


def trailing_return(closes: list[float], i: int, n: int) -> float | None:
    if i < n or closes[i - n] <= 0:
        return None
    return closes[i] / closes[i - n] - 1


def position_in_range(closes: list[float], i: int, n: int) -> float | None:
    if i < n:
        return None
    window = closes[i - n : i + 1]
    low, high = min(window), max(window)
    return (closes[i] - low) / (high - low) if high > low else None


RANKINGS = {
    "breakout-20": lambda c, i: breakout_strength(c, i),
    "return-20": lambda c, i: trailing_return(c, i, 20),
    "return-60": lambda c, i: trailing_return(c, i, 60),
    "return-120": lambda c, i: trailing_return(c, i, 120),
    "range-position-60": lambda c, i: position_in_range(c, i, 60),
}


def scores_by_session(bars, ranking) -> dict[str, dict[tuple[str, str], float]]:
    out: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
    for key, series in bars.items():
        closes = [b[1] for b in series]
        for i, (session, _, state) in enumerate(series):
            if state != "eligible":
                continue
            score = ranking(closes, i)
            if score is not None:
                out[session][key] = score
    return out


def churn(scores) -> tuple[int, float, float]:
    """Names entering the top-N each session, when the book is the top-N."""

    previous: set[tuple[str, str]] = set()
    counts: list[int] = []
    for session in sorted(scores):
        top = {k for k, _ in sorted(scores[session].items(), key=lambda kv: -kv[1])[:SLOTS]}
        if previous:
            counts.append(len(top - previous))
        previous = top
    if not counts:
        return 0, 0.0, 0.0
    return sum(counts), sum(counts) / len(counts), counts.count(SLOTS) / len(counts) * 100


def gated_swaps(scores, gate: float) -> int:
    """Rotations surviving a gate of `gate` on the score gap.

    The gate is in the ranking's own units. Where the ranking is a trailing
    return, a gap is already a return, so setting the gate to the measured
    round-trip cost introduces no fitted number.
    """

    held: set[tuple[str, str]] = set()
    swaps = 0
    for session in sorted(scores):
        today = scores[session]
        held = {k for k in held if k in today}
        for key, _ in sorted(today.items(), key=lambda kv: -kv[1]):
            if len(held) >= SLOTS:
                break
            held.add(key)
        while held:
            weakest = min(held, key=lambda k: today[k])
            outsiders = [(s, k) for k, s in today.items() if k not in held]
            if not outsiders:
                break
            best_score, best_key = max(outsiders)
            if best_score - today[weakest] <= gate:
                break
            held.discard(weakest)
            held.add(best_key)
            swaps += 1
    return swaps


def cost_multiple(swaps: int, capital: float, pct_of_turnover: float) -> float:
    """Six-year cost as a multiple of opening capital."""

    notional = capital * POSITION_SHARE
    return swaps * notional * 2 * (pct_of_turnover / 100) / capital


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)

    bars = load(args.dataset)

    print("ranking             per-session  all-swapped   total    " + "  ".join(
        f"{c:,}x-cost" for c, _ in SCALES
    ))
    for name, ranking in RANKINGS.items():
        scores = scores_by_session(bars, ranking)
        total, per, allswap = churn(scores)
        line = f"{name:<20}{per:>11.2f}{allswap:>12.1f}%{total:>9,}"
        for capital, pct in SCALES:
            line += f"{cost_multiple(total, capital, pct):>11.1f}x"
        print(line)

    print()
    print("cost gate on return-120, gate in trailing-return units")
    scores = scores_by_session(bars, RANKINGS["return-120"])
    baseline = None
    for gate in (0.0, 0.0042, 0.0312, 0.10, 0.25):
        swaps = gated_swaps(scores, gate)
        baseline = baseline or swaps
        line = f"  gate {gate*100:>6.2f}%  swaps {swaps:>7,}  {swaps/baseline*100:>5.1f}% of ungated"
        for capital, pct in SCALES:
            line += f"{cost_multiple(swaps, capital, pct):>11.1f}x"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
