"""Can FinMind supply the minute bars, and would they be usable if it could?

The 2026-08-21 cross-validation already settled most of what matters about
this vendor, and this probe deliberately does not re-ask any of it:

    Free tier is 300 requests an hour and needs no token.
    A whole-market single-day batch is refused with `Your level is free`.
    Daily prices take a date range, so one request covers the window.
    `TaiwanStockKBar` is a Sponsor-tier dataset -- **and was not tried**.
    FinMind held 793 securities the warehouse lacked, delisted ones among
    them, and zero the warehouse had and it did not.
    TWSE prices and volumes agreed on all 16,035 comparable rows.
    TPEx volumes disagreed on 91.94%, and the exchange's own report said
    FinMind was wrong.

Three questions are left, and only these are asked here.

ONE. IS THE MINUTE DATASET REACHABLE WITHOUT PAYING

"Sponsor tier" is what the documentation said in August. What the endpoint
answers is a different claim, and the difference decides whether the next step
costs money.

TWO. DOES A DELISTED SECURITY HAVE MINUTE HISTORY

The daily coverage passed this test -- 3202, which traded 57 sessions inside
the window and then delisted, was found through this vendor and is the reason
the research dataset stopped silently dropping it. **Daily coverage is not
evidence about minute coverage.** Most intraday vendors carry only what still
trades, and bolting that onto this warehouse would put back the survivorship
bias the lifecycle lane exists to remove.

THREE. WHAT SHAPE AND WHICH FIELDS

Whether a response carries volume at all, and whether one request can span a
useful date range, sets the request budget. The arithmetic is 11x apart
between "one call per symbol-year" and "one call per symbol-month".

WHAT THIS DOES NOT DO

It buys nothing, stores nothing in any warehouse, and settles no question
about accuracy. Volume accuracy needs an official arbiter, and the exchange
does not publish minute volume in a form this project holds -- so a minute
series that disagrees with the warehouse's daily total is a finding, and one
that agrees is not proof of anything finer.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API = "https://api.finmindtrade.com/api/v4/data"

# Named so a reader can see exactly which datasets were touched.
DAILY = "TaiwanStockPrice"
MINUTE = "TaiwanStockKBar"

# 3202 樺晟 delisted inside the window after 57 sessions and -40.1%; it is the
# security the 2026-08-21 audit recovered, so it is the right one to ask about
# again. 2330 is the liquid control: if the minute dataset is unreachable even
# for it, the refusal is about the tier and not about the security.
DELISTED_CASE = "3202"
LIQUID_CONTROL = "2330"

# 300 requests an hour is one every twelve seconds. This probe makes single
# figures of requests, so the floor costs nothing and removes the question.
INTERVAL_SECONDS = 12.0


def get(url: str, timeout: int = 60) -> dict[str, Any]:
    """Every outcome is data. Nothing here raises on a refusal.

    A tier refusal is the answer to question one, so turning it into an
    exception would throw away the finding.
    """

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return {"http": response.status, "body": json.loads(response.read())}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        return {"http": error.code, "text": raw[:400]}
    except Exception as exc:  # noqa: BLE001
        return {"http": None, "error": f"{type(exc).__name__}: {exc}"[:300]}


def summarise(answer: dict[str, Any]) -> dict[str, Any]:
    body = answer.get("body")
    if not isinstance(body, dict):
        return {
            "http": answer.get("http"),
            "outcome": "refused" if answer.get("http") else "error",
            "detail": (answer.get("text") or answer.get("error") or "")[:220],
        }
    rows = body.get("data") or []
    out: dict[str, Any] = {
        "http": answer.get("http"),
        "msg": str(body.get("msg") or "")[:160],
        "rows": len(rows),
        "outcome": "data" if rows else "empty",
    }
    if rows:
        out["fields"] = sorted(rows[0])
        out["first"] = rows[0]
        out["last"] = rows[-1]
        stamps = [str(r.get("date") or "") for r in rows if r.get("date")]
        if stamps:
            out["date_span"] = [min(stamps), max(stamps)]
    return out


def run(session: str, span_start: str, span_end: str) -> dict[str, Any]:
    asks: list[tuple[str, str]] = [
        # Question one, on a liquid name so a refusal is about the tier.
        (
            f"minute/{LIQUID_CONTROL}/one-day",
            f"{API}?dataset={MINUTE}&data_id={LIQUID_CONTROL}"
            f"&start_date={session}&end_date={session}",
        ),
        # Question two.
        (
            f"minute/{DELISTED_CASE}/one-day",
            f"{API}?dataset={MINUTE}&data_id={DELISTED_CASE}"
            f"&start_date={session}&end_date={session}",
        ),
        # Question three: does one request span a range, and how far.
        (
            f"minute/{LIQUID_CONTROL}/range",
            f"{API}?dataset={MINUTE}&data_id={LIQUID_CONTROL}"
            f"&start_date={span_start}&end_date={span_end}",
        ),
        # The control that says the account and the endpoint are working at
        # all. Without it, a refusal above cannot be told from a dead network.
        (
            f"daily/{DELISTED_CASE}/window",
            f"{API}?dataset={DAILY}&data_id={DELISTED_CASE}"
            f"&start_date=2025-01-01&end_date=2025-12-31",
        ),
    ]

    results: dict[str, Any] = {}
    for index, (label, url) in enumerate(asks):
        if index:
            time.sleep(INTERVAL_SECONDS)
        answer = summarise(get(url))
        answer["dataset"] = MINUTE if label.startswith("minute/") else DAILY
        results[label] = answer
        print(
            f"  {label:34s} http={answer.get('http')} "
            f"{answer['outcome']:8s} rows={answer.get('rows')}",
            flush=True,
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session",
        required=True,
        help="one trading session inside 3202's listed period, so question "
        "two is asked about a day the security actually traded",
    )
    parser.add_argument("--span-start", required=True)
    parser.add_argument("--span-end", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    out = args.out.resolve()
    if out.is_relative_to(Path(__file__).resolve().parents[2]):
        raise SystemExit(
            f"{out} is inside the repository. Probe output goes to an "
            f"isolated root, same as every capture"
        )

    print(f"4 requests at {INTERVAL_SECONDS}s")
    report = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "api": API,
        "tier": "free, no token",
        "interval_seconds": INTERVAL_SECONDS,
        "session_probed": args.session,
        "range_probed": [args.span_start, args.span_end],
        "results": run(args.session, args.span_start, args.span_end),
        "reading_note": (
            "A refusal on the minute dataset alongside data on the daily one "
            "means the tier, not the network. Minute rows for a delisted "
            "security would answer the survivorship question for this vendor; "
            "their absence would not settle it either way unless the liquid "
            "control returned rows for the same session."
        ),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\n寫入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
