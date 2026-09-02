"""The two controls a discretionary decision is judged against.

Contract sections 3.2 and 3.3. Three numbers, reported side by side:

    the picks            +30%
    twenty random baskets, median  +28%
    the eligible universe, equal weight  +26%

Any one of them missing and the judgement is not complete. Reporting only the
first is the thing the contract exists to prevent.

THE POPULATION IS THE DAY OF THE PURCHASE

Baskets are drawn from the universe as it stood on the entry session, not as
it stands now. A universe taken later has already dropped whatever delisted in
between, and a control drawn from survivors flatters the picks by exactly the
amount that matters.

The dataset carries delisted securities for this reason (M3's lifecycle lane).
A name with no close on the exit session is valued at its last observed close
and counted in `delisted_in_window`, rather than dropped -- dropping it would
put the survivorship back in through the other door.

REPRODUCIBLE BY ANYONE

Basket membership is `sha256(seed:market:symbol:session)`, the same scheme the
random control in `run_ledger_backtest.py` uses. Anyone holding the seed can
recompute any basket without this machine. The twenty seeds are the ones
control plan 001 fixed in advance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics as st
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from m4.rules import BrokerTerms, Side, trade_costs  # noqa: E402
from m5.ledger import POLICY_MIN_CASH_RESERVE  # noqa: E402

# Control plan 001 section 1.2. Chosen because they existed before this
# project did, so they cannot be said to have been picked.
CONTROL_SEEDS = (
    1, 2, 3, 5, 8, 13, 21, 34, 55, 89,
    144, 233, 377, 610, 987, 1597, 2584, 4181, 6765, 10946,
)


def score(seed: int, market: str, symbol: str, session: str) -> float:
    digest = hashlib.sha256(f"{seed}:{market}:{symbol}:{session}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def load_window(dataset: Path, entry: str, exit_session: str):
    """Eligible names on the entry session, and the closes that price them."""

    import pyarrow.parquet as pq

    table = pq.read_table(
        dataset / "research_dataset.parquet",
        columns=["market", "symbol", "session_date", "close", "tradability_state"],
    )
    eligible: list[tuple[str, str]] = []
    entry_close: dict[tuple[str, str], float] = {}
    last_close: dict[tuple[str, str], tuple[str, float]] = {}

    for row in table.to_pylist():
        session = row["session_date"]
        if session < entry or session > exit_session:
            continue
        key = (row["market"], row["symbol"])
        close = row["close"]
        if close is None:
            continue
        if session == entry:
            entry_close[key] = float(close)
            if row["tradability_state"] == "eligible":
                eligible.append(key)
        # Latest close at or before the exit, so a name that stopped trading is
        # valued where it stopped rather than dropped.
        prior = last_close.get(key)
        if prior is None or session > prior[0]:
            last_close[key] = (session, float(close))

    return sorted(eligible), entry_close, last_close


def basket_return(
    names: list[tuple[str, str]],
    entry_close: dict,
    last_close: dict,
    exit_session: str,
    nav: Decimal,
) -> dict[str, Any]:
    """Equal-weight, buy at the entry close, sell at the exit close, net of costs."""

    if not names:
        return {"return_pct": None, "priced": 0, "delisted_in_window": 0}

    per_position = nav * (Decimal("1") - POLICY_MIN_CASH_RESERVE) / len(names)
    terms = BrokerTerms()
    total_end = Decimal("0")
    total_start = Decimal("0")
    priced = 0
    delisted = 0

    for key in names:
        start = entry_close.get(key)
        if start is None or start <= 0:
            continue
        end_session, end = last_close.get(key, (None, None))
        if end is None:
            continue
        if end_session != exit_session:
            delisted += 1
        priced += 1

        quantity = int(per_position / Decimal(str(start)))
        if quantity <= 0:
            # Too small to buy a single share at this NAV. Counted as priced so
            # the shortfall is visible rather than silently reweighting the rest.
            total_start += per_position
            total_end += per_position
            continue
        cost_in = trade_costs(
            side=Side.BUY, price=Decimal(str(start)), quantity=quantity, terms=terms
        )
        cost_out = trade_costs(
            side=Side.SELL, price=Decimal(str(end)), quantity=quantity, terms=terms
        )
        spent = Decimal(str(start)) * quantity + cost_in.commission_charged
        got = Decimal(str(end)) * quantity - cost_out.commission_charged - cost_out.tax
        total_start += spent
        total_end += got

    if total_start <= 0:
        return {"return_pct": None, "priced": priced, "delisted_in_window": delisted}
    return {
        "return_pct": float((total_end / total_start - 1) * 100),
        "priced": priced,
        "delisted_in_window": delisted,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--entry-session", required=True)
    parser.add_argument("--exit-session", required=True)
    parser.add_argument("--nav", type=Decimal, default=Decimal("149717"))
    parser.add_argument(
        "--picks", required=True, help='JSON array, e.g. [["TWSE","2330"]]'
    )
    parser.add_argument(
        "--not-bought", default="[]", help="JSON array, contract section 5"
    )
    args = parser.parse_args(argv)

    picks = [tuple(p) for p in json.loads(args.picks)]
    not_bought = [tuple(p) for p in json.loads(args.not_bought)]

    eligible, entry_close, last_close = load_window(
        args.dataset, args.entry_session, args.exit_session
    )
    if not eligible:
        raise SystemExit(
            f"no eligible names on {args.entry_session}. The population must be "
            f"the universe on the day of the purchase (contract section 3.2), "
            f"so this cannot fall back to another session"
        )

    missing = [p for p in picks if p not in entry_close]
    if missing:
        raise SystemExit(f"no entry close for {missing} on {args.entry_session}")

    def run(names):
        return basket_return(
            list(names), entry_close, last_close, args.exit_session, args.nav
        )

    picks_result = run(picks)

    baskets = []
    for seed in CONTROL_SEEDS:
        drawn = sorted(
            eligible,
            key=lambda k: score(seed, k[0], k[1], args.entry_session),
        )[: len(picks)]
        baskets.append(run(drawn))

    basket_returns = sorted(
        b["return_pct"] for b in baskets if b["return_pct"] is not None
    )
    mine = picks_result["return_pct"]
    beaten = sum(1 for r in basket_returns if mine is not None and mine > r)

    report = {
        "contract_version": "discretionary-research-v1.0.0",
        "entry_session": args.entry_session,
        "exit_session": args.exit_session,
        "basket_size": len(picks),
        "eligible_universe_size": len(eligible),
        "picks": picks_result,
        "random_baskets": {
            "seeds": list(CONTROL_SEEDS),
            "returns_pct": basket_returns,
            "median_pct": st.median(basket_returns) if basket_returns else None,
            "min_pct": min(basket_returns) if basket_returns else None,
            "max_pct": max(basket_returns) if basket_returns else None,
            "beaten_by_picks": beaten,
            "percentile_of_picks": (
                None if not basket_returns else beaten / len(basket_returns) * 100
            ),
        },
        "equal_weight_universe": run(eligible),
        # Contract section 5. The names looked at and not bought are the control
        # for the act of selecting: if they did better, the selection subtracted.
        "considered_not_bought": run(not_bought) if not_bought else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
