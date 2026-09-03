"""Do the market's structural changes leave a step in the warehouse window?

Raised 2026-09-03. Taiwan's market rules changed twice inside the 2019-2026
window -- continuous trading replaced the call auction, and the intraday
odd-lot session opened, both in 2020 -- and every candidate result so far
pooled across both. If either change moved the data, those results should have
been read per regime and were not.

M4 contract section 1.2.1 already established the method for exactly this
question when it dated the price-limit rule: take sessions either side of the
change and see whether the behaviour steps. It also established why it
matters. A rule that was correct when written and carries no effective date
gets applied to years it does not govern, silently.

WHAT IS MEASURED, AND WHY IT IS THE MARKET-WIDE TABLE

`daily_prices_pit` does not carry `transactions`, but the TWSE `MI_INDEX`
response does -- table 6, 大盤統計資訊, one row per session with 成交金額,
成交股數 and 成交筆數 for 一般股票. Market-wide, so a session is one row
rather than a thousand, and already archived and hash-verified.

Three quantities come out of it:

    daily transactions        activity. Surges in a crash.
    mean shares per trade     **the one sensitive to the matching mechanism.**
                              Continuous trading fragments orders; a call
                              auction batches them.
    mean value per trade      the same thing in money

WHY A STEP AT THE CHANGE DATE IS NOT ENOUGH

Continuous trading arrived in March 2020, and so did the COVID crash. A metric
that jumps that month has two candidate causes and the date alone cannot
separate them -- the same confounding that made diagnostic 002's first answer
wrong, where a strategy's warmup ended two weeks before a crash and the number
that came out was about the crash.

So this measures two things instead:

1. **Is the step at the change month unusual?** Ranked against every other
   month-over-month step in the window, rather than judged against nothing.
2. **Is there a permanent level shift?** A mechanism change moves the level
   and leaves it moved. A crash spikes it and reverts.

The second is the one that decides, and only the second.

WHAT THIS CANNOT ANSWER

Whether intraday fills changed -- slippage, partial fills, queue position --
needs intraday data this project does not hold. And whether an odd lot was
**executable** intraday before the odd-lot session opened is a rules question
with an effective date, not a measurement. M0 already lists odd-lot fill
evidence as an unresolved blocker on a real canary; nothing here closes it.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_index_benchmarks import blob_for, number, observations  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-regime-continuity/1.0.0"

# 一般股票, the ordinary-share line of the market statistics board. The other
# lines are TDRs, ETFs and beneficiary certificates, which are out of M0 scope.
ORDINARY_SHARE_PREFIX = "1."

METRICS: dict[str, Callable[[float, float, float], float]] = {
    "daily_transactions": lambda amount, volume, count: count,
    "mean_shares_per_trade": lambda amount, volume, count: volume / count,
    "mean_value_per_trade": lambda amount, volume, count: amount / count,
}

# The metric that decides. The others are context.
MECHANISM_SENSITIVE = "mean_shares_per_trade"

# Dated from public knowledge of the rule changes and **not verified against a
# published effective date**, which is why every output naming them says
# `presumed`. The measurement does not depend on them being exactly right: a
# permanent level shift would be visible whichever month it started in, and
# the scan over every month finds the largest steps without being told where
# to look.
PRESUMED_CHANGES = {
    "2020-03": "continuous trading replaced the call auction (presumed)",
    "2020-10": "intraday odd-lot session opened (presumed)",
}


def market_statistics(archives: list[Path]) -> dict[str, tuple[float, float, float]]:
    """One row per session: 成交金額, 成交股數, 成交筆數 for ordinary shares."""

    out: dict[str, tuple[float, float, float]] = {}
    for archive in archives:
        if not archive.is_dir():
            raise SystemExit(f"not an archive root: {archive}")
        for _, record in observations(archive):
            period = str(record.get("logical_period") or "")
            if not period.startswith("session:"):
                continue
            try:
                document = json.loads(blob_for(archive, record).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            for table in document.get("tables") or []:
                if "大盤統計" not in str((table or {}).get("title") or ""):
                    continue
                for row in table.get("data") or []:
                    if not row or not str(row[0]).startswith(ORDINARY_SHARE_PREFIX):
                        continue
                    amount, volume, count = (
                        number(row[1]),
                        number(row[2]),
                        number(row[3]),
                    )
                    if amount and volume and count:
                        out[period[8:]] = (float(amount), float(volume), float(count))
    return out


def monthly(series, metric: Callable) -> dict[str, float]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for session, (amount, volume, count) in series.items():
        buckets[session[:7]].append(metric(amount, volume, count))
    return {month: st.median(values) for month, values in sorted(buckets.items())}


def steps(medians: dict[str, float]) -> dict[str, float]:
    months = sorted(medians)
    return {
        months[i]: abs(medians[months[i]] / medians[months[i - 1]] - 1)
        for i in range(1, len(months))
        if medians[months[i - 1]]
    }


def level_shift(medians: dict[str, float], change: str, window: int) -> dict[str, Any]:
    """Before and after the change, excluding the change month itself.

    The change month is left out on purpose: whatever else happened that month
    happened too, and including it would let a one-month spike stand in for a
    level.
    """

    months = sorted(medians)
    if change not in months:
        return {"available": False}
    at = months.index(change)
    before = [medians[m] for m in months[max(0, at - window) : at]]
    after = [medians[m] for m in months[at + 1 : at + 1 + window]]
    if not before or not after:
        return {"available": False}
    b, a = st.median(before), st.median(after)
    return {
        "available": True,
        "months_each_side": window,
        "before_median": b,
        "after_median": a,
        "shift_pct": (a / b - 1) * 100 if b else None,
    }


def build(archives: list[Path]) -> dict[str, Any]:
    series = market_statistics(archives)
    if not series:
        raise SystemExit(
            f"no market-statistics rows from {[str(a) for a in archives]}. An "
            f"empty series would report continuity for a window never read"
        )

    report: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "sessions": len(series),
        "first_session": min(series),
        "last_session": max(series),
        "presumed_changes": PRESUMED_CHANGES,
        "metrics": {},
    }

    for name, metric in METRICS.items():
        medians = monthly(series, metric)
        moves = steps(medians)
        ranked = sorted(moves.values(), reverse=True)
        entry: dict[str, Any] = {
            "months": len(medians),
            "median_monthly_step_pct": st.median(ranked) * 100 if ranked else None,
            "largest_steps": [
                {"month": m, "step_pct": moves[m] * 100}
                for m in sorted(moves, key=lambda k: -moves[k])[:5]
            ],
            "at_presumed_changes": {},
            "level_shift": {},
        }
        for change in PRESUMED_CHANGES:
            if change in moves:
                rank = ranked.index(moves[change]) + 1
                entry["at_presumed_changes"][change] = {
                    "step_pct": moves[change] * 100,
                    "rank_of": len(ranked),
                    "rank": rank,
                    "percentile": (1 - rank / len(ranked)) * 100,
                }
            entry["level_shift"][change] = level_shift(medians, change, window=12)
        report["metrics"][name] = entry

    decisive = report["metrics"][MECHANISM_SENSITIVE]
    report["verdict"] = {
        "decided_by": MECHANISM_SENSITIVE,
        "reason": (
            "A matching-mechanism change fragments or batches orders, which "
            "moves the mean size of a trade and leaves it moved. Activity "
            "metrics spike in a crash and revert, and March 2020 was both."
        ),
        "level_shift_pct": {
            change: (decisive["level_shift"][change] or {}).get("shift_pct")
            for change in PRESUMED_CHANGES
        },
        "median_monthly_step_pct": decisive["median_monthly_step_pct"],
    }
    report["reading_note"] = (
        "A level shift smaller than the median month-to-month step is not a "
        "step. This measures market-wide daily aggregates and can say nothing "
        "about intraday fills, and nothing at all about whether an odd lot "
        "was executable intraday before the odd-lot session opened -- that is "
        "a rules question with an effective date, and M0 already carries it "
        "as an unresolved blocker on a real canary."
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, action="append", required=True, dest="archives"
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    report = build(args.archives)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
