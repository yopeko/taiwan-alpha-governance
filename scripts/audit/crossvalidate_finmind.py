"""Cross-validate the M3 warehouse and the M6 dataset against FinMind.

FinMind is an independent vendor. It cannot define anything here -- the
exchanges do that -- but it can answer one question the warehouse cannot ask
of itself: is there a security, or a session, or a number that we never saw?
A warehouse validated only against its own sources reports itself complete no
matter how much it is missing.

The whole run uses FinMind's free tier, which needs no token. Free tier gives
300 requests/hour and refuses the whole-market-by-date form (HTTP 400, "Your
level is free"), so every query here is one security over the full window.

    python scripts/audit/crossvalidate_finmind.py --out C:/tmp/finmind-audit-01

Four checks, in the order they build on each other:

  duplicates Does any (market, symbol, session) appear twice in the
             warehouse? record_id used to be hashed over snapshot_id, so
             re-capturing a session minted "new" records that PIT
             de-duplication could not see. Fixed in M3.4 after this check
             found 3,071 of them; the check stays because it is cheap and it
             is what noticed.

  orphans    Which securities have official prices in the warehouse but no
             row in the lifecycle table? This used to measure silent data
             loss -- the M6 export walked the lifecycle table, so those
             securities left with their prices and no reason code. The export
             now carries them with `not-in-lifecycle-source` and refuses
             them, so the number here measures the licensed vendor's coverage
             gap rather than a hole in the dataset. It should stay small and
             be explainable; `test_every_priced_security_reaches_the_dataset`
             is what now guards against the loss itself.

  universe   Every symbol we carry, does FinMind have it? And of the ones it
             has that we do not, do any actually trade inside our window? A
             symbol that traded and is absent is a hole.

  values     For a stratified sample, do open/high/low/close/volume/turnover
             agree field by field? Disagreement is not automatically our bug.
             It is a question to put to the exchange, and the exchange's own
             report is the arbiter -- see the evidence note for the answer
             this run produced.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import statistics
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.finmindtrade.com/api/v4/data"
INFO_DATASET = "TaiwanStockInfo"
PRICE_DATASET = "TaiwanStockPrice"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m3"))

from current_build import (  # noqa: E402
    CALENDAR,
    PRICES,
    RESEARCH_DATASET,
    WINDOW,
)

# An audit that asks an independent source whether the warehouse is complete
# has to be pointed at the warehouse in question. These were three literals
# naming the 2025-2026 build, so after the six-year rebuild this would have
# cross-validated the previous generation and found it, correctly, complete.
WAREHOUSE_PRICES = PRICES / "daily_prices_pit.parquet"
LIFECYCLE = CALENDAR / "security_intervals.csv"
DATASET = RESEARCH_DATASET / "research_dataset.parquet"

WINDOW_START, WINDOW_END = WINDOW

# FinMind keeps one TaiwanStockInfo row per market a security has ever
# belonged to. Reading the latest one gives you today's market, not the market
# it was on during the window -- and TaiwanStockPrice will then serve its
# emerging-board quotes under that eventual market. Both halves of that are
# lookahead, so the type is only ever used here to say "not a common share".
NON_COMMON = {
    "ETF", "上櫃ETF", "ETN", "上櫃指數股票型基金(ETF)", "指數投資證券(ETN)",
    "Index", "大盤", "存託憑證", "受益證券", "所有證券",
}

FIELDS = (
    ("open", "open"),
    ("high", "max"),
    ("low", "min"),
    ("close", "close"),
    ("volume", "Trading_Volume"),
    ("turnover", "Trading_money"),
)


def get(url: str, timeout: int = 90) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        if error.code == 402:
            raise SystemExit(f"FinMind rate limit reached: {body[:200]}")
        return {"msg": f"http-{error.code}", "data": [], "body": body[:200]}


def prices(symbol: str) -> list[dict]:
    url = (f"{API}?dataset={PRICE_DATASET}&data_id={symbol}"
           f"&start_date={WINDOW_START}&end_date={WINDOW_END}")
    return get(url).get("data") or []


def read_warehouse() -> tuple[dict[str, list], int]:
    import pyarrow.parquet as pq

    table = pq.read_table(WAREHOUSE_PRICES)
    return {name: table[name].to_pylist() for name in table.schema.names}, table.num_rows


def read_lifecycle() -> list[dict]:
    with LIFECYCLE.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def check_duplicates(warehouse: dict, report: dict) -> None:
    keys = list(zip(warehouse["market"], warehouse["symbol"], warehouse["session_date"]))
    counts = collections.Counter(keys)
    duplicated = {key: n for key, n in counts.items() if n > 1}

    sessions = collections.Counter(key[2] for key in duplicated)
    snapshots: dict[str, set] = collections.defaultdict(set)
    for index, key in enumerate(keys):
        if key in duplicated:
            snapshots[key[2]].add(warehouse["snapshot_id"][index])

    report["duplicates"] = {
        "duplicated_keys": len(duplicated),
        "excess_rows": sum(n - 1 for n in duplicated.values()),
        "sessions": dict(sessions.most_common()),
        "snapshots_per_affected_session": {d: len(v) for d, v in snapshots.items()},
    }
    print(f"  duplicated (market, symbol, session) keys: {len(duplicated)}"
          f" across {len(sessions)} session(s)")


def check_orphans(warehouse: dict, report: dict) -> None:
    lifecycle = {(row["market"], row["symbol"]) for row in read_lifecycle()}
    pairs = list(zip(warehouse["market"], warehouse["symbol"]))
    priced = set(pairs)
    orphans = priced - lifecycle
    per = collections.Counter(pair for pair in pairs if pair in orphans)

    report["orphans"] = {
        "lifecycle_entries": len(lifecycle),
        "priced_securities": len(priced),
        "orphan_securities": len(orphans),
        "orphan_price_rows": sum(per.values()),
        "warehouse_rows": len(pairs),
        "detail": {f"{m}:{s}": n for (m, s), n in per.most_common()},
        "lifecycle_without_any_price": sorted(f"{m}:{s}" for m, s in lifecycle - priced),
    }
    share = sum(per.values()) / len(pairs) * 100 if pairs else 0.0
    print(f"  vendor lifecycle covers neither: {len(orphans)} securities,"
          f" {sum(per.values())} price rows ({share:.2f}% of the warehouse)"
          f" -- exported and refused, not dropped")


def check_universe(warehouse: dict, report: dict) -> None:
    info = get(f"{API}?dataset={INFO_DATASET}").get("data") or []
    latest: dict[str, dict] = {}
    for row in info:
        current = latest.get(row["stock_id"])
        if current is None or row["date"] > current["date"]:
            latest[row["stock_id"]] = row

    ours = set(warehouse["symbol"])
    theirs = set(latest)
    report["universe"] = {
        "finmind_securities": len(latest),
        "our_symbols": len(ours),
        "ours_absent_from_finmind": sorted(ours - theirs),
        "finmind_only": len(theirs - ours),
    }

    suspects = [
        symbol for symbol in sorted(theirs - ours)
        if latest[symbol]["industry_category"] not in NON_COMMON
        and len(symbol) == 4 and symbol.isdigit()
    ]
    print(f"  probing {len(suspects)} FinMind-only common-share symbols"
          f" for activity inside the window", flush=True)

    traded: dict[str, dict] = {}
    for index, symbol in enumerate(suspects, 1):
        rows = prices(symbol)
        if rows:
            dates = sorted(row["date"] for row in rows)
            traded[symbol] = {
                "sessions": len(rows),
                "first": dates[0],
                "last": dates[-1],
                "name": latest[symbol]["stock_name"],
                "category": latest[symbol]["industry_category"],
                # "traded" means quoted somewhere, not listed on the market
                # FinMind names -- see the NON_COMMON comment above.
                "market_claimed": latest[symbol]["type"],
            }
        if index % 25 == 0:
            print(f"    {index}/{len(suspects)}", flush=True)

    report["universe"]["probed"] = len(suspects)
    report["universe"]["traded_in_window_but_absent"] = traded
    print(f"  absent from our universe yet quoted in-window: {len(traded)}")


def build_sample(seed: int, size_hint: int) -> dict[str, str]:
    import pyarrow.parquet as pq

    table = pq.read_table(
        DATASET,
        columns=["market", "symbol", "turnover", "corporate_action_state", "limit_basis"],
    )
    symbol = table["symbol"].to_pylist()
    market = table["market"].to_pylist()
    turnover = table["turnover"].to_pylist()
    action = table["corporate_action_state"].to_pylist()
    basis = table["limit_basis"].to_pylist()

    turnovers = collections.defaultdict(list)
    home: dict[str, str] = {}
    actions: collections.Counter = collections.Counter()
    published: collections.Counter = collections.Counter()
    for index, sym in enumerate(symbol):
        home[sym] = market[index]
        if turnover[index]:
            turnovers[sym].append(turnover[index])
        if action[index] not in ("no-action", "no-coverage"):
            actions[sym] += 1
        if basis[index] == "publisher-exact":
            published[sym] += 1

    median = {s: statistics.median(v) for s, v in turnovers.items() if len(v) >= 60}
    ranked = sorted(median, key=lambda s: -median[s])
    random.seed(seed)
    # Six strata, so the hint divides by six. The floor is one rather than a
    # comfortable minimum because a tiny run is how you smoke-test this
    # without spending an hour's worth of the free tier's 300 requests.
    per_stratum = max(1, size_hint // 6)

    picks: dict[str, str] = {}

    def add(tag: str, symbols) -> None:
        for sym in symbols:
            picks.setdefault(sym, tag)

    add("top-liquidity", ranked[:per_stratum])
    add("bottom-liquidity", ranked[-per_stratum:])
    add("corporate-action", [s for s, _ in actions.most_common(per_stratum)])
    add("publisher-limits", [s for s, _ in published.most_common(per_stratum)])
    tpex = [s for s in ranked if home[s] == "TPEX"]
    add("tpex-random", random.sample(tpex, min(per_stratum, len(tpex))))
    add("all-random", random.sample(ranked, min(per_stratum, len(ranked))))
    return picks


def check_values(warehouse: dict, report: dict, seed: int, size_hint: int) -> None:
    picks = build_sample(seed, size_hint)
    print(f"  fetching {len(picks)} securities"
          f" ({collections.Counter(picks.values()).most_common()})", flush=True)

    theirs: dict[tuple[str, str], dict] = {}
    for index, symbol in enumerate(sorted(picks), 1):
        for row in prices(symbol):
            theirs[(symbol, row["date"])] = row
        if index % 20 == 0:
            print(f"    {index}/{len(picks)}", flush=True)

    ours: dict[tuple[str, str], dict] = {}
    for index, symbol in enumerate(warehouse["symbol"]):
        if symbol not in picks:
            continue
        ours[(symbol, warehouse["session_date"][index])] = {
            name: warehouse[name][index]
            for name in ("market", "open", "high", "low", "close",
                         "volume", "turnover", "ohlc_state")
        }

    shared = set(ours) & set(theirs)
    per_market: dict = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter)
    )
    examples: dict = collections.defaultdict(list)

    comparable = 0
    for key in shared:
        mine = ours[key]
        if mine["ohlc_state"] != "complete":
            continue
        comparable += 1
        market = mine["market"]
        for ours_name, their_name in FIELDS:
            a, b = mine[ours_name], theirs[key][their_name]
            if a is None and b is None:
                continue
            same = (a is not None and b is not None
                    and abs(float(a) - float(b)) <= 1e-6)
            per_market[market][ours_name]["same" if same else "differs"] += 1
            if not same and len(examples[(market, ours_name)]) < 5:
                examples[(market, ours_name)].append(
                    {"symbol": key[0], "session": key[1], "ours": a, "finmind": b}
                )

    # Volume divisibility separates the two markets' definitions without
    # needing the vendor at all: a market whose every figure is a whole
    # multiple of the board lot is not reporting odd-lot trading.
    divisibility = {}
    for market in ("TWSE", "TPEX"):
        vols = [warehouse["volume"][i] for i, m in enumerate(warehouse["market"])
                if m == market and warehouse["volume"][i]]
        if vols:
            whole = sum(1 for v in vols if v % 1000 == 0)
            divisibility[market] = {
                "rows_with_volume": len(vols),
                "whole_board_lots": whole,
                "share": whole / len(vols),
            }

    report["values"] = {
        "sampled_securities": len(picks),
        "strata": dict(collections.Counter(picks.values())),
        "shared_rows": len(shared),
        "ours_only": len(set(ours) - set(theirs)),
        "finmind_only": len(set(theirs) - set(ours)),
        "comparable_rows": comparable,
        "by_market": {
            market: {field: dict(counts) for field, counts in fields.items()}
            for market, fields in per_market.items()
        },
        "examples": {f"{m}:{f}": rows for (m, f), rows in examples.items()},
        "volume_divisibility": divisibility,
    }

    for market in sorted(per_market):
        print(f"  {market}:")
        for ours_name, _ in FIELDS:
            counts = per_market[market][ours_name]
            total = counts["same"] + counts["differs"]
            if total:
                print(f"    {ours_name:9s} {counts['differs']:6d} differ of {total:6d}"
                      f" ({counts['differs'] / total * 100:6.2f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--sample", type=int, default=90,
                        help="rough sample size for the value check; the free"
                             " tier allows 300 requests per hour in total")
    parser.add_argument("--skip", nargs="*", default=[],
                        choices=["universe", "orphans", "duplicates", "values"])
    args = parser.parse_args()

    for path in (WAREHOUSE_PRICES, LIFECYCLE, DATASET):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")

    warehouse, rows = read_warehouse()
    report = {
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "warehouse_rows": rows,
        "inputs": {
            "prices": str(WAREHOUSE_PRICES),
            "lifecycle": str(LIFECYCLE),
            "dataset": str(DATASET),
        },
        "vendor": {
            "name": "FinMind",
            "tier": "free",
            "token": "none",
            "note": "vendor evidence; it cannot define an exchange fact, only"
                    " reveal one we never captured",
        },
    }

    if "duplicates" not in args.skip:
        print("[duplicates]")
        check_duplicates(warehouse, report)
    if "orphans" not in args.skip:
        print("[orphans]")
        check_orphans(warehouse, report)
    if "universe" not in args.skip:
        print("[universe]")
        check_universe(warehouse, report)
    if "values" not in args.skip:
        print("[values]")
        check_values(warehouse, report, args.seed, args.sample)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "finmind_crossvalidation.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                      encoding="utf-8")
    print(f"\nwrote {target}")


if __name__ == "__main__":
    main()
