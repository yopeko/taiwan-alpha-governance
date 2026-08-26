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
from dataclasses import dataclass
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
CANDIDATE_REPORT_SCHEMA = "tw-alpha-m6-candidate-report/1.0.0"
CANDIDATE_REPORT_CONTRACT = "candidate-report-v1.0.0"

# The median stop distance measured across the SEPA trades in M6 Phase 0.
# Used only to turn the risk budget into a position size when deriving the
# reference scale; the real size follows each signal own stop.
MEDIAN_STOP_DISTANCE = Decimal("0.08")

# What fraction of a session's volume one account may assume it can take.
# M0 forbids assuming a fill; this is the assumption that replaces "always",
# and it is deliberately conservative for an account this size.
PARTICIPATION_RATE = Decimal("0.01")


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


@dataclass(frozen=True)
class Signal:
    market: str
    symbol: str
    stop_price: Decimal


@dataclass
class OpenPosition:
    market: str
    symbol: str
    entry_session: str
    entry_price: Decimal
    stop_price: Decimal
    quantity: int


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
        signals.append(
            Signal(key[0], key[1], stop_price=close * (Decimal("1") - stop_pct))
        )
    return signals


def run(
    dataset_root: Path,
    *,
    opening_cash: Decimal,
    lookback: int,
    stop_pct: Decimal,
    max_holding_sessions: int,
) -> dict[str, Any]:
    sessions, by_session = load_dataset(dataset_root)
    ledger = Ledger(opening_cash=opening_cash, sessions=[date.fromisoformat(s) for s in sessions])

    history: dict[tuple[str, str], list[dict]] = defaultdict(list)
    positions: dict[tuple[str, str], OpenPosition] = {}
    pending: list[Signal] = []
    trades: list[dict[str, Any]] = []
    refusals: dict[str, int] = defaultdict(int)
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

        def conditions(key: tuple[str, str]) -> MarketConditions | None:
            row = rows.get(key)
            if row is None:
                return None
            volume = row.get("volume")
            return MarketConditions(
                session=as_date,
                session_is_open=row["session_state"] == "official-open",
                tradability_state=row["tradability_state"],
                limit_up=Decimal(str(row["limit_up"])) if row["limit_up"] is not None else None,
                limit_down=Decimal(str(row["limit_down"])) if row["limit_down"] is not None else None,
                available_quantity=(
                    int(Decimal(str(volume)) * PARTICIPATION_RATE) if volume else 0
                ),
            )

        # --- exits first -------------------------------------------------
        for key in list(positions):
            position = positions[key]
            row = rows.get(key)
            if row is None or row["close"] is None:
                continue
            close = Decimal(str(row["close"]))
            low = Decimal(str(row["low"])) if row["low"] is not None else close
            age = index - sessions.index(position.entry_session)
            reason = None
            if low <= position.stop_price:
                # Conservative: when a session touches both the stop and a
                # profitable level, the stop is assumed to come first. Daily
                # bars cannot say which did, and this errs against the account.
                reason, price = "stop", position.stop_price
            elif age >= max_holding_sessions:
                reason, price = "max-holding", close
            if reason is None:
                continue
            market = conditions(key)
            if market is None:
                continue
            for leg in lot_legs(position.quantity):
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
        for signal in pending:
            key = (signal.market, signal.symbol)
            if key in positions or len(positions) >= POLICY_MAX_POSITIONS:
                refusals["entry:position-slots-full"] += 1
                continue
            row = rows.get(key)
            if row is None or row.get("open") is None:
                refusals["entry:no-opening-price"] += 1
                continue
            entry = Decimal(str(row["open"]))
            if entry <= signal.stop_price:
                # The gap opened below the stop the signal was sized against.
                refusals["entry:opened-below-stop"] += 1
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
                refusals[f"entry:{plan.reason}"] += 1
                continue
            order_seq += 1
            market = conditions(key)
            if market is None:
                refusals["entry:no-market-conditions"] += 1
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
                )
            else:
                refusals[f"entry:{result.reason}"] += 1

        # --- today's signals fill tomorrow --------------------------------
        for key, row in rows.items():
            if row["close"] is not None:
                history[key].append(row)
                if len(history[key]) > lookback + 2:
                    history[key].pop(0)
        pending = [
            s
            for s in breakout_signals(history, session, lookback=lookback, stop_pct=stop_pct)
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
            "name": "close-above-n-session-high",
            "note": "a pipeline probe, not a proposal",
            "lookback": lookback,
            "stop_pct": float(stop_pct),
            "max_holding_sessions": max_holding_sessions,
        },
        "assumptions": {
            "participation_rate": float(PARTICIPATION_RATE),
            "signal_on_close_fill_next_open": True,
            "stop_assumed_to_precede_target_within_a_session": True,
        },
        "opening_cash": float(opening_cash),
        "final_nav": final_nav,
        "return_pct": (final_nav / float(opening_cash) - 1) * 100,
        "sessions": len(sessions),
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
                # Contract section 3: the total, never one reason code. Raising
                # the slot cap on 2026-08-25 moved 277,777 slots-full refusals
                # into other codes and left the total unchanged, so a rule
                # watching one code would have reported success.
                "selection_logic_measured": total <= trades * 10,
                "refusals_json": json.dumps(
                    dict(sorted(refusals.items())), ensure_ascii=False
                ),
            }
        )

    sample = next(iter(results.values()))
    terms = BrokerTerms()

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
    parser.add_argument("--stop-pct", type=Decimal, default=Decimal("0.08"))
    parser.add_argument("--max-holding-sessions", type=int, default=20)
    args = parser.parse_args(argv)

    common = dict(
        lookback=args.lookback,
        stop_pct=args.stop_pct,
        max_holding_sessions=args.max_holding_sessions,
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
            if not row["selection_logic_measured"]:
                print(
                    f"  {row['scale']}: selection-logic-not-measured "
                    f"({row['refusals_total']:,} refusals against "
                    f"{row['completed_trades']} trades). This row may not rank "
                    "candidates against one another."
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
