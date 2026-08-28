"""Compare two candidates the way the control comparison contract requires.

The question M6.3 left open was whether the 12-1 momentum ranking helped, and
the honest answer was that nobody could say: momentum needs 252 sessions of
warmup, so the ranked run started trading a year after the unranked probe and
the two walked different histories.

Owner decision, 2026-08-27, option 乙: run each candidate over its own window
and compare only where both were trading. This produces that comparison.

Everything is recomputed inside the common window. Return is re-based to the
NAV each account held when the window opened, drawdown is re-measured over the
slice, and trades and costs are filtered by session. Carrying any figure in
from the full run would let a drawdown that happened before the comparison
count towards it.

What option 乙 costs, and why the report says so out loud: the candidate with
the shorter warmup arrives at the common window start already holding
positions and already up or down on the year. `open_positions_at_window_start`
and `nav_at_window_start` are required fields for exactly that reason. Option
甲 -- retruncating both runs and re-running -- would not have that problem, and
was not chosen.

Eight rows: two candidates, two scales, two participation rates. The scales
because ADR-0002 decision 3 says a report carrying one is missing a column
rather than being simpler. The participation rates because how much of a
session an account can take is assumed, not measured, and an assumption that
moves the answer belongs on the axis rather than pinned to one value.

The tradable universe is deliberately not on that axis. It was, until the
first run showed that refusing TPEx odd-lot entries changed which names were
held rather than how much of them was reachable -- the same strategy returned
-3.57% and -37.76% at the reference scale, which is two books, not a band.
Owner decision 2026-08-27, option 丙: the universe belongs to the candidate
definition and is reported per candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_ledger_backtest import (  # noqa: E402
    ENTRY_RULES,
    UNIVERSES,
    BrokerTerms,
    RANKINGS,
    realised_costs,
    reference_scale_nav,
    run,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from m5.ledger import POLICY_INITIAL_CAPITAL  # noqa: E402

# Both bumped with the columns. 1.0.0 carried `odd_lot_liquidity`; 1.1.0
# replaced it with `participation_rate` and a per-candidate `universe`.
#
# Declared stale once already, on the candidate report, and caught only
# because a test compared the producer's string against the document. The
# same test now covers this pair.
SCHEMA_ID = "tw-alpha-m6-control-comparison/1.1.0"
CONTRACT_VERSION = "control-comparison-v1.1.0"

SCALES = ("m0-execution", "reference-measurement")

# The sensitivity axis: how much of a session an account may assume it can
# take. The universe is identical between the two, so a difference here is a
# difference in the fill assumption and nothing else.
#
# 0.001 rather than 0 because zero is not a thinner market, it is a closed one.
PARTICIPATION_RATES = (Decimal("0.01"), Decimal("0.001"))


def trading_span(result: dict[str, Any]) -> tuple[str, str] | None:
    """First and last session this candidate actually had a position on.

    Sessions, not the dataset's span: a candidate that cannot score anything
    for its first 252 sessions was present but not trading, and counting those
    as its window is what made the M6.3 comparison meaningless.
    """

    trades = result["trades"]
    if not trades:
        return None
    first = min(t["entry_session"] for t in trades)
    last = max(t["exit_session"] for t in trades)
    return first, last


def window_metrics(
    result: dict[str, Any], start: str, end: str
) -> dict[str, Any]:
    """Every figure recomputed inside [start, end]."""

    equity = [row for row in result["equity"] if start <= row["session"] <= end]
    if not equity:
        raise SystemExit(
            "a candidate has no equity inside the common window, which means "
            "the window was derived from something other than its own trades"
        )

    opening_nav = equity[0]["nav"]
    closing_nav = equity[-1]["nav"]

    peak = opening_nav
    drawdown = 0.0
    for row in equity:
        peak = max(peak, row["nav"])
        if peak > 0:
            drawdown = max(drawdown, (peak - row["nav"]) / peak)

    in_window = [
        t for t in result["trades"] if start <= t["exit_session"] <= end
    ]
    cost, turnover = realised_costs({"trades": in_window})

    # Positions held when the window opened. The number option 乙 has to
    # disclose: an account arriving with ten positions is not starting level
    # with one arriving flat.
    #
    # Deduplicated by position, not counted by trade record. One position can
    # produce several records -- a holding that is neither whole board lots nor
    # a pure odd lot is sold as two orders, and a partial fill spreads it over
    # more. Counting records reported 16 positions carried into a window under
    # a policy that caps the book at ten, which is how the error announced
    # itself.
    carried_positions: dict[tuple[str, str, str], Decimal] = {}
    for t in result["trades"]:
        if not (t["entry_session"] < start <= t["exit_session"]):
            continue
        key = (t["market"], t["symbol"], t["entry_session"])
        # Cost basis rather than risk: the stop each position was opened with
        # is not in the trade record. The field name says which one it is.
        carried_positions[key] = carried_positions.get(key, Decimal("0")) + Decimal(
            str(t["entry_price"])
        ) * int(t["quantity"])
    carried = list(carried_positions)
    carried_risk = sum(carried_positions.values(), Decimal("0"))

    return {
        "nav_at_window_start": opening_nav,
        "open_positions_at_window_start": len(carried),
        "cost_basis_carried_into_window": float(carried_risk),
        "return_pct_in_window": (closing_nav / opening_nav - 1) * 100
        if opening_nav
        else 0.0,
        "drawdown_pct_in_window": drawdown * 100,
        "completed_trades_in_window": len(in_window),
        "cost_total_in_window": float(cost),
        "cost_share_of_turnover_in_window": float(cost / turnover)
        if turnover
        else 0.0,
    }


def compare(
    dataset: Path,
    candidates: dict[str, dict[str, str]],
    *,
    lookback: int,
    stop_pct: Decimal,
    max_holding_sessions: int,
) -> tuple[list[dict], dict]:
    scales = {
        "m0-execution": POLICY_INITIAL_CAPITAL,
        "reference-measurement": reference_scale_nav(),
    }

    results: dict[tuple[str, str, Decimal], dict] = {}
    for name, spec in candidates.items():
        for scale, cash in scales.items():
            for rate in PARTICIPATION_RATES:
                results[(name, scale, rate)] = run(
                    dataset,
                    opening_cash=cash,
                    lookback=lookback,
                    stop_pct=stop_pct,
                    max_holding_sessions=max_holding_sessions,
                    ranking_name=spec["ranking"],
                    universe=spec["universe"],
                    entry_rule=spec["entry"],
                    participation_rate=rate,
                )

    # One dataset, checked rather than assumed. Two candidates priced on
    # different data are not a comparison.
    hashes = {r["dataset_sha256"] for r in results.values()}
    if len(hashes) != 1:
        raise SystemExit(f"the runs disagree on the dataset: {sorted(hashes)}")

    rows: list[dict] = []
    windows: dict[tuple[str, str], dict] = {}
    for scale in SCALES:
        for rate in PARTICIPATION_RATES:
            spans = {}
            for name in candidates:
                span = trading_span(results[(name, scale, rate)])
                if span is None:
                    raise SystemExit(
                        f"candidate {name} completed no trades at {scale} at "
                        f"participation {rate}; there is no window to compare"
                    )
                spans[name] = span
            start = max(span[0] for span in spans.values())
            end = min(span[1] for span in spans.values())
            if start > end:
                raise SystemExit(
                    f"the two candidates never traded at the same time at "
                    f"{scale} at participation {rate}"
                )
            windows[(scale, str(rate))] = {
                "common_window_start": start,
                "common_window_end": end,
                "window_source": {
                    "start": next(n for n, s in spans.items() if s[0] == start),
                    "end": next(n for n, s in spans.items() if s[1] == end),
                },
            }
            for name, spec in candidates.items():
                result = results[(name, scale, rate)]
                sessions = [
                    row["session"]
                    for row in result["equity"]
                    if start <= row["session"] <= end
                ]
                total_sessions = len(result["equity"])
                rows.append(
                    {
                        "candidate": name,
                        "ranking_function": spec["ranking"],
                        "universe": spec["universe"],
                        "entry_rule": spec["entry"],
                        "scale": scale,
                        "participation_rate": float(rate),
                        "common_window_start": start,
                        "common_window_end": end,
                        "sessions_in_common_window": len(sessions),
                        "sessions_excluded": total_sessions - len(sessions),
                        "selection_logic_measured": bool(spec["ranking"])
                        and result["rank_violations_scarcity"] == 0,
                        **window_metrics(result, start, end),
                    }
                )

    sample = next(iter(results.values()))
    manifest = {
        "schema_id": SCHEMA_ID,
        "contract_version": CONTRACT_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": sample["dataset_sha256"],
        "dataset_root": str(sample["dataset_root"]),
        "candidates": candidates,
        "scales": list(SCALES),
        "participation_rates": [float(r) for r in PARTICIPATION_RATES],
        "windows": {f"{s}|{r}": w for (s, r), w in windows.items()},
        "strategy_version": sample["strategy"],
        "broker_terms": {
            "evidence_state": BrokerTerms().evidence_state,
            "source": BrokerTerms().source,
        },
        "reading_note": (
            "Control comparison contract section 3: conclusions hold inside "
            "the common window only, and all four scale-by-assumption "
            "combinations must be read together. Picking the favourable one "
            "is what this format exists to prevent. ADR-0002 decision 1 still "
            "binds: m0-execution returns are not evidence about a strategy."
        ),
        "option_note": (
            "Owner decision 2026-08-27, option 乙: each candidate ran its own "
            "window and only the overlap is compared. The cost is that a "
            "candidate can arrive at the window start already holding "
            "positions -- see open_positions_at_window_start."
        ),
    }
    return rows, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ranking-a", choices=sorted(RANKINGS), default="momentum-12-1")
    parser.add_argument("--ranking-b", choices=sorted(RANKINGS), default="")
    parser.add_argument("--universe-a", choices=UNIVERSES, default="all")
    parser.add_argument("--universe-b", choices=UNIVERSES, default="all")
    parser.add_argument("--entry-a", choices=ENTRY_RULES, default="breakout")
    parser.add_argument("--entry-b", choices=ENTRY_RULES, default="breakout")
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--stop-pct", type=Decimal, default=Decimal("0.08"))
    parser.add_argument("--max-holding-sessions", type=int, default=20)
    args = parser.parse_args(argv)

    candidates = {
        "a": {
            "ranking": args.ranking_a,
            "universe": args.universe_a,
            "entry": args.entry_a,
        },
        "b": {
            "ranking": args.ranking_b,
            "universe": args.universe_b,
            "entry": args.entry_b,
        },
    }
    if candidates["a"] == candidates["b"]:
        raise SystemExit(
            "both candidates are identical, so this would compare one against "
            "itself and spend a trial on a tautology. Vary --ranking, "
            "--universe or --entry"
        )
    rows, manifest = compare(
        args.dataset,
        candidates,
        lookback=args.lookback,
        stop_pct=args.stop_pct,
        max_holding_sessions=args.max_holding_sessions,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), args.out / "control_comparison.parquet")
    (args.out / "comparison_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    for scale in SCALES:
        for rate in PARTICIPATION_RATES:
            group = [
                r
                for r in rows
                if r["scale"] == scale and r["participation_rate"] == float(rate)
            ]
            print(f"\n{scale}  /  參與率 {rate}")
            print(
                f"  共同窗口 {group[0]['common_window_start']} → "
                f"{group[0]['common_window_end']}  "
                f"（{group[0]['sessions_in_common_window']} 場次）"
            )
            for row in group:
                print(
                    f"    {row['candidate']} "
                    f"{row['ranking_function'] or '(無排序)':<16}"
                    f"{row['entry_rule']:<12}"
                    f" 報酬 {row['return_pct_in_window']:>8.2f}%"
                    f"  回撤 {row['drawdown_pct_in_window']:>6.2f}%"
                    f"  成交 {row['completed_trades_in_window']:>5}"
                    f"  帶入部位 {row['open_positions_at_window_start']:>2}"
                )
    print(f"\n對照比較寫入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
