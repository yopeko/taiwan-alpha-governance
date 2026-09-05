"""Every position a run took, as a table a person can read and a spreadsheet
can diff against another backtester.

WHY THIS EXISTS

The backtest report already carried the trades. It did not carry them in a
form anyone could check: a JSON array of 114 objects answers "what was the
return" and not "which names, for how long, and why did that one close there".
The first time a result was compared against a commercial backtester the
question was immediately the second one, and nothing here could answer it.

WHAT RECONCILES AND WHAT CANNOT

Two backtesters disagreeing on the same rules is normal, and the disagreement
is usually not in the rules. Before blaming the signal, check these -- each
one is a deliberate choice recorded elsewhere in this repository, and each
moves a result by more than a rule change would:

    prices          unadjusted, official closes. No back-adjusted series
                    exists here and M0 forbids deriving one without a written
                    method, so an ex-dividend session shows a real drop that
                    an adjusted vendor series does not.
    entry           the session AFTER the signal, at its open. A backtester
                    filling on the signal bar's close is trading on a price
                    that was not knowable when the signal formed.
    stop fills      `min(stop, open)`. A gapped session cannot fill at a
                    price that never traded; filling every stop at the stop
                    was measured on 2026-09-04 as 6.23% of opening NAV of
                    free money.
    costs           real broker terms with a NT$20 minimum per side, 0.3%
                    sell tax and slippage. At the M0 scale this alone took
                    47% of opening capital in one run.
    liquidity       an account may take at most `participation_rate` of a
                    session's volume, and the ledger refuses what does not
                    fit. Refusals are counted, not silently skipped.
    universe        `tradability_state` gates every entry. A security under a
                    disposition measure or in a full-delivery interval is
                    refused, with a reason code.
    sizing          M0 section 8 risk budget, not a fixed lot or a fixed
                    fraction. Position size falls out of the stop distance.

`--csv` writes one row per position, open ones included, so a difference can
be found name by name instead of argued about in aggregate.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

FIELDS = (
    "market",
    "symbol",
    "entry_session",
    "exit_session",
    "holding_sessions",
    "quantity",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_price",
    "exit_reason",
    "gross_pnl",
    "return_pct",
)


def rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Closed trades then open positions, each with its own gross result.

    **Gross, and the column says so.** Costs in this repository are charged
    per leg by the rules module and depend on the whole fill, so a per-trade
    net would have to re-derive them and would disagree with the report's own
    total. The report's `cost_total` is the number that has been checked.
    """

    out: list[dict[str, Any]] = []
    for trade in report.get("trades", []):
        entry, exit_price = trade["entry_price"], trade["exit_price"]
        out.append(
            {
                **{k: trade.get(k) for k in FIELDS if k in trade},
                "gross_pnl": (exit_price - entry) * trade["quantity"],
                "return_pct": (exit_price / entry - 1) * 100 if entry else None,
            }
        )
    for position in report.get("open_positions", []):
        entry, last = position["entry_price"], position.get("last_close")
        out.append(
            {
                **{k: position.get(k) for k in FIELDS if k in position},
                "exit_session": "",
                "exit_price": last,
                "exit_reason": "still-open",
                "gross_pnl": (
                    None if last is None else (last - entry) * position["quantity"]
                ),
                "return_pct": (
                    None if last is None or not entry else (last / entry - 1) * 100
                ),
            }
        )
    return out


def summarise(report: dict[str, Any], listed: list[dict[str, Any]]) -> None:
    closed = [r for r in listed if r["exit_reason"] != "still-open"]
    strategy = report.get("strategy", {})
    print(f"策略        {strategy.get('name')}")
    print(f"進場規則    {strategy.get('entry_rule')}   停損 {strategy.get('stop_pct')}"
          f"   報酬風險比 {strategy.get('reward_risk')}"
          f"   持有上限 {strategy.get('max_holding_sessions')} 場次")
    print(f"期初 {report['opening_cash']:,.0f}   期末 {report['final_nav']:,.2f}"
          f"   報酬 {report['return_pct']:+.2f}%   回撤 {report['drawdown_pct']:.2f}%")
    print(f"完成交易 {len(closed)}   期末未平倉 {len(listed) - len(closed)}")

    if closed:
        held = [r["holding_sessions"] for r in closed if r.get("holding_sessions") is not None]
        if held:
            print()
            print(f"持有長度（場次）  中位 {statistics.median(held):.0f}"
                  f"   平均 {statistics.mean(held):.1f}"
                  f"   最短 {min(held)}   最長 {max(held)}")
        wins = [r for r in closed if (r["gross_pnl"] or 0) > 0]
        print(f"毛勝率            {len(wins)}/{len(closed)} = {len(wins)/len(closed)*100:.1f}%"
              f"   （毛額，成本另計，見 cost_total）")

        print()
        print("出場原因         筆數   持有中位   毛報酬中位")
        for reason, count in Counter(r["exit_reason"] for r in closed).most_common():
            group = [r for r in closed if r["exit_reason"] == reason]
            h = [r["holding_sessions"] for r in group if r.get("holding_sessions") is not None]
            g = [r["return_pct"] for r in group if r["return_pct"] is not None]
            print(f"  {reason:<14} {count:>5}   {statistics.median(h):>8.0f}"
                  f"   {statistics.median(g):>+9.2f}%")

    still = [r for r in listed if r["exit_reason"] == "still-open"]
    if still:
        print()
        print("期末仍持有:")
        for r in still:
            head = (
                f"  {r['symbol']:>6} {r['market']:<5} 進 {r['entry_session']}"
                f" @ {r['entry_price']:.4f}  已持有 {r['holding_sessions']} 場次"
            )
            if r["return_pct"] is None:
                # No close on the final session. **Not a display problem.** A
                # held security that stops being quoted is skipped by the exit
                # loop entirely -- stop, target and the holding limit all need
                # a price -- so it stays in the book for the rest of the
                # window, marked at its entry price. Said plainly here because
                # the count it used to hide behind said nothing.
                print(f"{head}  最後場次無收盤——出場迴圈需要價格，所以它沒有出場")
            else:
                print(f"{head}  最後收盤 {r['exit_price']}  毛 {r['return_pct']:+.2f}%")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="a run's JSON output")
    parser.add_argument("--csv", type=Path, help="also write one row per position")
    parser.add_argument("--head", type=int, default=20, help="how many to print")
    parser.add_argument(
        "--reason", help="only positions that closed for this reason"
    )
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    listed = rows(report)
    if not listed:
        raise SystemExit(
            f"{args.report} records no positions. A run with no trades is a "
            f"result, but it is not one this tool can list"
        )
    summarise(report, listed)

    shown = [r for r in listed if not args.reason or r["exit_reason"] == args.reason]
    print()
    print(f"逐筆（{'全部' if not args.reason else args.reason}，前 {args.head} / {len(shown)}）:")
    print(f"  {'代號':<7}{'進場':<12}{'出場':<12}{'場次':>5}{'股數':>8}"
          f"{'進':>11}{'停損':>11}{'停利':>11}{'出':>11}{'毛%':>9}  原因")
    for r in shown[: args.head]:
        target = "" if r.get("target_price") is None else f"{r['target_price']:.2f}"
        print(
            f"  {r['symbol']:<7}{r['entry_session']:<12}{str(r['exit_session']):<12}"
            f"{r.get('holding_sessions', ''):>5}{r['quantity']:>8}"
            f"{r['entry_price']:>11.4f}{r.get('stop_price', 0):>11.2f}{target:>11}"
            f"{(r['exit_price'] or 0):>11.4f}"
            f"{(r['return_pct'] if r['return_pct'] is not None else 0):>+9.2f}"
            f"  {r['exit_reason']}"
        )

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(FIELDS))
            writer.writeheader()
            for r in listed:
                writer.writerow({k: r.get(k) for k in FIELDS})
        print()
        print(f"寫入 {args.csv}（{len(listed)} 列，utf-8-sig，Excel 直接開）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
