"""M6 Phase 3: drive the M5 ledger over the frozen research dataset.

This is the piece that was missing. M3 could say what was knowable, M4 could
price a trade and M5 could refuse an impossible one, but nothing walked a
calendar and made them argue with each other. Every earlier number in this
repository came from a table; this produces one from a simulated account.

How a session runs
------------------
1. settle whatever became cash today;
2. mark the book, so NAV and drawdown are measured before anything is decided;
3. exits before entries, because an exit frees the name and the money;
4. entries, sized by M0's risk policy, never by what is left in the account.

Signals are computed on the close of session S and submitted on S+1. A
strategy that decided and filled on the same bar would be trading on a price
it could not have known at decision time, which is the oldest error in
backtesting and the reason the whole warehouse exists.

Fills go through `Ledger.execute`, so the market conditions the dataset
recorded — tradability, price limits, liquidity — decide the outcome. Refusals
are collected rather than discarded: for a small account they are usually more
informative than the trades.

The strategy here is a deliberately plain breakout. It is a probe for the
pipeline, not a proposal: it exists so a failure can be attributed to the
plumbing rather than to a pattern detector nobody can hold in their head.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pyarrow as pa  # noqa: E402

from m4.rules import (  # noqa: E402
    BOARD_LOT,
    RULES_VERSION,
    BrokerTerms,
    Side,
    terms_cover,
    trade_costs,
)
from m5.ledger import (  # noqa: E402
    LEDGER_VERSION,
    Ledger,
    MarketConditions,
    OrderRequest,
    POLICY_INITIAL_CAPITAL,
    POLICY_MAX_POSITIONS,
    POLICY_PLANNED_RISK,
    TRADABLE_STATE,
    plan_position,
)

SCHEMA_ID = "tw-alpha-m6-ledger-backtest/1.0.0"

# As the dataset spells it. Compared case-insensitively at the call site, but
# named here so the value has one home rather than being retyped per branch.
TPEX_MARKET = "TPEX"
# Bumped with the columns, not with the code. 1.0.0 through 2026-08-26, then
# 1.2.0 when `rank_consistency_violations` was replaced by the scarcity and
# sizing pair -- a reader matching an old report against this schema would
# otherwise be told the columns are the ones it does not have.
CANDIDATE_REPORT_SCHEMA = "tw-alpha-m6-candidate-report/1.2.0"
CANDIDATE_REPORT_CONTRACT = "candidate-report-v1.2.0"

# The median stop distance measured across the SEPA trades in M6 Phase 0.
# Used only to turn the risk budget into a position size when deriving the
# reference scale; the real size follows each signal own stop.
MEDIAN_STOP_DISTANCE = Decimal("0.08")

# What fraction of a session's volume one account may assume it can take.
# M0 forbids assuming a fill; this is the assumption that replaces "always",
# and it is deliberately conservative for an account this size.
#
# The default, and the axis a sensitivity varies. Changing it asks "what if I
# could get less of each session" while the tradable universe stays exactly
# the same -- which is what makes it a sensitivity rather than a second
# strategy. `--universe` is the other thing, and it is not this.
PARTICIPATION_RATE = Decimal("0.01")

# The universe a candidate may enter. Not an assumption about fills: it decides
# which securities can be held at all, so two universes are two candidates.
#
# Owner decision 2026-08-27 (option 丙) separated these after `tpex-none` was
# found to change the held names outright -- the same strategy under two
# universes returned -37.76% and -3.57% at the reference scale, which is not a
# sensitivity band, it is two different books.
UNIVERSES = ("all", "no-tpex-odd-lot-entry")


def lot_legs(quantity: int) -> list[int]:
    """Split a holding into orders a broker would actually accept.

    A partial fill leaves a position that is neither whole board lots nor a
    pure odd lot — 2,000 shares ordered, 1,437 filled — and no single order can
    sell it. Taiwan settles that as two: the board lots in the regular session
    and the remainder in the odd-lot session.

    Found by this driver, where the missing split stranded positions
    permanently and quietly cut completed trades from 66 to 5.
    """

    if quantity <= 0:
        return []
    board = quantity - quantity % BOARD_LOT
    odd = quantity - board
    return [leg for leg in (board, odd) if leg > 0]


# Refusals that mean the account could not take the position, as opposed to
# this security not being tradable. Rank consistency is checked against these
# only: a name refused because it was halted says nothing about whether the
# ranking was followed.
#
# Split in two on 2026-08-26, because the two halves answer different
# questions and were cancelling each other out while pooled.
#
# Scarcity: the account is full, and `plan_position` reaches these branches
# before it reads the candidate's price at all. They fire identically for
# every security.
SCARCITY_REFUSALS = frozenset(
    {
        "entry:position-slots-full",
        "entry:max-positions-reached",
        "entry:cash-reserve-floor-reached",
    }
)

# Sizing: the account could not take *this* security at a size that satisfies
# every cap. Each of these branches reads the candidate's own price or stop,
# so a wide-stopped or expensive name fails where a cheaper one fits.
#
# `round-trip-cost-exceeds-planned-risk` was called capacity on 2026-08-25 for
# the reason that it moves with account size. True, and it also moves with the
# security, which is what puts it here.
SIZING_REFUSALS = frozenset(
    {
        "entry:cash-cannot-cover-position-and-charged-commission",
        "entry:breaches-hard-risk-cap",
        "entry:breaches-total-open-risk-cap",
        "entry:no-quantity-satisfies-every-cap",
        "entry:round-trip-cost-exceeds-planned-risk",
    }
)

CAPACITY_REFUSALS = SCARCITY_REFUSALS | SIZING_REFUSALS


def count_rank_violation(
    opened: list[float], refused: list[tuple[float, str]], codes: frozenset[str]
) -> str | None:
    """Did a refusal in `codes` outscore something opened the same session?

    Returns the offending code, or None. Compared at the extremes -- the best
    name turned away against the worst one taken -- because that is the pair
    that breaks first.

    Pulled out of the session loop so both answers can be exercised by a unit
    test. In the driver the scarcity branch cannot return a code: signals are
    walked in descending score order and `positions` only grows during the
    loop, so once the slots fill nothing opens after, and a scarcity refusal
    is never followed by a fill. Zero there is a guard on the sort, not a
    finding about the strategy.
    """

    if not opened or not refused:
        return None
    candidates = [(score, code) for score, code in refused if code in codes]
    if not candidates:
        return None
    best_score, best_code = max(candidates)
    return best_code if best_score > min(opened) else None


# 12-1 momentum: the return over the past twelve months excluding the most
# recent one. Jegadeesh & Titman (1993) and the momentum literature that
# followed it; the recent month is skipped because short-horizon returns
# reverse, and including it mixes two opposing effects.
#
# Chosen for one reason: it was settled decades ago, on other markets, by
# people who had never seen this dataset. Nothing about Taiwan 2019-2026 went
# into it, so it cannot have been fitted to the window it is about to be
# tested on. That is what makes it a prior rather than a result.
#
# Sessions rather than months, which is itself a conversion and therefore a
# choice: 252 sessions back to 21 sessions back, the conventional annual and
# monthly session counts.
MOMENTUM_LOOKBACK_SESSIONS = 252
MOMENTUM_SKIP_SESSIONS = 21


def momentum_12_1(
    closes: list[float], i: int, **_identity: str
) -> float | None:
    """Return from 252 sessions ago to 21 sessions ago. None if too short."""

    if i < MOMENTUM_LOOKBACK_SESSIONS:
        return None
    start = closes[i - MOMENTUM_LOOKBACK_SESSIONS]
    end = closes[i - MOMENTUM_SKIP_SESSIONS]
    if start <= 0:
        return None
    return end / start - 1


# Low volatility: rank by the inverse of trailing realised volatility, so the
# quietest name scores highest. Black (1972), Haugen & Heins (1975), and
# Frazzini & Pedersen (2014) on betting against beta -- decades old, other
# markets, and nothing about Taiwan 2019-2026 went into it.
#
# Chosen as the second candidate for two reasons beyond being a prior.
#
# It measures something 12-1 momentum does not. Momentum ranks by how much a
# price moved; this ranks by how steadily. Two candidates that rank on
# variants of past return would mostly be one candidate tested twice.
#
# It needs 60 sessions of warmup rather than 252. The first control comparison
# had a common window of 1,584 sessions at the reference scale and only 37 at
# the m0 scale, because the momentum candidate could not trade for its first
# year. A shorter warmup is not a better idea, but it does make the comparison
# cover more of the window, and the window is not something to spend lightly.
#
# What this is not: a claim that low volatility works on breakouts. The
# literature says low-volatility stocks have outperformed their risk; it says
# nothing about the subset that has just made a twenty-day high. Composing the
# two is this project's step, and the composite has to be judged on its own.
VOLATILITY_LOOKBACK_SESSIONS = 60


def realised_volatility(closes: list[float], i: int) -> float | None:
    """Standard deviation of daily returns over the last 60 sessions.

    None where the history is short or a price is non-positive: a value that
    cannot be computed must not quietly become zero.
    """

    if i < VOLATILITY_LOOKBACK_SESSIONS:
        return None
    window = closes[i - VOLATILITY_LOOKBACK_SESSIONS : i + 1]
    returns = []
    for previous, current in zip(window, window[1:]):
        if previous is None or current is None or previous <= 0:
            return None
        returns.append(current / previous - 1)
    if len(returns) < VOLATILITY_LOOKBACK_SESSIONS:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if variance <= 0:
        # A price that never moved for sixty sessions is not the calmest
        # security in the market, it is one that was not trading.
        return None
    return variance ** 0.5


def inverse_volatility_60(
    closes: list[float], i: int, **_identity: str
) -> float | None:
    """Negative realised volatility, so the quietest name scores highest.

    Negated so that higher scores sort first under the same descending rule
    every ranking uses, rather than each ranking carrying its own direction.
    """

    vol = realised_volatility(closes, i)
    return None if vol is None else -vol


# Stop distance: a constant, or a multiple of the security's own volatility.
#
# `fixed` is what every candidate through trial 12 used, and it was never
# argued for. It also has a consequence nobody chose: `plan_position` sizes by
# risk, so with a constant stop the position value is
#
#     quantity x price = (planned risk / stop distance) x NAV
#
# which is 9.375% of NAV for every security regardless of price. **Equal risk
# degenerates into equal weight, and the constant is why.**
#
# `volatility` removes the constant and the existing risk policy then produces
# volatility-scaled sizes on its own: a 4% stop takes 18.7% of NAV, a 16% stop
# takes 4.7%. No new weighting logic -- the mechanism was already there, held
# flat by a constant.
#
# Barroso & Santa-Clara (2015) and Daniel & Moskowitz (2016) on
# volatility-managed momentum; Baz et al. standardise MACD by 63-day
# volatility for the same reason.
STOP_RULES = ("fixed", "volatility", "trailing")

# Candidate plan 006. `fixed` and `volatility` both measure from the entry
# price, and M0 section 8.1 halts on drawdown from the NAV high water -- two
# reference points, with nothing bounding the distance between them. Diagnostic
# 002 measured that distance at 54.06%.
#
# `trailing` ratchets each position's stop up behind its own peak, so giveback
# from a peak is bounded by the stop distance rather than unbounded. The
# initial distance is the same as `fixed`; only the reference point moves.

# Two standard deviations, scaled from daily to the 21-session holding period.
# The square-root scaling is the standard conversion, not a choice. The
# multiplier of 2 is a choice, and the only free parameter this rule adds:
# taken because it is conventional, not because it tested better -- nothing
# was run before candidate plan 004 was committed.
STOP_VOL_MULTIPLIER = Decimal("2")
STOP_HORIZON_SESSIONS = 21

# Unclamped, and the clamp that was here first is the reason this comment
# exists. Candidate plan 004 specified a 4%-16% floor and ceiling "to prevent
# degeneracy" and justified them by saying both ends sat inside caps the
# contracts already impose -- which is the argument for not having them.
#
# Measured before running anything: on the development segment the median
# unclamped distance is 18.51%, so **59.3% of securities clamped at the 16%
# ceiling**. For most of the book the rule was a constant, just a different
# one from 8%, and momentum favours volatile names so the selected ten would
# have clamped almost entirely. The result would have measured halved gross
# exposure rather than volatility scaling.
#
# Removing both bounds takes the free parameters from two to zero, and the
# existing gates still catch the extremes -- checked rather than assumed, and
# the check corrected which gate does it:
#
#     stop 0.01%  ->  refused, round-trip-cost-exceeds-planned-risk
#     stop 1%     ->  33.40% of NAV, inside every cap
#     stop 6.27%  ->  11.96%   (P05 of the measured distribution)
#     stop 18.51% ->   4.04%   (median)
#     stop 41.19% ->   1.80%   (P95)
#
# The quiet end is caught by the **cost gate**, not the 45% weight cap as
# first written: a position whose entire risk budget is smaller than its round
# trip is refused for that reason, which is the right reason. Nothing at the
# loud end needs catching -- it just gets small.
def trail_stop(
    stop_price: Decimal, peak_high: Decimal, stop_pct: Decimal
) -> Decimal:
    """The stop a trailing rule allows, given the peak **through yesterday**.

    Ratchet only: it never lowers a stop. A trailing stop that could fall
    would let a position give back more than the distance it advertises, which
    is the property the whole rule exists for.

    The caller owns the promise that `peak_high` excludes today. Extracted here
    so the arithmetic is testable without a backtest; the ordering that keeps
    that promise is asserted separately, because it lives in the holding loop.
    """

    trailed = peak_high * (Decimal("1") - stop_pct)
    return trailed if trailed > stop_price else stop_price


def stop_distance(
    closes: list[float], i: int, rule: str, fixed_pct: Decimal
) -> Decimal | None:
    """How far below entry the stop sits, as a fraction of price."""

    if rule in ("fixed", "trailing"):
        # Same opening distance. `trailing` differs in what it measures from
        # afterwards, which is the holding loop's job, not this function's.
        return fixed_pct
    vol = realised_volatility(closes, i)
    if vol is None:
        return None
    return STOP_VOL_MULTIPLIER * Decimal(str(vol)) * Decimal(
        str(STOP_HORIZON_SESSIONS)
    ).sqrt()



# The control M0 section 9.1 has required from the start -- "equal-size
# same-pool random selection" -- and which nothing implemented until
# 2026-09-01. Its absence is why candidate 003's +163.20% cannot be
# attributed: the window holds 2020-2021, and momentum's Rank IC over the
# same data is -0.0080 (t = -0.56). Without this, "the ranking helped" and
# "any ten names would have" are the same number.
#
# Pre-registered in docs/evidence/m7-control-plan-001-random-selection-2026-09-01.md
# before a line of this was written.
#
# Scored on identity, never on price. A hash of (seed, market, symbol,
# session) is reproducible by anyone holding the seed, which the plan fixes in
# advance. The alternative -- drawing from `random.Random(seed)` in iteration
# order -- reproduces only while that order holds, and iteration order is a
# property of the dataset file rather than of anything declared. **A control
# only its author can reproduce is not a control.**
CONTROL_SEEDS = (
    1, 2, 3, 5, 8, 13, 21, 34, 55, 89,
    144, 233, 377, 610, 987, 1597, 2584, 4181, 6765, 10946,
)


def _random_seeded(seed: int):
    """A ranking that knows nothing about the market."""

    def score(
        closes: list[float],
        i: int,
        *,
        market: str = "",
        symbol: str = "",
        session: str = "",
    ) -> float:
        digest = hashlib.sha256(
            f"{seed}:{market}:{symbol}:{session}".encode()
        ).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    return score


RANKINGS: dict[str, Any] = {
    "": None,
    "momentum-12-1": momentum_12_1,
    "inverse-volatility-60": inverse_volatility_60,
    # Twenty, because one draw is a sample and the question is whether a
    # candidate's return sits inside the distribution or outside it.
    **{f"random-seed-{s}": _random_seeded(s) for s in CONTROL_SEEDS},
}


@dataclass(frozen=True)
class Signal:
    market: str
    symbol: str
    stop_price: Decimal
    score: float | None = None


@dataclass
class OpenPosition:
    market: str
    symbol: str
    entry_session: str
    entry_price: Decimal
    stop_price: Decimal
    quantity: int
    # The highest session high seen **through the previous session**, which is
    # what a trailing stop may use today. Updated after today's stop check, so
    # today's high can only move tomorrow's stop.
    #
    # Starts at the entry price rather than the entry session's high: on the
    # day of entry the high is not yet known when the position opens, and
    # using it would let a stop be set from a price that had not happened.
    peak_high: Decimal = Decimal("0")


def load_dataset(root: Path) -> tuple[list[str], dict[str, dict[tuple[str, str], dict]]]:
    table = pq.read_table(root / "research_dataset.parquet")
    by_session: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
    for row in table.to_pylist():
        by_session[row["session_date"]][(row["market"], row["symbol"])] = row
    return sorted(by_session), by_session


def breakout_signals(
    history: dict[tuple[str, str], list[dict]],
    session: str,
    *,
    lookback: int,
    stop_pct: Decimal,
    ranking: Any = None,
    stop_rule: str = "fixed",
) -> list[Signal]:
    """Close above the highest close of the previous `lookback` sessions.

    Two deliberate properties. It needs only `lookback` sessions of warmup, so
    it can use most of a window that a 52-week rule cannot; and it has one
    parameter, so a result cannot be the product of a search.
    """

    signals: list[Signal] = []
    for key, bars in history.items():
        if len(bars) <= lookback:
            continue
        today = bars[-1]
        if today["session_date"] != session or today["close"] is None:
            continue
        window = [b["close"] for b in bars[-(lookback + 1):-1] if b["close"] is not None]
        if len(window) < lookback:
            continue
        close = Decimal(str(today["close"]))
        if close <= Decimal(str(max(window))):
            continue
        closes_all = [b["close"] for b in bars]
        if any(c is None for c in closes_all):
            continue
        distance = stop_distance(closes_all, len(bars) - 1, stop_rule, stop_pct)
        if distance is None:
            continue
        score = None
        if ranking is not None:
            closes = [b["close"] for b in bars]
            if any(c is None for c in closes):
                # A gap in the history makes the score unreadable, and a
                # missing score must not quietly sort as zero.
                continue
            score = ranking(
                closes, len(bars) - 1,
                market=key[0], symbol=key[1], session=session,
            )
            if score is None:
                continue
        signals.append(
            Signal(
                key[0],
                key[1],
                stop_price=close * (Decimal("1") - distance),
                score=score,
            )
        )
    # Highest score first. Without a ranking the order is whatever the history
    # dict yielded, which is the arrival order the amended decision 4 is about.
    if ranking is not None:
        signals.sort(key=lambda s: s.score, reverse=True)
    return signals


# Rebalance cadence for the rank-only entry, in sessions. 21 is the
# conventional monthly session count, the same conversion the 12-1 momentum
# lookback already makes. Not searched over: one cadence, declared here.
REBALANCE_SESSIONS = 21

ENTRY_RULES = ("breakout", "rank-only")


def rank_only_signals(
    history: dict[tuple[str, str], list[dict]],
    session: str,
    *,
    stop_pct: Decimal,
    ranking: Any,
    stop_rule: str = "fixed",
) -> list[Signal]:
    """Every scoreable security, ranked. No entry condition at all.

    This is the original shape of the momentum literature: rank by the score,
    hold the top N, rebalance on a cadence. What this project had been running
    was "break out, *then* rank by the score", which is a composite it built
    itself.

    The composite is why "does the ranking help" could not be answered. The
    ranking only ever reordered signals that had already passed a breakout
    filter, and M6.2 measured that filter turning over 8.72 names a session.
    Remove the filter and the ranking is measurable on its own.

    Requires a ranking. Without one this would be "hold an arbitrary ten
    securities", which is not a candidate, and returning an empty list would
    let that read as a strategy that found nothing.
    """

    if ranking is None:
        raise ValueError(
            "rank-only entry needs a ranking function; without one it holds an "
            "arbitrary ten securities and reports that as a result"
        )

    signals: list[Signal] = []
    for key, bars in history.items():
        today = bars[-1]
        if today["session_date"] != session or today["close"] is None:
            continue
        closes = [b["close"] for b in bars]
        if any(c is None for c in closes):
            continue
        score = ranking(
            closes, len(bars) - 1,
            market=key[0], symbol=key[1], session=session,
        )
        if score is None:
            continue
        distance = stop_distance(closes, len(bars) - 1, stop_rule, stop_pct)
        if distance is None:
            # No stop means no size, and sizing a position without one would
            # be the only place in this driver where risk is not quantified.
            continue
        close = Decimal(str(today["close"]))
        signals.append(
            Signal(
                market=key[0],
                symbol=key[1],
                stop_price=close * (Decimal("1") - distance),
                score=score,
            )
        )
    signals.sort(key=lambda s: s.score, reverse=True)
    return signals


# M0 section 8's cost table: "壓力測試 | 可變成本及滑價的 1.5、2、3 倍",
# and "所有候選必須在相同成本模型下比較並通過至少 2 倍成本壓力後，才可由
# `research` 申請進入 `validated`". Nothing implemented it, so no candidate
# could have applied even if one had passed its own thresholds.
# The ledger's own default, restated here so the multiplier has something to
# multiply. Asserted against `Ledger.__init__` by a test rather than trusted:
# a drift between the two would silently change the baseline every stressed
# run is measured against.
LEDGER_BASELINE_SLIPPAGE = Decimal("0.0020")

COST_STRESS_MULTIPLIERS = (Decimal("1"), Decimal("1.5"), Decimal("2"), Decimal("3"))


def stressed_costs(multiplier: Decimal) -> tuple[BrokerTerms, Decimal]:
    """Multiply the rate-based costs, and only those.

    **The minimum commission is deliberately not multiplied, and the sell tax
    is not either.** M0 says "可變成本及滑價" -- variable costs and slippage.
    The 20 TWD floor is not variable, and the 0.3% transaction tax is statute
    rather than an assumption this project could be wrong about.

    That choice matters more than it looks at the M0 scale, where the floor
    is most of the cost: a stress test that leaves it alone is not stressing
    the dominant term. It is stated here rather than buried so that someone
    who disagrees can disagree with a specific decision. The reported
    `minimum_commission_share_pct` says how much of the cost the untouched
    floor accounted for, so the limit of the test is visible in its output.

    `m4/rules.py` and `m5/ledger.py` are byte-identical mirrors of Taiwan Core
    and are not edited: both the terms and the slippage rate are constructor
    arguments, so the stress is applied from outside.
    """

    if multiplier <= 0:
        raise SystemExit("cost multiplier must be positive")
    base = BrokerTerms()
    return (
        replace(base, commission_rate=base.commission_rate * multiplier),
        LEDGER_BASELINE_SLIPPAGE * multiplier,
    )


def run(
    dataset_root: Path,
    *,
    opening_cash: Decimal,
    lookback: int,
    stop_pct: Decimal,
    max_holding_sessions: int,
    ranking_name: str = "",
    universe: str = "all",
    participation_rate: Decimal = PARTICIPATION_RATE,
    first_trading_session: str | None = None,
    entry_rule: str = "breakout",
    stop_rule: str = "fixed",
    max_positions: int | None = None,
    cost_multiplier: Decimal = Decimal("1"),
) -> dict[str, Any]:
    sessions, by_session = load_dataset(dataset_root)
    terms, slippage = stressed_costs(cost_multiplier)
    ledger = Ledger(
        opening_cash=opening_cash,
        sessions=[date.fromisoformat(s) for s in sessions],
        terms=terms,
        slippage_rate=slippage,
    )

    history: dict[tuple[str, str], list[dict]] = defaultdict(list)
    positions: dict[tuple[str, str], OpenPosition] = {}
    pending: list[Signal] = []
    trades: list[dict[str, Any]] = []
    refusals: dict[str, int] = defaultdict(int)
    ranking = RANKINGS[ranking_name]

    # Candidate plan 006 section 2.2. `POLICY_MAX_POSITIONS` lives in
    # `m5/ledger.py`, a byte-identical mirror of Taiwan Core, so it cannot be
    # edited here -- and should not be: M0 section 8 sets 10 as a ceiling, not
    # a target, so holding fewer is already compliant.
    #
    # `min` and not the requested value: a candidate able to ask for more than
    # policy allows would be a way around the cap rather than a choice inside
    # it. A test asserts this cannot be loosened.
    slots = (
        POLICY_MAX_POSITIONS
        if max_positions is None
        else min(max_positions, POLICY_MAX_POSITIONS)
    )
    # Deep enough for whichever needs more history, the entry rule or the
    # ranking. Trimming to the breakout lookback alone left 22 bars, and a
    # 252-session momentum read against 22 bars scores nothing at all.
    history_depth = lookback + 2
    if ranking_name == "momentum-12-1":
        history_depth = max(history_depth, MOMENTUM_LOOKBACK_SESSIONS + 2)
    elif ranking_name == "inverse-volatility-60":
        history_depth = max(history_depth, VOLATILITY_LOOKBACK_SESSIONS + 2)
    # Sessions where a candidate refused for capacity outscored one that was
    # opened. Zero is the claim that fills followed the ranking.
    # What the odd-lot liquidity mode actually did. Counted because the first
    # version compared against "TPEx" while the dataset says "TPEX", so the
    # mode ran over 1,840 sessions and changed nothing -- and reported the same
    # figures as the default, which read as "the assumption does not matter".
    suppressed: dict[str, int] = defaultdict(int)
    scarcity_violations = 0
    sizing_violations = 0
    violation_codes: dict[str, int] = defaultdict(int)
    equity: list[dict[str, Any]] = []
    order_seq = 0

    for index, session in enumerate(sessions):
        rows = by_session[session]
        as_date = date.fromisoformat(session)
        ledger.settle_through(as_date)

        marks = {
            key[1]: Decimal(str(row["close"]))
            for key, row in rows.items()
            if row["close"] is not None
        }
        held = {p.symbol for p in positions.values()}
        if held - set(marks):
            # A held security with no close today is marked at its last one;
            # the ledger refuses to value what it cannot price, and carrying
            # the previous mark is the conservative reading of a halt.
            for key, position in positions.items():
                if position.symbol not in marks:
                    marks[position.symbol] = position.entry_price
        equity.append({"session": session, "nav": float(ledger.mark_session(as_date, marks))})

        def conditions(
            key: tuple[str, str],
            quantity: int | None = None,
            *,
            entering: bool = False,
        ) -> MarketConditions | None:
            row = rows.get(key)
            if row is None:
                return None
            volume = row.get("volume")
            available = int(Decimal(str(volume)) * participation_rate) if volume else 0
            if (
                universe == "no-tpex-odd-lot-entry"
                and entering
                and key[0].upper() == TPEX_MARKET
                and quantity is not None
                and quantity < BOARD_LOT
            ):
                # TPEx publishes board-lot volume only. Letting an odd lot take
                # a share of it borrows liquidity from a session it was not in.
                # This mode refuses instead, which is the other end of the range
                # rather than a better answer -- see Owner decision D17.
                #
                # Entries only, and that word is the whole correction. Applied
                # to exits as well, the mode stranded positions: a board lot
                # bought on TPEx partially fills, the remainder is an odd lot,
                # and the odd lot can never be sold. The unranked probe filled
                # all ten slots by March 2019 and never traded again -- eight
                # completed trades, ten open at the end, 15,019
                # `exit:no-liquidity-no-fill` refusals, and a reported +38.53%
                # that was mark-to-market on stock it could not sell.
                #
                # An account that cannot get out is not a conservative model of
                # a thin market, it is a state no market produces.
                available = 0
                suppressed["tpex-odd-lot-entries-refused"] += 1
            return MarketConditions(
                session=as_date,
                session_is_open=row["session_state"] == "official-open",
                tradability_state=row["tradability_state"],
                limit_up=Decimal(str(row["limit_up"])) if row["limit_up"] is not None else None,
                limit_down=Decimal(str(row["limit_down"])) if row["limit_down"] is not None else None,
                available_quantity=available,
            )

        # What yesterday's close ranked, arriving today. For the rank-only
        # rule `pending` is non-empty only on the session after a rebalance,
        # so its presence *is* the rebalance flag -- no second calendar to
        # drift out of step with the first.
        is_rebalance = entry_rule == "rank-only" and bool(pending)
        target_set = {(s.market, s.symbol) for s in pending}

        # --- exits first -------------------------------------------------
        for key in list(positions):
            position = positions[key]
            row = rows.get(key)
            if row is None or row["close"] is None:
                continue
            close = Decimal(str(row["close"]))
            low = Decimal(str(row["low"])) if row["low"] is not None else close
            high = Decimal(str(row["high"])) if row["high"] is not None else close
            age = index - sessions.index(position.entry_session)

            # Candidate plan 006 section 2.1. The ratchet uses `peak_high`,
            # which holds highs **through the previous session** -- today's is
            # folded in below, after the stop has been checked.
            #
            # Raising the stop from today's high and then testing today's low
            # would decide where the stop sat using a price not yet known when
            # the session opened. That is intra-session look-ahead, and it
            # makes results better, which is what makes it dangerous.
            if stop_rule == "trailing":
                position.stop_price = trail_stop(
                    position.stop_price, position.peak_high, stop_pct
                )

            reason = None
            if low <= position.stop_price:
                # Conservative: when a session touches both the stop and a
                # profitable level, the stop is assumed to come first. Daily
                # bars cannot say which did, and this errs against the account.
                reason, price = "stop", position.stop_price
            elif entry_rule == "rank-only":
                # Held until it leaves the top N on a rebalance, not until it
                # gets old. A holding period is a parameter; membership of the
                # top N is the strategy restating itself.
                if is_rebalance and key not in target_set:
                    reason, price = "left-the-top-n", close
            elif age >= max_holding_sessions:
                reason, price = "max-holding", close
            if reason is None:
                # Survived. Today's high may move the stop from tomorrow.
                if high > position.peak_high:
                    position.peak_high = high
                continue
            legs = lot_legs(position.quantity)
            for leg in legs:
                market = conditions(key, leg)
                if market is None:
                    continue
                order_seq += 1
                result = ledger.execute(
                    OrderRequest(
                        order_id=f"x{order_seq}",
                        fill_id=f"x{order_seq}",
                        session=as_date,
                        symbol=position.symbol,
                        side=Side.SELL,
                        quantity=leg,
                        limit_price=price,
                    ),
                    market,
                )
                if result.state in ("filled", "partially-filled"):
                    trades.append(
                        {
                            "market": position.market,
                            "symbol": position.symbol,
                            "entry_session": position.entry_session,
                            "exit_session": session,
                            "entry_price": float(position.entry_price),
                            "exit_price": float(result.fill_price or price),
                            "quantity": result.filled_quantity,
                            "exit_reason": reason,
                        }
                    )
                    position.quantity -= result.filled_quantity
                else:
                    refusals[f"exit:{result.reason}"] += 1
            if position.quantity <= 0:
                del positions[key]

        # --- entries, from yesterday's signals ----------------------------
        opened_scores: list[float] = []
        capacity_refused_scores: list[tuple[float, str]] = []

        def note_refusal(code: str, signal: Signal) -> None:
            refusals[code] += 1
            if signal.score is not None and code in CAPACITY_REFUSALS:
                capacity_refused_scores.append((signal.score, code))

        # The sealed segment is evaluated on the full dataset with this set to
        # its first session: a 252-session momentum score for 2025-01-02 reads
        # 2024 prices, which were known on the day, so warming up on them is
        # not a look-ahead. Nested validation contract section 1.
        #
        # Entries only. An open position still has to be allowed to exit, and
        # there are none before the first trading session anyway.
        if first_trading_session is not None and session < first_trading_session:
            pending = []
        for signal in pending:
            key = (signal.market, signal.symbol)
            if key in positions:
                # Not scarcity: we already hold it, and holding the better
                # name is the ranking being obeyed, not overruled. Filed
                # under slots-full until 2026-08-26, where it manufactured
                # rank violations out of the account's own best position.
                note_refusal("entry:already-held", signal)
                continue
            if len(positions) >= slots:
                note_refusal("entry:position-slots-full", signal)
                continue
            row = rows.get(key)
            if row is None or row.get("open") is None:
                note_refusal("entry:no-opening-price", signal)
                continue
            entry = Decimal(str(row["open"]))
            if entry <= signal.stop_price:
                # The gap opened below the stop the signal was sized against.
                note_refusal("entry:opened-below-stop", signal)
                continue
            # M0 section 8 caps *total* open risk at 2.00% of NAV, not just
            # the risk of each position taken alone. `plan_position` enforces
            # it, but only against the figure it is handed, and this driver
            # was handing it nothing -- so the cap defaulted to zero prior
            # risk and never once refused a trade.
            #
            # With two slots the omission could not bite: two positions at the
            # 0.75% target come to 1.5%, inside the cap. It only becomes
            # visible when the slot count rises, which is exactly the question
            # that was being asked of this driver.
            nav_now = ledger.nav(marks)
            open_risk = sum(
                (
                    (held.entry_price - held.stop_price) * Decimal(held.quantity)
                    for held in positions.values()
                ),
                Decimal("0"),
            ) / nav_now
            plan = plan_position(
                nav=nav_now,
                price=entry,
                stop_price=signal.stop_price,
                open_positions=len(positions),
                open_risk=open_risk,
                settled_cash=ledger.buying_power,
            )
            if not plan.is_trade:
                note_refusal(f"entry:{plan.reason}", signal)
                continue
            order_seq += 1
            market = conditions(key, plan.quantity, entering=True)
            if market is None:
                note_refusal("entry:no-market-conditions", signal)
                continue
            result = ledger.execute(
                OrderRequest(
                    order_id=f"e{order_seq}",
                    fill_id=f"e{order_seq}",
                    session=as_date,
                    symbol=signal.symbol,
                    side=Side.BUY,
                    quantity=plan.quantity,
                    limit_price=entry,
                ),
                market,
            )
            if result.state in ("filled", "partially-filled"):
                positions[key] = OpenPosition(
                    market=signal.market,
                    symbol=signal.symbol,
                    entry_session=session,
                    entry_price=result.fill_price or entry,
                    stop_price=signal.stop_price,
                    quantity=result.filled_quantity,
                    # Not the entry session's high: that price had not
                    # happened when the position opened.
                    peak_high=result.fill_price or entry,
                )
                if signal.score is not None:
                    opened_scores.append(signal.score)
            else:
                note_refusal(f"entry:{result.reason}", signal)

        # Two questions, counted apart. Scarcity: was a name turned away for
        # want of room while a worse one was taken? Sizing: was the top name
        # unable to fit? Only the first is the selection logic failing.
        scarce = count_rank_violation(
            opened_scores, capacity_refused_scores, SCARCITY_REFUSALS
        )
        if scarce is not None:
            scarcity_violations += 1
            violation_codes[scarce] += 1
        sized = count_rank_violation(
            opened_scores, capacity_refused_scores, SIZING_REFUSALS
        )
        if sized is not None:
            sizing_violations += 1
            violation_codes[sized] += 1

        # --- today's signals fill tomorrow --------------------------------
        for key, row in rows.items():
            if row["close"] is not None:
                history[key].append(row)
                if len(history[key]) > history_depth:
                    history[key].pop(0)
        if entry_rule == "rank-only":
            # Only on a rebalance session, and only the top N. Every other
            # session the book is left alone, which is the whole point: the
            # breakout rule reshuffled it daily.
            if (index + 1) % REBALANCE_SESSIONS == 0:
                ranked = rank_only_signals(
                    history,
                    session,
                    stop_pct=stop_pct,
                    ranking=ranking,
                    stop_rule=stop_rule,
                )
                pending = [
                    s
                    for s in ranked
                    if rows[(s.market, s.symbol)]["tradability_state"]
                    == TRADABLE_STATE
                ][:slots]
            else:
                pending = []
        else:
            pending = [
                s
                for s in breakout_signals(
                    history,
                    session,
                    lookback=lookback,
                    stop_pct=stop_pct,
                    ranking=ranking,
                    stop_rule=stop_rule,
                )
                if rows[(s.market, s.symbol)]["tradability_state"] == TRADABLE_STATE
            ]

    final_nav = float(ledger.nav(marks)) if equity else float(opening_cash)
    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(dataset_root),
        "dataset_sha256": json.loads(
            (dataset_root / "dataset_manifest.json").read_bytes()
        )["sha256"],
        "strategy": {
            "name": (
                "close-above-n-session-high"
                if entry_rule == "breakout"
                else "hold-top-n-by-score"
            ),
            "entry_rule": entry_rule,
            "stop_rule": stop_rule,
            "rebalance_sessions": (
                REBALANCE_SESSIONS if entry_rule == "rank-only" else None
            ),
            # True of the unranked form, and it stayed in the manifest after a
            # ranking made it a candidate. Derived now instead of asserted.
            "note": (
                "a candidate ranked by " + ranking_name
                if ranking_name
                else "a pipeline probe, not a proposal"
            ),
            "lookback": lookback,
            "stop_pct": float(stop_pct),
            "max_holding_sessions": max_holding_sessions,
            # Empty means no ranking, and that is an honest answer rather than
            # a missing field: the entry loop then walks `pending` in whatever
            # order the signals were generated, so which names it holds is
            # decided by arrival order. ADR-0002 decision 4, as amended on
            # 2026-08-26, marks such a run `selection-logic-not-measured`.
            "ranking_function": ranking_name,
            # What applied, not what was requested. A run that asked for 12
            # and got 10 must not read as a 12-slot run.
            "max_positions": slots,
        },
        "rank_violations_scarcity": scarcity_violations if ranking_name else -1,
        "rank_violations_sizing": sizing_violations if ranking_name else -1,
        "rank_violation_codes": dict(
            sorted(violation_codes.items(), key=lambda kv: -kv[1])
        ),
        "assumptions": {
            "participation_rate": float(PARTICIPATION_RATE),
            "signal_on_close_fill_next_open": True,
            # M0 section 8. A run at 1 is the baseline; 2 is the multiple a
            # candidate has to survive before it may apply for `validated`.
            "cost_multiplier": float(cost_multiplier),
            "commission_rate": float(terms.commission_rate),
            "slippage_rate": float(slippage),
            # Not multiplied, and named so the omission is visible rather than
            # discovered. See `stressed_costs`.
            "minimum_commission_not_stressed": float(terms.minimum_commission),
            "sell_tax_rate_not_stressed": float(terms.sell_tax_rate),
            "participation_rate": float(participation_rate),
            "universe": universe,
            "first_trading_session": first_trading_session,
            "universe_effect": dict(suppressed),
            "stop_assumed_to_precede_target_within_a_session": True,
        },
        "opening_cash": float(opening_cash),
        "final_nav": final_nav,
        "return_pct": (final_nav / float(opening_cash) - 1) * 100,
        "sessions": len(sessions),
        # The window these figures were priced over. Needed to say whether the
        # broker terms used were in force for it -- a count of sessions cannot.
        "first_session": sessions[0],
        "last_session": sessions[-1],
        "completed_trades": len(trades),
        "open_at_end": len(positions),
        "high_water_mark": float(ledger.high_water_mark),
        "drawdown_pct": float(ledger.drawdown) * 100,
        "realised_pnl": float(ledger.realised_pnl),
        "journal_entries": len(ledger.journal),
        "refusals": dict(sorted(refusals.items(), key=lambda kv: -kv[1])),
        "trades": trades,
        "equity": equity,
    }
    return manifest


def reference_scale_nav() -> Decimal:
    """The NAV whose positions clear the minimum commission.

    ADR-0002 decision 2 forbids writing this down: the reference scale is the
    smallest position at which the minimum commission stops binding, and that
    is a function of the broker terms in force. Derived here by asking
    `trade_costs`, so it moves when the terms move instead of becoming a
    constant that quietly describes last year's schedule.

    Position size follows M0 section 8: the planned risk over the median stop
    distance measured in M6 Phase 0.
    """

    terms = BrokerTerms()
    low, high = 1, 5_000_000
    while low < high:
        mid = (low + high) // 2
        if trade_costs(
            side=Side.BUY, price=Decimal(1), quantity=mid, terms=terms
        ).minimum_commission_applied:
            low = mid + 1
        else:
            high = mid
    position_share = POLICY_PLANNED_RISK / MEDIAN_STOP_DISTANCE
    return (Decimal(low) / position_share).quantize(Decimal("1"))


def realised_costs(result: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """Commission and tax actually charged, and the turnover they were charged on.

    Recomputed from the fills rather than carried, so a report cannot claim a
    cost the rules module would not produce for the same trades.
    """

    terms = BrokerTerms()
    cost = Decimal("0")
    turnover = Decimal("0")
    for trade in result["trades"]:
        quantity = int(trade["quantity"])
        for side, price in (
            (Side.BUY, trade["entry_price"]),
            (Side.SELL, trade["exit_price"]),
        ):
            leg = trade_costs(
                side=side, price=Decimal(str(price)), quantity=quantity, terms=terms
            )
            cost += leg.total_cost
            turnover += leg.gross
    return cost, turnover


def candidate_report(results: dict[str, dict[str, Any]]) -> tuple[list[dict], dict]:
    """One row per scale, plus the manifest, per the candidate report contract.

    Both scales are required. A report carrying one is not a simpler report,
    it is a report missing a field: ADR-0002 decision 3 asks for the gap
    between them, and a gap needs two numbers.
    """

    rows: list[dict[str, Any]] = []
    for scale, result in sorted(results.items()):
        cost, turnover = realised_costs(result)
        refusals = {k: int(v) for k, v in result["refusals"].items()}
        total = sum(refusals.values())
        trades = int(result["completed_trades"])
        ranking = str(result["strategy"].get("ranking_function") or "")
        # Not applicable without a ranking, and -1 says so rather than 0,
        # which would read as "checked, none found".
        scarcity = int(result.get("rank_violations_scarcity", -1)) if ranking else -1
        sizing = int(result.get("rank_violations_sizing", -1)) if ranking else -1
        rows.append(
            {
                "scale": scale,
                "opening_cash": float(result["opening_cash"]),
                "return_pct": float(result["return_pct"]),
                "drawdown_pct": float(result["drawdown_pct"]),
                "completed_trades": trades,
                "cost_total": float(cost),
                "cost_share_of_capital": float(cost) / float(result["opening_cash"]),
                "cost_share_of_turnover": (
                    float(cost / turnover) if turnover else 0.0
                ),
                "refusals_total": total,
                # Contract v1.1.0 section 3. The verdict is about whether
                # selection followed a ranking, not about how many candidates
                # were turned away: a screen over two thousand securities
                # refuses six figures of signals however good its ranking is.
                #
                # Counting was tried twice and was wrong twice. Watching only
                # `position-slots-full` reported success when raising the slot
                # cap merely moved refusals into other codes; watching the
                # total fixed that and still failed every broad-signal
                # candidate on arithmetic that says nothing about its ranking.
                "ranking_function": ranking,
                # Contract v1.2.0 splits what v1.1.0 pooled. Sizing violations
                # were outvoting the scarcity ones and taking the verdict with
                # them, while saying nothing about the selection logic.
                "rank_violations_scarcity": scarcity,
                "rank_violations_sizing": sizing,
                # Which code outscored an opened position, so a non-zero
                # count can be read rather than only counted.
                "rank_violation_codes_json": json.dumps(
                    result.get("rank_violation_codes", {}) if ranking else {},
                    ensure_ascii=False,
                ),
                "selection_logic_measured": bool(ranking) and scarcity == 0,
                "refusals_json": json.dumps(
                    dict(sorted(refusals.items())), ensure_ascii=False
                ),
            }
        )

    sample = next(iter(results.values()))
    terms = BrokerTerms()
    window_start = date.fromisoformat(sample["first_session"])
    window_end = date.fromisoformat(sample["last_session"])

    # The warehouse id lives in the dataset's own manifest, not in the run.
    # Read rather than defaulted: an empty lineage field is indistinguishable
    # from a report built against a warehouse nobody can name, and the
    # contract test caught exactly that when this defaulted to "".
    dataset_manifest_path = Path(sample["dataset_root"]) / "dataset_manifest.json"
    dataset_manifest = json.loads(dataset_manifest_path.read_bytes())
    warehouse_id = dataset_manifest.get("warehouse_dataset_id")
    if not warehouse_id:
        raise SystemExit(
            f"{dataset_manifest_path} carries no warehouse_dataset_id; refusing "
            "to emit a report whose lineage cannot be resolved"
        )

    manifest = {
        "schema_id": CANDIDATE_REPORT_SCHEMA,
        "contract_version": CANDIDATE_REPORT_CONTRACT,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "scales": sorted(results),
        "dataset_sha256": sample["dataset_sha256"],
        "dataset_root": str(sample["dataset_root"]),
        "warehouse_dataset_id": warehouse_id,
        "warehouse_roots": dataset_manifest.get("warehouse_roots", {}),
        "strategy_version": sample["strategy"],
        "rules_version": RULES_VERSION,
        "ledger_version": LEDGER_VERSION,
        "broker_terms": {
            "commission_rate": str(terms.commission_rate),
            "minimum_commission": str(terms.minimum_commission),
            "sell_tax_rate": str(terms.sell_tax_rate),
            "evidence_state": terms.evidence_state,
            "has_rebate": terms.has_rebate,
            "source": terms.source,
            # Whether these terms were in force for the window they priced.
            # Undated for the research defaults, which belong to no broker and
            # therefore to no date range. It matters for a real schedule: the
            # The 2026 promotion runs for that year and the dataset starts in 2019,
            # so pricing the whole window on it is a claim about a period the
            # terms did not govern -- fair to ask, not fair to leave unsaid.
            "effective_from": (
                str(terms.effective_from) if terms.effective_from else None
            ),
            "effective_through": (
                str(terms.effective_through) if terms.effective_through else None
            ),
            "covers_priced_window": terms_cover(terms, window_start, window_end),
        },
        "assumptions": sample["assumptions"],
        "reading_note": (
            "ADR-0002 decision 1: figures produced at the m0-execution scale "
            "are not evidence about a strategy. Decision 4: a row whose "
            "selection_logic_measured is false may not be used to rank "
            "candidates against one another."
        ),
    }
    return rows, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--report-root",
        type=Path,
        help=(
            "emit a candidate report per docs/contracts/candidate-report-contract.md. "
            "Runs both scales, because the contract requires both"
        ),
    )
    parser.add_argument("--opening-cash", type=Decimal, default=Decimal("10000"))
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument(
        "--max-positions",
        type=int,
        default=None,
        help=(
            "hold at most this many names. Clamped to M0 section 8's cap, so "
            "it can only tighten. Omit for the policy maximum"
        ),
    )
    parser.add_argument("--stop-pct", type=Decimal, default=Decimal("0.08"))
    parser.add_argument("--max-holding-sessions", type=int, default=20)
    parser.add_argument(
        "--stop-rule",
        choices=STOP_RULES,
        default="fixed",
        help=(
            "`fixed` is the constant every candidate through trial 13 used. "
            "It also makes equal-risk sizing degenerate into equal weight, "
            "because position value is (planned risk / stop distance) x NAV. "
            "`volatility` removes the constant and the existing risk policy "
            "then scales size by volatility on its own"
        ),
    )
    parser.add_argument(
        "--entry",
        choices=ENTRY_RULES,
        default="breakout",
        help=(
            "`breakout` is the probe every candidate so far has used without "
            "it ever being argued for. `rank-only` removes it: hold the top N "
            "by score, rebalanced monthly, which is the original shape of the "
            "momentum literature and the only one where the ranking can be "
            "measured on its own"
        ),
    )
    parser.add_argument(
        "--participation-rate",
        type=Decimal,
        default=PARTICIPATION_RATE,
        help=(
            "fraction of a session's published volume one account may assume "
            "it can take. The sensitivity axis: the universe is unchanged, "
            "only how much of it is reachable"
        ),
    )
    parser.add_argument(
        "--first-trading-session",
        help=(
            "refuse entries before this session while still reading earlier "
            "bars for warmup. How the sealed segment is evaluated without "
            "spending 252 of its 382 sessions on warmup"
        ),
    )
    parser.add_argument(
        "--universe",
        choices=UNIVERSES,
        default="all",
        help=(
            "which securities may be entered. `no-tpex-odd-lot-entry` refuses "
            "odd-lot entries on TPEx, whose published volume is board lots "
            "only. That changes the names held, so it is a second candidate "
            "rather than a second assumption -- see Owner decision, option 丙"
        ),
    )
    parser.add_argument(
        "--cost-multiplier",
        type=Decimal,
        default=Decimal("1"),
        help=(
            "multiply the rate-based costs and slippage. M0 section 8 requires "
            "a candidate to survive 2 before it may apply for `validated`; the "
            "20 TWD floor and the 0.3%% tax are not multiplied"
        ),
    )
    parser.add_argument(
        "--ranking",
        choices=sorted(RANKINGS),
        default="",
        help=(
            "score used to order candidates when slots are scarce. Empty means "
            "none, which is arrival order and can never be selection-measured"
        ),
    )
    args = parser.parse_args(argv)

    common = dict(
        lookback=args.lookback,
        stop_pct=args.stop_pct,
        max_holding_sessions=args.max_holding_sessions,
        ranking_name=args.ranking,
        universe=args.universe,
        participation_rate=args.participation_rate,
        first_trading_session=args.first_trading_session,
        entry_rule=args.entry,
        stop_rule=args.stop_rule,
        max_positions=args.max_positions,
        cost_multiplier=args.cost_multiplier,
    )

    if args.report_root:
        scales = {
            "m0-execution": POLICY_INITIAL_CAPITAL,
            "reference-measurement": reference_scale_nav(),
        }
        results = {
            name: run(args.dataset, opening_cash=cash, **common)
            for name, cash in scales.items()
        }
        rows, manifest = candidate_report(results)
        root = args.report_root
        root.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), root / "candidate_report.parquet")
        (root / "report_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        for row in rows:
            print(
                f"{row['scale']:<24} 期初 {row['opening_cash']:>10,.0f}"
                f"  報酬 {row['return_pct']:>7.2f}%"
                f"  回撤 {row['drawdown_pct']:>6.2f}%"
                f"  成交 {row['completed_trades']:>5}"
                f"  成本/期初 {row['cost_share_of_capital']:>6.1%}"
                f"  成本/成交額 {row['cost_share_of_turnover']:>6.2%}"
            )
            if row["rank_violations_sizing"] > 0:
                codes = json.loads(row["rank_violation_codes_json"])
                detail = ", ".join(
                    f"{k} x{v}" for k, v in codes.items() if k in SIZING_REFUSALS
                )
                # Reported, never a verdict: this is the account refusing the
                # top-ranked name, not the ranking being ignored.
                print(
                    f"  {row['scale']}: {row['rank_violations_sizing']} sessions "
                    f"where the top-ranked name would not fit ({detail})"
                )
            if not row["selection_logic_measured"]:
                # Say which of the two failures it is. The count of refusals
                # stopped deciding this in contract v1.1.0 and printing it
                # here kept implying otherwise.
                if not row["ranking_function"]:
                    why = "no ranking function declared, so fills followed arrival order"
                else:
                    why = (
                        f"{row['rank_violations_scarcity']} sessions took a "
                        "worse-scored name while a better one waited for room"
                    )
                print(
                    f"  {row['scale']}: selection-logic-not-measured -- {why}. "
                    "This row may not rank candidates against one another."
                )
        print(f"\n候選報告寫入 {root}")
        return 0

    result = run(args.dataset, opening_cash=args.opening_cash, **common)
    print(f"資料集      {Path(result['dataset_root']).name}  ({result['dataset_sha256'][:16]}…)")
    print(f"策略        {result['strategy']['name']}  lookback={result['strategy']['lookback']}"
          f"  stop={result['strategy']['stop_pct']:.0%}")
    print(f"期初資金    {result['opening_cash']:,.0f}")
    print(f"期末 NAV    {result['final_nav']:,.2f}   ({result['return_pct']:+.2f}%)")
    print(f"交易日      {result['sessions']}   完成交易 {result['completed_trades']}"
          f"   期末未平倉 {result['open_at_end']}")
    print(f"最大回撤    {result['drawdown_pct']:.2f}%   帳本分錄 {result['journal_entries']}")
    print()
    print("被拒絕的委託（前 12 種）:")
    for reason, count in list(result["refusals"].items())[:12]:
        print(f"   {count:>7}  {reason}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        print(f"\n明細寫入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
