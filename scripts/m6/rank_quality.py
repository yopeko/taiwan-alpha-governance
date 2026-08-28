"""Measure whether a ranking function ranks well, separately from whether a
strategy using it made money.

The gap this closes. The candidate report has `selection_logic_measured`,
which asks whether fills followed the declared ranking. Nothing has ever asked
whether the ranking was any good. Momentum-12-1 and inverse-volatility-60 have
been through three comparisons and no number has said how well either of them
ordered anything -- only what the account ended up with, which mixes ranking
quality with cost, timing and the market.

Taken from the LTR paper's actual contribution, which is not LambdaMART: it is
treating this as a ranking problem with a ranking objective. See
`docs/evidence/ltr-paper-learnings-2026-08-28.md`.

This runs no strategy. It is a property of a ranking function on a dataset,
not of a portfolio, so it costs no fills, no slippage and no cost model.

Three measures, reported apart:

  Rank IC     Spearman correlation between score and forward return, per
              cross-section, then the mean and a t statistic over time.
  NDCG@N      How well the top N is ordered, relevance graded by forward
              return quintile. N defaults to the slot count, because the top
              N is the only part a ten-slot account can act on.
  Monotonicity Mean forward return by score quintile. A ranking can have a
              respectable IC and still be useless if the relationship is not
              monotone where it matters.

## A limitation that has to be read with every number here

Forward returns are computed from **unadjusted** closes, because this
warehouse has no adjusted series and M0 forbids deriving one without a
documented method. A security going ex-dividend shows an artificial drop.

That is not uniform noise. High-yield securities systematically show lower
unadjusted forward returns, so any ranking correlated with yield will have its
IC pushed towards that bias. It is a real distortion, its direction is known,
and it is stated rather than corrected -- correcting it silently would be the
undocumented adjustment method M0 prohibits.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_ledger_backtest import (  # noqa: E402
    MOMENTUM_LOOKBACK_SESSIONS,
    RANKINGS,
    VOLATILITY_LOOKBACK_SESSIONS,
    load_dataset,
)

SCHEMA_ID = "tw-alpha-m6-rank-quality/1.0.0"

# Monthly, matching the rebalance cadence the rank-only entry uses and the
# paper's own. A daily cross-section would mostly measure autocorrelation in
# the score rather than anything about ordering.
CROSS_SECTION_SESSIONS = 21
FORWARD_SESSIONS = 21
QUINTILES = 5
DEFAULT_TOP_N = 10


def ranks(values: list[float]) -> list[float]:
    """Average ranks, ties shared. Spearman is Pearson on these."""

    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = shared
        i = j + 1
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        # Every score identical, or every forward return identical. Not a
        # correlation of zero -- a cross-section with nothing to correlate.
        return None
    return sxy / math.sqrt(sxx * syy)


def spearman(scores: list[float], forwards: list[float]) -> float | None:
    return pearson(ranks(scores), ranks(forwards))


def quintile_of(rank_position: int, total: int) -> int:
    return min(QUINTILES - 1, rank_position * QUINTILES // total)


def ndcg_at(scores: list[float], forwards: list[float], n: int) -> float | None:
    """Graded relevance = forward-return quintile, 0 worst to 4 best.

    The top N is the only part a slot-limited account can act on, so ordering
    beyond it is not what the strategy needs to get right.
    """

    total = len(scores)
    if total < n or total < QUINTILES:
        return None
    by_forward = sorted(range(total), key=lambda i: forwards[i])
    relevance = [0] * total
    for position, index in enumerate(by_forward):
        relevance[index] = quintile_of(position, total)

    def dcg(indices: list[int]) -> float:
        return sum(
            (2 ** relevance[i] - 1) / math.log2(rank + 2)
            for rank, i in enumerate(indices[:n])
        )

    by_score = sorted(range(total), key=lambda i: scores[i], reverse=True)
    ideal = sorted(range(total), key=lambda i: relevance[i], reverse=True)
    best = dcg(ideal)
    return dcg(by_score) / best if best > 0 else None


def cross_sections(
    dataset_root: Path, ranking_name: str
) -> list[dict[str, Any]]:
    ranking = RANKINGS[ranking_name]
    if ranking is None:
        raise SystemExit(
            "rank quality needs a ranking function. Arrival order has no "
            "score, so there is nothing whose ordering could be measured"
        )

    sessions, by_session = load_dataset(dataset_root)
    depth = max(MOMENTUM_LOOKBACK_SESSIONS, VOLATILITY_LOOKBACK_SESSIONS) + 2

    closes: dict[tuple[str, str], list[float]] = defaultdict(list)
    close_at: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for session in sessions:
        for key, row in by_session[session].items():
            if row["close"] is not None:
                closes[key].append(float(row["close"]))
                close_at[key][session] = float(row["close"])
                if len(closes[key]) > depth:
                    closes[key].pop(0)

    # Rebuilt rather than carried, so the score at each cross-section is the
    # one the ranking would have produced with that day's history and no more.
    out: list[dict[str, Any]] = []
    history: dict[tuple[str, str], list[float]] = defaultdict(list)
    for index, session in enumerate(sessions):
        for key, row in by_session[session].items():
            if row["close"] is not None:
                history[key].append(float(row["close"]))
                if len(history[key]) > depth:
                    history[key].pop(0)

        if (index + 1) % CROSS_SECTION_SESSIONS:
            continue
        forward_index = index + FORWARD_SESSIONS
        if forward_index >= len(sessions):
            break
        forward_session = sessions[forward_index]

        scores: list[float] = []
        forwards: list[float] = []
        for key, bars in history.items():
            if key not in by_session[session]:
                continue
            score = ranking(bars, len(bars) - 1)
            if score is None:
                continue
            now = close_at[key].get(session)
            later = close_at[key].get(forward_session)
            if not now or later is None or now <= 0:
                continue
            scores.append(score)
            forwards.append(later / now - 1)

        if len(scores) < QUINTILES * 2:
            continue
        out.append(
            {
                "session": session,
                "forward_session": forward_session,
                "securities": len(scores),
                "rank_ic": spearman(scores, forwards),
                "ndcg": ndcg_at(scores, forwards, DEFAULT_TOP_N),
                "scores": scores,
                "forwards": forwards,
            }
        )
    return out


def quintile_returns(sections: list[dict[str, Any]]) -> list[float | None]:
    buckets: list[list[float]] = [[] for _ in range(QUINTILES)]
    for section in sections:
        scores, forwards = section["scores"], section["forwards"]
        total = len(scores)
        by_score = sorted(range(total), key=lambda i: scores[i])
        for position, index in enumerate(by_score):
            buckets[quintile_of(position, total)].append(forwards[index])
    return [sum(b) / len(b) if b else None for b in buckets]


def summarise(sections: list[dict[str, Any]], ranking_name: str) -> dict[str, Any]:
    ics = [s["rank_ic"] for s in sections if s["rank_ic"] is not None]
    ndcgs = [s["ndcg"] for s in sections if s["ndcg"] is not None]
    mean_ic = sum(ics) / len(ics) if ics else None

    t_stat = None
    if mean_ic is not None and len(ics) > 2:
        variance = sum((x - mean_ic) ** 2 for x in ics) / (len(ics) - 1)
        if variance > 0:
            t_stat = mean_ic / math.sqrt(variance / len(ics))

    quintiles = quintile_returns(sections)
    monotone = all(
        a is not None and b is not None and a <= b
        for a, b in zip(quintiles, quintiles[1:])
    )

    return {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "ranking_function": ranking_name,
        "cross_sections": len(sections),
        "cross_section_sessions": CROSS_SECTION_SESSIONS,
        "forward_sessions": FORWARD_SESSIONS,
        "mean_rank_ic": mean_ic,
        "rank_ic_t_stat": t_stat,
        "mean_ndcg_at_10": sum(ndcgs) / len(ndcgs) if ndcgs else None,
        "quintile_mean_forward_return": quintiles,
        "quintile_monotone": monotone,
        "reading_note": (
            "Forward returns use unadjusted closes; this warehouse has no "
            "adjusted series and M0 forbids deriving one without a documented "
            "method. A security going ex-dividend shows an artificial drop, "
            "which pushes the IC of any yield-correlated ranking towards that "
            "bias. Stated rather than corrected. A t statistic over "
            f"{len(ics)} monthly cross-sections is not a significance claim: "
            "the cross-sections overlap in the securities they contain and "
            "the sections are not independent."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--ranking", choices=[k for k in sorted(RANKINGS) if k], required=True
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    sections = cross_sections(args.dataset, args.ranking)
    if not sections:
        raise SystemExit(
            "no cross-section had enough scoreable securities; the ranking "
            "produced nothing to measure rather than measuring as zero"
        )
    report = summarise(sections, args.ranking)

    print(f"排序函式 {report['ranking_function']}")
    print(f"  截面數        {report['cross_sections']}")
    ic = report["mean_rank_ic"]
    print(f"  平均 Rank IC  {ic:+.4f}" if ic is not None else "  平均 Rank IC  n/a")
    t = report["rank_ic_t_stat"]
    print(f"  t 統計        {t:+.2f}" if t is not None else "  t 統計        n/a")
    nd = report["mean_ndcg_at_10"]
    print(f"  NDCG@10       {nd:.4f}" if nd is not None else "  NDCG@10       n/a")
    print("  分位平均未來報酬（最差 → 最佳）:")
    for i, value in enumerate(report["quintile_mean_forward_return"]):
        print(f"     Q{i + 1}  {value:+.4%}" if value is not None else f"     Q{i + 1}  n/a")
    print(f"  單調 {report['quintile_monotone']}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\n寫入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
