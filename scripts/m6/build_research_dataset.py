"""M6 Phase 2: freeze the as-of warehouse into one dataset a strategy can read.

M3 answers "what was knowable on this date" one session at a time. A research
run needs the whole window in one table, and needs it to be the *same* table
next month, or two runs of the same strategy are not comparable.

This walks the calendar, asks M3.6 for every session, and writes what it said.
Nothing is computed here that M3 did not already establish, with one exception
noted below.

What each row carries
---------------------
* the official OHLCV for that security on that session, unadjusted;
* the M3.6 verdict — membership, session, market status, price, corporate
  action, and the tradability those combine into;
* the reason codes behind that verdict, so a strategy that was refused a trade
  can say which rule refused it;
* the price limits for the session.

The limits are the exception. Where the exchange published them — every
ex-rights, capital-reduction and par-value-change session — they are copied.
Everywhere else they are computed from the previous close by M4's tick-aware
rule, and the row says which of the two it was. A limit that was computed is
not evidence, and a consumer that cares about the difference can see it.

Reproducibility
---------------
The output carries the M3 dataset ids it was built from and a content hash of
its own rows. Rebuilding from the same warehouse produces the same hash; if it
does not, something upstream moved and the two research runs were never
comparable.

Reads only. Nothing under the protected production stores is opened for write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))

from asof import Warehouse, default_warehouse  # noqa: E402
from m4.rules import RuleError, price_limits, resolve_price_limits  # noqa: E402

SCHEMA_ID = "tw-alpha-m6-research-dataset/1.0.0"

SCHEMA = pa.schema(
    [
        pa.field("market", pa.string(), nullable=False),
        pa.field("session_date", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("security_instance_id", pa.string(), nullable=True),
        pa.field("open", pa.float64(), nullable=True),
        pa.field("high", pa.float64(), nullable=True),
        pa.field("low", pa.float64(), nullable=True),
        pa.field("close", pa.float64(), nullable=True),
        pa.field("volume", pa.int64(), nullable=True),
        pa.field("turnover", pa.float64(), nullable=True),
        pa.field("ohlc_state", pa.string(), nullable=True),
        pa.field("membership_state", pa.string(), nullable=False),
        pa.field("session_state", pa.string(), nullable=False),
        pa.field("market_status_state", pa.string(), nullable=False),
        pa.field("price_state", pa.string(), nullable=False),
        pa.field("corporate_action_state", pa.string(), nullable=False),
        pa.field("tradability_state", pa.string(), nullable=False),
        pa.field("reason_codes", pa.string(), nullable=True),
        pa.field("limit_up", pa.float64(), nullable=True),
        pa.field("limit_down", pa.float64(), nullable=True),
        pa.field("limit_basis", pa.string(), nullable=False),
        pa.field("previous_close", pa.float64(), nullable=True),
    ]
)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def action_limit_inputs(
    warehouse: Warehouse,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Everything a limit on a restatement session can be built from.

    A session that restates a price cannot take its limits from the previous
    close — M4.1 measured that and it is wrong on every row carrying a cash
    capital increase. So a session with a corporate action either gets the
    exchange's own published limits, or gets them from the two reference
    prices by the official formula, or gets nothing at all.
    """

    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in warehouse._actions:
        key = (
            str(row.get("market")),
            str(row.get("symbol")),
            str(row.get("effective_date")),
        )
        found.setdefault(
            key,
            {
                "limit_up": row.get("limit_up"),
                "limit_down": row.get("limit_down"),
                "reference_price": row.get("reference_price"),
                "dividend_only_reference_price": row.get("dividend_only_reference_price"),
            },
        )
    return found


def published_limits(warehouse: Warehouse) -> dict[tuple[str, str, str], tuple[Any, Any]]:
    """Limits the exchange itself published, keyed by market, symbol, session.

    These come from the corporate-action table, which carries them for every
    event that restates a price: ex-rights, capital reductions and par-value
    changes. Copying beats recomputing — the published value is the fact, and
    M4's formula reproduces it rather than defining it.
    """

    found: dict[tuple[str, str, str], tuple[Any, Any]] = {}
    for row in warehouse._actions:
        up, down = row.get("limit_up"), row.get("limit_down")
        if up is None or down is None:
            continue
        key = (str(row.get("market")), str(row.get("symbol")), str(row.get("effective_date")))
        found.setdefault(key, (up, down))
    return found


def previous_closes(warehouse: Warehouse) -> dict[tuple[str, str], list[tuple[str, Any]]]:
    """Each security's closes in session order, for the ordinary limit base."""

    series: dict[tuple[str, str], list[tuple[str, Any]]] = {}
    for row in warehouse._prices:
        close = row.get("close")
        if close is None:
            continue
        key = (str(row.get("market")), str(row.get("symbol")))
        series.setdefault(key, []).append((str(row.get("session_date")), close))
    for values in series.values():
        values.sort()
    return series


def build(out_root: Path, *, sessions: int | None = None) -> dict[str, Any]:
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")
    warehouse = default_warehouse()

    calendar = sorted(
        {
            str(row["session_date"])
            for row in warehouse._calendar
            if str(row.get("session_state")) == "official-open"
        }
    )
    if sessions:
        calendar = calendar[:sessions]

    prices = {
        (str(r.get("market")), str(r.get("symbol")), str(r.get("session_date"))): r
        for r in warehouse._prices
    }
    actions = action_limit_inputs(warehouse)
    closes = previous_closes(warehouse)
    previous: dict[tuple[str, str], Any] = {}
    close_cursor: dict[tuple[str, str], int] = {}

    rows: list[dict[str, Any]] = []
    limit_basis_counts: dict[str, int] = {}
    for session in calendar:
        result = warehouse.reconstruct(as_of_session=session, decision_as_of=session)
        for state in result.securities:
            key = (state.market, state.symbol)
            price = prices.get((state.market, state.symbol, session))
            prior = previous.get(key)

            action = actions.get((state.market, state.symbol, session))
            if action and action["limit_up"] is not None and action["limit_down"] is not None:
                up, down = float(action["limit_up"]), float(action["limit_down"])
                basis = "publisher-exact"
            elif action:
                reference = _decimal(action["reference_price"])
                dividend_only = _decimal(action["dividend_only_reference_price"])
                if reference is not None and dividend_only is not None:
                    computed_up, computed_down, _ = resolve_price_limits(
                        reference,
                        is_ex_rights_session=True,
                        ex_rights_reference_price=reference,
                        dividend_only_reference_price=dividend_only,
                    )
                    up, down = float(computed_up), float(computed_down)
                    basis = "computed-official-ex-rights-formula"
                else:
                    # Fail closed rather than fall through to the previous
                    # close. On a restatement session that base is not merely
                    # imprecise, it is the wrong number.
                    up = down = None
                    basis = "blocked-restatement-without-reference-prices"
            elif prior is not None and float(prior) > 0:
                try:
                    computed_up, computed_down = price_limits(Decimal(str(prior)))
                    up, down = float(computed_up), float(computed_down)
                    basis = "computed-from-previous-close"
                except RuleError:
                    up = down = None
                    basis = "blocked-tick-band"
            else:
                up = down = None
                basis = "blocked-no-previous-close"
            limit_basis_counts[basis] = limit_basis_counts.get(basis, 0) + 1

            rows.append(
                {
                    "market": state.market,
                    "session_date": session,
                    "symbol": state.symbol,
                    "security_instance_id": state.security_instance_id,
                    "open": _float(price, "open"),
                    "high": _float(price, "high"),
                    "low": _float(price, "low"),
                    "close": _float(price, "close"),
                    "volume": _int(price, "volume"),
                    "turnover": _float(price, "turnover"),
                    "ohlc_state": str(price.get("ohlc_state")) if price else None,
                    "membership_state": state.membership_state,
                    "session_state": state.session_state,
                    "market_status_state": state.market_status_state,
                    "price_state": state.price_state,
                    "corporate_action_state": state.corporate_action_state,
                    "tradability_state": state.tradability_state,
                    "reason_codes": "|".join(state.reason_codes) or None,
                    "limit_up": up,
                    "limit_down": down,
                    "limit_basis": basis,
                    "previous_close": float(prior) if prior is not None else None,
                }
            )
            if price is not None and price.get("close") is not None:
                previous[key] = price["close"]

    rows.sort(key=lambda r: (r["session_date"], r["market"], r["symbol"]))
    out_root.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    target = out_root / "research_dataset.parquet"
    pq.write_table(table, target)
    content_hash = hashlib.sha256(target.read_bytes()).hexdigest()

    tradability = {}
    for row in rows:
        tradability[row["tradability_state"]] = tradability.get(row["tradability_state"], 0) + 1

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "warehouse_dataset_id": warehouse.dataset_id,
        "warehouse_roots": {
            "calendar": str(warehouse.calendar_root),
            "prices": str(warehouse.prices_root),
            "status": str(warehouse.status_root),
        },
        "sessions": len(calendar),
        "window": {"start": calendar[0], "end": calendar[-1]} if calendar else {},
        "rows": len(rows),
        "distinct_securities": len({(r["market"], r["symbol"]) for r in rows}),
        "sha256": content_hash,
        "tradability_state_counts": dict(sorted(tradability.items())),
        "limit_basis_counts": dict(sorted(limit_basis_counts.items())),
        "notes": [
            "Prices are the official unadjusted bars; no adjusted series is "
            "derived here and none may be without a documented method.",
            "A limit marked computed-from-previous-close is not evidence: the "
            "exchange published limits only for sessions that restate a price.",
            "Warmup is the caller's problem. A 200-day average needs 200 "
            "sessions of this window before it means anything.",
            "volume means different things per market. TWSE includes "
            "intraday odd lots, TPEx is whole board lots only and excludes "
            "the after-hours fixed-price session. Owner decision D2 keeps "
            "both as published, so a liquidity threshold has to be set per "
            "market or it quietly excludes TPEx names.",
            "Every security the exchange quoted is here, including ones the "
            "lifecycle source does not cover. They carry "
            "not-in-lifecycle-source and are never eligible. Out of scope is "
            "a verdict with a reason code, not an absence.",
        ],
    }
    (out_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def _float(row: dict[str, Any] | None, field: str) -> float | None:
    if row is None or row.get(field) is None:
        return None
    return float(row[field])


def _int(row: dict[str, Any] | None, field: str) -> int | None:
    if row is None or row.get(field) is None:
        return None
    return int(row[field])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument(
        "--sessions", type=int, help="build only the first N sessions, for a smoke run"
    )
    args = parser.parse_args(argv)
    manifest = build(args.out_root, sessions=args.sessions)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
