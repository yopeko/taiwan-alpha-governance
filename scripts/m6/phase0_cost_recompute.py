"""M6 Phase 0: recompute an existing SEPA backtest under honest costs.

Nothing is re-simulated here. The entry and exit prices, dates and sequence
are taken exactly as the original backtest produced them, and only three
things are corrected:

* **Share counts become whole.** The backtest sizes a position as
  `allocation / price`, which yields fractional shares — 455.5157 of one
  security, 2278.5038 of another. Those do not exist.
* **Commission gets its floor.** The backtest charges `gross * 0.001425` with
  no minimum and no truncation. Taiwan brokers bill whole NTD with a floor
  around NT$20, which on a small position is several times the proportional
  fee.
* **Slippage widens to the M0 research assumption.** The backtest uses 10 bps
  per side; M0 section 7.2 specifies 20 bps for daily and odd-lot research.

Holding the fills fixed is the point. Re-simulating would change which trades
happened, and then the comparison would confound "the cost model was wrong"
with "the strategy took different trades". This isolates the first.

Reads only. The screener's DuckDB, raw store and archives are never opened.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from math import floor
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from m4.rules import BrokerTerms, RuleError, Side, classify_lot, trade_costs  # noqa: E402
from m5.ledger import plan_position  # noqa: E402

SCHEMA_ID = "tw-alpha-m6-phase0-cost-recompute/1.0.0"

# What the backtest itself used, read from the report's metadata sheet and
# asserted rather than assumed.
BACKTEST_COMMISSION_RATE = Decimal("0.001425")
BACKTEST_SELL_TAX_RATE = Decimal("0.003")

# M0 section 7.2.
M0_SLIPPAGE_BPS = Decimal("20")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def backtest_pnl(shares: Decimal, entry: Decimal, exit_price: Decimal) -> dict[str, Decimal]:
    """Reproduce the original arithmetic exactly, to have something to compare.

    `entry_cost = shares * price * (1 + commission)` and
    `proceeds = shares * price * (1 - commission - tax)`: proportional, with no
    minimum and no rounding to whole NTD.
    """

    outlay = shares * entry * (Decimal("1") + BACKTEST_COMMISSION_RATE)
    proceeds = shares * exit_price * (
        Decimal("1") - BACKTEST_COMMISSION_RATE - BACKTEST_SELL_TAX_RATE
    )
    return {
        "shares": shares,
        "outlay": outlay,
        "proceeds": proceeds,
        "pnl": proceeds - outlay,
        "commission": shares * entry * BACKTEST_COMMISSION_RATE
        + shares * exit_price * BACKTEST_COMMISSION_RATE,
        "tax": shares * exit_price * BACKTEST_SELL_TAX_RATE,
    }


def honest_pnl(
    shares: Decimal, entry: Decimal, exit_price: Decimal, terms: BrokerTerms
) -> dict[str, Any]:
    """The same fills, priced through the M4 cost model on whole shares.

    Flooring rather than rounding: a position is sized by what the cash can
    buy, so the achievable quantity is never more than the fractional one.
    """

    quantity = int(floor(shares))
    if quantity <= 0:
        return {"quantity": 0, "skipped": "fractional-position-below-one-share"}
    buy = trade_costs(side=Side.BUY, price=entry, quantity=quantity, terms=terms)
    sell = trade_costs(side=Side.SELL, price=exit_price, quantity=quantity, terms=terms)
    try:
        classify_lot(quantity)
        lot_state = "valid"
    except RuleError:
        # 2,278 shares is two board lots plus 278 odd. A broker fills that as
        # two separate orders, and the odd-lot leg trades in its own session
        # with its own liquidity. Recorded rather than corrected: pretending it
        # is one fill is exactly the kind of optimism this exercise measures.
        lot_state = "mixed-board-and-odd-needs-two-orders"
    return {
        "quantity": quantity,
        "outlay": -buy.net_cash_delta,
        "proceeds": sell.net_cash_delta,
        "pnl": sell.net_cash_delta + buy.net_cash_delta,
        "commission": buy.commission + sell.commission,
        "tax": sell.tax,
        "minimum_commission_applied": bool(
            buy.minimum_commission_applied or sell.minimum_commission_applied
        ),
        "lot_state": lot_state,
    }


def widen_slippage(
    entry: Decimal, exit_price: Decimal, applied_bps: Decimal
) -> tuple[Decimal, Decimal]:
    """Undo the backtest's slippage and reapply M0's.

    The report stores fill prices with slippage already inside them, so the
    raw price has to be recovered before a different assumption can be applied.
    """

    factor = applied_bps / Decimal("10000")
    raw_entry = entry / (Decimal("1") + factor)
    raw_exit = exit_price / (Decimal("1") - factor)
    wider = M0_SLIPPAGE_BPS / Decimal("10000")
    return raw_entry * (Decimal("1") + wider), raw_exit * (Decimal("1") - wider)


def rescale(
    trades: pd.DataFrame, account: Decimal, weight: Decimal, terms: BrokerTerms
) -> dict[str, Any]:
    """The same fills, at the position size an M0 account could actually take.

    The reports were produced with NT$1,000,000 across ten names, so each
    position is around NT$100,000 and the NT$20 commission floor never binds.
    M0 allows NT$10,000 across two names with a 45% cap per name, which is
    about NT$4,500 — and there the floor is most of the fee.

    Quantities are floored, so a trade whose budget cannot buy a single share
    is reported as untakeable rather than rounded up into existence.
    """

    budget = account * weight
    rows: list[dict[str, Any]] = []
    for _, trade in trades.iterrows():
        entry = _decimal(trade["entry_price"])
        exit_price = _decimal(trade["exit_price"])
        quantity = int(floor(budget / entry))
        if quantity <= 0:
            rows.append({"takeable": False, "pnl": 0.0, "cost": 0.0, "notional": 0.0})
            continue
        buy = trade_costs(side=Side.BUY, price=entry, quantity=quantity, terms=terms)
        sell = trade_costs(side=Side.SELL, price=exit_price, quantity=quantity, terms=terms)
        rows.append(
            {
                "takeable": True,
                "pnl": float(sell.net_cash_delta + buy.net_cash_delta),
                "cost": float(buy.total_cost + sell.total_cost),
                "notional": float(entry * quantity),
                "minimum_applied": bool(
                    buy.minimum_commission_applied or sell.minimum_commission_applied
                ),
            }
        )
    frame = pd.DataFrame(rows)
    taken = frame[frame["takeable"]]
    total_notional = float(taken["notional"].sum()) if not taken.empty else 0.0
    return {
        "account": float(account),
        "position_budget": float(budget),
        "takeable_trades": int(len(taken)),
        "untakeable_trades": int((~frame["takeable"]).sum()),
        "minimum_commission_trades": int(taken["minimum_applied"].sum()) if not taken.empty else 0,
        "pnl": float(taken["pnl"].sum()) if not taken.empty else 0.0,
        "cost": float(taken["cost"].sum()) if not taken.empty else 0.0,
        "cost_pct_of_traded_notional": (
            float(taken["cost"].sum()) / total_notional * 100.0 if total_notional else 0.0
        ),
        "traded_notional": total_notional,
        # Scale-invariant. Return on the account is not comparable here: the
        # reference case puts a tenth of NAV in each name and the M0 case puts
        # 45%, so the account figure would measure the weight difference rather
        # than the cost difference this table exists to show.
        "pnl_per_100_notional": (
            float(taken["pnl"].sum()) / total_notional * 100.0 if total_notional else 0.0
        ),
    }


def risk_sized(
    trades: pd.DataFrame, account: Decimal, terms: BrokerTerms
) -> dict[str, Any]:
    """The same fills, sized by M0's risk policy rather than by weight.

    `plan_position` applies every cap in M0 section 8 and refuses instead of
    rounding up, including the one that matters most at this account size: a
    round trip whose cost exceeds the risk the position was sized to take.
    Those refusals are the finding, not an error to work around.
    """

    rows: list[dict[str, Any]] = []
    for _, trade in trades.iterrows():
        entry = _decimal(trade["entry_price"])
        exit_price = _decimal(trade["exit_price"])
        stop = _decimal(trade["stop_price"])
        plan = plan_position(
            nav=account,
            price=entry,
            stop_price=stop,
            open_positions=0,
            settled_cash=account,
            terms=terms,
        )
        if not plan.is_trade:
            rows.append({"takeable": False, "reason": plan.reason, "pnl": 0.0,
                         "cost": 0.0, "notional": 0.0, "minimum_applied": False})
            continue
        buy = trade_costs(side=Side.BUY, price=entry, quantity=plan.quantity, terms=terms)
        sell = trade_costs(side=Side.SELL, price=exit_price, quantity=plan.quantity, terms=terms)
        rows.append(
            {
                "takeable": True,
                "reason": plan.reason,
                "pnl": float(sell.net_cash_delta + buy.net_cash_delta),
                "cost": float(buy.total_cost + sell.total_cost),
                "notional": float(entry * plan.quantity),
                "minimum_applied": bool(
                    buy.minimum_commission_applied or sell.minimum_commission_applied
                ),
                "quantity": plan.quantity,
                "stop_distance_pct": float((entry - stop) / entry * 100),
            }
        )
    frame = pd.DataFrame(rows)
    taken = frame[frame["takeable"]]
    refused = frame[~frame["takeable"]]
    total_notional = float(taken["notional"].sum()) if not taken.empty else 0.0
    return {
        "account": float(account),
        "sizing": "m0-risk-policy",
        "takeable_trades": int(len(taken)),
        "untakeable_trades": int(len(refused)),
        "refusal_reasons": refused["reason"].value_counts().to_dict() if not refused.empty else {},
        "median_position_notional": (
            float(taken["notional"].median()) if not taken.empty else 0.0
        ),
        "median_stop_distance_pct": (
            float(taken["stop_distance_pct"].median()) if not taken.empty else 0.0
        ),
        "minimum_commission_trades": int(taken["minimum_applied"].sum()) if not taken.empty else 0,
        "pnl": float(taken["pnl"].sum()) if not taken.empty else 0.0,
        "cost": float(taken["cost"].sum()) if not taken.empty else 0.0,
        "traded_notional": total_notional,
        "cost_pct_of_traded_notional": (
            float(taken["cost"].sum()) / total_notional * 100.0 if total_notional else 0.0
        ),
        "pnl_per_100_notional": (
            float(taken["pnl"].sum()) / total_notional * 100.0 if total_notional else 0.0
        ),
        "pnl_pct_of_account": (
            float(taken["pnl"].sum()) / float(account) * 100.0 if account else 0.0
        ),
    }


def recompute(report: Path, sheet: str) -> dict[str, Any]:
    book = pd.ExcelFile(report)
    metadata = book.parse("metadata").iloc[0]
    trades = book.parse(sheet)
    if trades.empty:
        raise SystemExit(f"{sheet} has no trades")

    stated_commission = _decimal(metadata["commission_rate"])
    stated_tax = _decimal(metadata["sell_tax_rate"])
    if stated_commission != BACKTEST_COMMISSION_RATE or stated_tax != BACKTEST_SELL_TAX_RATE:
        raise SystemExit(
            "the report was produced with different rates than this script "
            f"reproduces: {stated_commission} / {stated_tax}"
        )
    applied_bps = _decimal(metadata["slippage_bps"])
    terms = BrokerTerms()

    rows: list[dict[str, Any]] = []
    for _, trade in trades.iterrows():
        shares = _decimal(trade["shares"])
        entry = _decimal(trade["entry_price"])
        exit_price = _decimal(trade["exit_price"])
        original = backtest_pnl(shares, entry, exit_price)
        whole = honest_pnl(shares, entry, exit_price, terms)
        wide_entry, wide_exit = widen_slippage(entry, exit_price, applied_bps)
        wide = honest_pnl(shares, wide_entry, wide_exit, terms)
        rows.append(
            {
                "symbol": str(trade["symbol"]),
                "market": str(trade["market"]),
                "entry_date": str(trade["entry_date"])[:10],
                "exit_date": str(trade["exit_date"])[:10],
                "exit_reason": str(trade["exit_reason"]),
                "shares_fractional": float(shares),
                "shares_whole": whole.get("quantity", 0),
                "notional": float(shares * entry),
                "pnl_backtest": float(original["pnl"]),
                "pnl_whole_shares_real_costs": float(whole.get("pnl", 0)),
                "pnl_plus_m0_slippage": float(wide.get("pnl", 0)),
                "cost_backtest": float(original["commission"] + original["tax"]),
                "cost_honest": float(whole.get("commission", 0) + whole.get("tax", 0)),
                "minimum_commission_applied": whole.get("minimum_commission_applied", False),
                "lot_state": whole.get("lot_state", "n/a"),
            }
        )

    frame = pd.DataFrame(rows)
    initial_cash = float(metadata["initial_cash"])
    totals = {
        "trades": len(frame),
        "pnl_backtest": frame["pnl_backtest"].sum(),
        "pnl_whole_shares_real_costs": frame["pnl_whole_shares_real_costs"].sum(),
        "pnl_plus_m0_slippage": frame["pnl_plus_m0_slippage"].sum(),
        "cost_backtest": frame["cost_backtest"].sum(),
        "cost_honest": frame["cost_honest"].sum(),
        "trades_with_fractional_shares": int(
            (frame["shares_fractional"] != frame["shares_whole"]).sum()
        ),
        "trades_hitting_minimum_commission": int(
            frame["minimum_commission_applied"].sum()
        ),
        "trades_needing_two_orders": int(
            frame["lot_state"].eq("mixed-board-and-odd-needs-two-orders").sum()
        ),
    }
    # Expressed against opening capital rather than compounded: the fills are
    # held fixed, so a compounded path would imply a re-simulation this script
    # deliberately does not do.
    for key in ("pnl_backtest", "pnl_whole_shares_real_costs", "pnl_plus_m0_slippage"):
        totals[f"{key}_pct_of_initial_cash"] = totals[key] / initial_cash * 100.0

    # M0 section 8, sized the way the policy actually sizes: by risk, using
    # each trade's own stop. The 45% weight cap is not what binds — a 0.75%
    # risk budget against an 8% stop allows far less than 45% of NAV, and
    # sizing by the weight cap would have understated the problem.
    m0_scale = risk_sized(trades, Decimal("10000"), terms)
    reference_scale = rescale(
        trades, _decimal(initial_cash), Decimal("1") / _decimal(metadata["max_positions"]), terms
    )

    return {
        "schema_id": SCHEMA_ID,
        "m0_account_scale": m0_scale,
        "reference_account_scale": reference_scale,
        "report": str(report),
        "sheet": sheet,
        "window": {"start": str(metadata["start"])[:10], "end": str(metadata["end"])[:10]},
        "strategy": str(metadata["strategy"]),
        "signal_profile": str(metadata["signal_profile"]),
        "min_score": float(metadata["min_score"]),
        "initial_cash": initial_cash,
        "max_positions": int(metadata["max_positions"]),
        "backtest_slippage_bps": float(applied_bps),
        "m0_slippage_bps": float(M0_SLIPPAGE_BPS),
        "totals": totals,
        "per_trade": frame.to_dict(orient="records"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sheet", default="trades_legacy")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    result = recompute(args.report, args.sheet)
    totals = result["totals"]
    print(f"報表      : {Path(result['report']).name}")
    print(f"分頁      : {result['sheet']}")
    print(f"期間      : {result['window']['start']} .. {result['window']['end']}")
    print(f"策略      : {result['strategy']} / {result['signal_profile']} / score>={result['min_score']:.0f}")
    print(f"資金      : {result['initial_cash']:,.0f}   最大持股 {result['max_positions']}")
    print()
    print(f"完成交易  : {totals['trades']}")
    print(f"  其中股數為小數        : {totals['trades_with_fractional_shares']}")
    print(f"  其中觸及最低手續費    : {totals['trades_hitting_minimum_commission']}")
    print(f"  其中需拆成兩張單      : {totals['trades_needing_two_orders']}")
    print()
    print(f"{'情境':<34}{'損益':>14}{'佔初始資金':>12}")
    print(f"{'原回測':<34}{totals['pnl_backtest']:>14,.0f}{totals['pnl_backtest_pct_of_initial_cash']:>11.2f}%")
    print(f"{'整股 + 真實費用(含最低)':<30}{totals['pnl_whole_shares_real_costs']:>14,.0f}"
          f"{totals['pnl_whole_shares_real_costs_pct_of_initial_cash']:>11.2f}%")
    print(f"{'再加 M0 滑價 20bps':<32}{totals['pnl_plus_m0_slippage']:>14,.0f}"
          f"{totals['pnl_plus_m0_slippage_pct_of_initial_cash']:>11.2f}%")
    print()
    print(f"手續費+稅  原回測 {totals['cost_backtest']:>10,.0f}   誠實 {totals['cost_honest']:>10,.0f}"
          f"   低估 {totals['cost_honest'] - totals['cost_backtest']:>10,.0f}")

    m0 = result["m0_account_scale"]
    ref = result["reference_account_scale"]
    print()
    print("--- 同樣的進出價，換成不同的帳戶規模 ---")
    print("(每 100 元成交額的數字，與帳戶規模無關；佔帳戶的報酬率不可比，"
          "因為兩者的單檔權重不同)")
    print(f"{'帳戶':<12}{'每筆預算':>10}{'可下單':>8}{'觸及最低費':>11}"
          f"{'成本/100元':>12}{'淨損益/100元':>13}")
    print(
        f"{'報表原始(權重)':<14}{ref['position_budget']:>8,.0f}"
        f"{ref['takeable_trades']:>8}{ref['minimum_commission_trades']:>11}"
        f"{ref['cost_pct_of_traded_notional']:>11.2f}%{ref['pnl_per_100_notional']:>12.2f}%"
    )
    print(
        f"{'M0 一萬元(風險)':<13}{m0['median_position_notional']:>8,.0f}"
        f"{m0['takeable_trades']:>8}{m0['minimum_commission_trades']:>11}"
        f"{m0['cost_pct_of_traded_notional']:>11.2f}%{m0['pnl_per_100_notional']:>12.2f}%"
    )
    print()
    print(f"M0 風險化部位中位數 {m0['median_position_notional']:,.0f} 元，"
          f"停損距離中位數 {m0['median_stop_distance_pct']:.1f}%")
    print(f"M0 下 {m0['untakeable_trades']}/{totals['trades']} 筆被政策拒絕：")
    for reason, count in sorted(m0["refusal_reasons"].items(), key=lambda kv: -kv[1]):
        print(f"    {count:>3}  {reason}")

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
