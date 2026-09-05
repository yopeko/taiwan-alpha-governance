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
    RANKING_HISTORY_SESSIONS,
    RANKINGS,
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
    # Deep enough for whichever ranking is being measured, read from the
    # declaration beside the ranking rather than from the two constants that
    # happened to be the deepest when this was written. A five-session
    # cumulative measured against a two-session history returns None on every
    # security and reports nothing at all.
    depth = max(RANKING_HISTORY_SESSIONS.values()) + 2

    close_at: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for session in sessions:
        for key, row in by_session[session].items():
            if row.close is not None:
                close_at[key][session] = float(row.close)

    # Rebuilt rather than carried, so the score at each cross-section is the
    # one the ranking would have produced with that day's history and no more.
    out: list[dict[str, Any]] = []
    # `Bar` objects, not closes. A ranking that reads the institutional
    # columns needs the whole row, and building a second parallel list per
    # column is how the two get one session out of step with each other --
    # silently, and in the direction that flatters the result.
    #
    # Appended only where a close exists, which is what the driver does, so
    # the history a ranking sees here is the history it would see there.
    history: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for index, session in enumerate(sessions):
        for key, row in by_session[session].items():
            if row.close is not None:
                history[key].append(row)
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
        keys: list[tuple[str, str]] = []
        # How many of the securities on the board this ranking could not score.
        # Diagnostic plan 005 requires it: a signal that cannot score half the
        # pool has its IC measured on a filtered universe, and the filter is
        # the signal's own -- which is a property of the signal, not noise.
        eligible = unscored = 0
        for key, bars in history.items():
            if key not in by_session[session]:
                continue
            eligible += 1
            # **With the identity, which this call omitted until 2026-09-05.**
            #
            # The driver passes `market`, `symbol` and `session`; this did not,
            # so every ranking that reads them saw the empty string. The
            # twenty random controls score by `sha256(seed:market:symbol:
            # session)`, so all twenty gave **the same score to every security
            # in every cross-section** -- zero variance, a Spearman of None,
            # and a top-10 that was 14 distinct names across 68 sessions
            # instead of several hundred.
            #
            # The controls were therefore not controls here. `momentum-12-1`
            # and `inverse-volatility-60` read only prices and are unaffected,
            # which is why rank-quality 001 was right and this went unseen.
            score = ranking(
                bars, len(bars) - 1,
                market=key[0], symbol=key[1], session=session,
            )
            if score is None:
                unscored += 1
                continue
            now = close_at[key].get(session)
            later = close_at[key].get(forward_session)
            if not now or later is None or now <= 0:
                continue
            scores.append(score)
            forwards.append(later / now - 1)
            keys.append(key)

        if len(scores) < QUINTILES * 2:
            continue
        top = sorted(range(len(scores)), key=lambda i: -scores[i])[:DEFAULT_TOP_N]
        out.append(
            {
                "session": session,
                "forward_session": forward_session,
                "securities": len(scores),
                "eligible": eligible,
                "unscored": unscored,
                "rank_ic": spearman(scores, forwards),
                "ndcg": ndcg_at(scores, forwards, DEFAULT_TOP_N),
                "scores": scores,
                "forwards": forwards,
                # The names this ranking would actually have acted on.
                "top_keys": [keys[i] for i in top],
            }
        )
    return out


def ends_delisted(dataset_root: Path) -> set[tuple[str, str]]:
    """Securities the lifecycle source calls delisted on the window's last session.

    Read from the dataset rather than inferred from how long a price has been
    absent: `membership_state` records it, and guessing at something already
    recorded is how the halt/delist distinction got blurred in the first place.
    """

    table = pq.read_table(
        dataset_root / "research_dataset.parquet",
        columns=["market", "symbol", "session_date", "membership_state"],
    )
    sessions = table.column("session_date").to_pylist()
    last = max(sessions)
    return {
        (m, s)
        for m, s, sd, ms in zip(
            table.column("market").to_pylist(),
            table.column("symbol").to_pylist(),
            sessions,
            table.column("membership_state").to_pylist(),
        )
        if sd == last and ms == "delisted"
    }


def delisting_rate(
    sections: list[dict[str, Any]], ends_delisted: set[tuple[str, str]]
) -> dict[str, Any]:
    """How often the top N is a security that stops trading before the window ends.

    Added 2026-09-05, after `inverse-volatility-60` was measured entering 76
    securities of which **15.8% ended delisted**, against a random median of
    2.0% and above all twenty controls. The mechanism is mechanical: realised
    volatility falls when a security trades thinly, and a security often trades
    thinly before it is suspended.

    **A ranking can have a real IC and still be unusable**, because a position
    in a security that stops trading can never be closed and permanently
    consumes a slot. The IC does not see this at all: a security with no
    forward return is simply absent from the cross-section. So the two numbers
    are reported side by side rather than one standing for the other.

    The base rate is the same measurement over every security that was scored,
    which is the honest comparison -- a ranking cannot be blamed for a pool
    that is full of them.
    """

    picked = 0
    picked_delisted = 0
    pool: set[tuple[str, str]] = set()
    for section in sections:
        for key in section["top_keys"]:
            picked += 1
            if key in ends_delisted:
                picked_delisted += 1
        pool.update(section["top_keys"])
    scored_pool: set[tuple[str, str]] = set()
    for section in sections:
        scored_pool.update(section["top_keys"])
    return {
        "top_n_slots_measured": picked,
        "top_n_delisted_share_pct": (picked_delisted / picked * 100) if picked else None,
        "distinct_names_in_top_n": len(pool),
        "distinct_delisted_in_top_n": len(pool & ends_delisted),
        "distinct_delisted_share_pct": (
            len(pool & ends_delisted) / len(pool) * 100 if pool else None
        ),
    }


def quintile_returns(sections: list[dict[str, Any]]) -> list[float | None]:
    buckets: list[list[float]] = [[] for _ in range(QUINTILES)]
    for section in sections:
        scores, forwards = section["scores"], section["forwards"]
        total = len(scores)
        by_score = sorted(range(total), key=lambda i: scores[i])
        for position, index in enumerate(by_score):
            buckets[quintile_of(position, total)].append(forwards[index])
    return [sum(b) / len(b) if b else None for b in buckets]


def stability(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Walk-forward, adapted rather than copied.

    The paper walks forward to *train*: month T's model sees only [0, T-1].
    Every ranking here has zero parameters, so there is nothing to fit and
    nothing to leak -- every cross-section is already out of sample.

    What the discipline is still worth is the other half: **is the number
    stable, or is a pooled average hiding a few periods that carry it?** The
    nested validation contract section 6 admits this project runs one holdout
    rather than folds; a per-period series is the cheapest honest answer to
    that, and it costs nothing but reporting what was already computed.

    A mean IC of +0.07 from sixty-six cross-sections can be sixty-six small
    positives or four large ones and sixty-two zeros. The t statistic cannot
    tell those apart when the sections overlap, and these overlap heavily.
    """

    ics = [(s["session"], s["rank_ic"]) for s in sections if s["rank_ic"] is not None]
    if not ics:
        return {}

    by_year: dict[str, list[float]] = defaultdict(list)
    for session, ic in ics:
        by_year[session[:4]].append(ic)

    # Expanding mean, in order. Converging towards a level is what a real
    # effect looks like; drifting or jumping late is what one carried by a few
    # periods looks like.
    running: list[dict[str, Any]] = []
    total = 0.0
    for index, (session, ic) in enumerate(ics, start=1):
        total += ic
        running.append({"session": session, "expanding_mean_ic": total / index})

    positive = sum(1 for _, ic in ics if ic > 0)
    yearly = {
        year: {"cross_sections": len(v), "mean_ic": sum(v) / len(v)}
        for year, v in sorted(by_year.items())
    }
    return {
        "ic_hit_rate": positive / len(ics),
        "ic_by_year": yearly,
        "best_year": max(yearly, key=lambda y: yearly[y]["mean_ic"]),
        "worst_year": min(yearly, key=lambda y: yearly[y]["mean_ic"]),
        "expanding_mean_ic": running,
        "sign_stable_across_years": (
            all(v["mean_ic"] > 0 for v in yearly.values())
            or all(v["mean_ic"] < 0 for v in yearly.values())
        ),
    }


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
        "stability": stability(sections),
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

    # Diagnostic plan 005's two added reporting items.
    eligible = sum(s["eligible"] for s in sections)
    unscored = sum(s["unscored"] for s in sections)
    report["unscored_share_pct"] = unscored / eligible * 100 if eligible else None
    report["delisting"] = delisting_rate(sections, ends_delisted(args.dataset))

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
    share = report["unscored_share_pct"]
    print(f"  因 null 未計分  {share:.1f}%" if share is not None else "  因 null 未計分  n/a")
    d = report["delisting"]
    if d["top_n_delisted_share_pct"] is not None:
        print(
            f"  前 10 名裡後來下市的  {d['top_n_delisted_share_pct']:.2f}%"
            f"（{d['distinct_delisted_in_top_n']}/{d['distinct_names_in_top_n']} 檔不重複）"
        )

    st = report.get("stability") or {}
    if st:
        print(f"\n  IC 為正的截面比例  {st['ic_hit_rate']:.1%}")
        print(f"  各年份符號一致      {st['sign_stable_across_years']}")
        print("  逐年平均 IC:")
        for year, v in st["ic_by_year"].items():
            print(f"     {year}  {v['mean_ic']:+.4f}  （{v['cross_sections']} 個截面）")
        tail = st["expanding_mean_ic"][-1]["expanding_mean_ic"]
        head = st["expanding_mean_ic"][min(11, len(st["expanding_mean_ic"]) - 1)][
            "expanding_mean_ic"
        ]
        print(f"  擴張平均 IC：前 12 個截面 {head:+.4f} → 全部 {tail:+.4f}")

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
