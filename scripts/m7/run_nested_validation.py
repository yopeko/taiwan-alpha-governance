"""Evaluate one candidate on the development segment and on the sealed one.

The nested validation contract's section 4 in executable form.

Running this spends a seal opening. That is not a figure of speech: the sealed
segment is 382 sessions that exist to answer one question about one candidate,
and every evaluation makes the next one worth slightly less. The opening
ledger exists because that cost is invisible otherwise -- nothing about the
tenth opening looks different from the first when you are reading its report.

So this refuses to run unless three things hold:

  the candidate is committed, and the commit predates now;
  the working tree is clean, so the committed candidate is the one that runs;
  `--i-am-spending-a-seal-opening` is passed.

The third is a speed bump, not a security measure. It exists so that opening
the seal is never something that happened while you were doing something else.

Sealed evaluation reads the *full* dataset with `--first-trading-session` set
to the seal boundary. Contract section 1: what is sealed is outcomes, not
price history. A 252-session momentum score for 2025-01-02 reads 2024 prices,
which were known on the day.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts" / "m6"))

from split_sealed_dataset import SEAL_FROM, SPLIT_VERSION  # noqa: E402

from run_ledger_backtest import (  # noqa: E402
    PARTICIPATION_RATE,
    RANKINGS,
    UNIVERSES,
    BrokerTerms,
    realised_costs,
    reference_scale_nav,
    run,
)

sys.path.insert(0, str(REPO))

from m5.ledger import POLICY_INITIAL_CAPITAL  # noqa: E402

SCHEMA_ID = "tw-alpha-m7-nested-validation/1.0.0"
CONTRACT_VERSION = "nested-validation-v1.0.0"

SCALES = ("m0-execution", "reference-measurement")
PARTICIPATION_RATES = (Decimal("0.01"), Decimal("0.001"))
LEDGER_NAME = "sealed_evaluation_ledger.jsonl"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def candidate_provenance() -> dict[str, str]:
    """The commit the candidate is running from, and proof it is unmodified.

    A dirty tree means the code being evaluated is not the code that was
    committed, so the commit timestamp proves nothing about what ran. M6.3
    had exactly this gap in a weaker form -- the probe ran before its commit
    and the prior claim rests on a self-report.
    """

    if git("status", "--porcelain"):
        raise SystemExit(
            "the working tree has uncommitted changes. A seal opening records "
            "`candidate_commit` as evidence that the candidate predates the "
            "evaluation, and that evidence is worthless if the code that ran "
            "was not the code in the commit. Commit first."
        )
    return {
        "candidate_commit": git("rev-parse", "HEAD"),
        "candidate_commit_at": git("log", "-1", "--format=%cI"),
    }


def segment_rows(
    result: dict[str, Any], *, candidate: dict[str, str], segment: str, scale: str, rate: Decimal
) -> dict[str, Any]:
    cost, turnover = realised_costs(result)
    return {
        "candidate_id": candidate["candidate_id"],
        "ranking_function": candidate["ranking"],
        "universe": candidate["universe"],
        "segment": segment,
        "scale": scale,
        "participation_rate": float(rate),
        "sessions": int(result["sessions"]),
        "return_pct": float(result["return_pct"]),
        "drawdown_pct": float(result["drawdown_pct"]),
        "completed_trades": int(result["completed_trades"]),
        "cost_total": float(cost),
        "cost_share_of_turnover": float(cost / turnover) if turnover else 0.0,
        "selection_logic_measured": bool(candidate["ranking"])
        and result["rank_violations_scarcity"] == 0,
    }


def next_opening_number(ledger: Path) -> int:
    if not ledger.is_file():
        return 1
    return sum(1 for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()) + 1


def evaluate(
    *,
    development: Path,
    full: Path,
    candidate: dict[str, str],
    ledger: Path,
    lookback: int,
    stop_pct: Decimal,
    max_holding_sessions: int,
) -> tuple[list[dict], dict]:
    provenance = candidate_provenance()
    opening = next_opening_number(ledger)

    scales = {
        "m0-execution": POLICY_INITIAL_CAPITAL,
        "reference-measurement": reference_scale_nav(),
    }

    rows: list[dict] = []
    hashes: dict[str, str] = {}
    for segment, dataset, first_session in (
        ("development", development, None),
        ("sealed", full, SEAL_FROM),
    ):
        for scale, cash in scales.items():
            for rate in PARTICIPATION_RATES:
                result = run(
                    dataset,
                    opening_cash=cash,
                    lookback=lookback,
                    stop_pct=stop_pct,
                    max_holding_sessions=max_holding_sessions,
                    ranking_name=candidate["ranking"],
                    universe=candidate["universe"],
                    participation_rate=rate,
                    first_trading_session=first_session,
                )
                hashes[segment] = result["dataset_sha256"]
                rows.append(
                    segment_rows(
                        result,
                        candidate=candidate,
                        segment=segment,
                        scale=scale,
                        rate=rate,
                    )
                )

    # The number the contract's section 5 forbids reporting alone.
    degradation = {}
    for scale in SCALES:
        for rate in PARTICIPATION_RATES:
            def pick(segment: str) -> float:
                return next(
                    r["return_pct"]
                    for r in rows
                    if r["segment"] == segment
                    and r["scale"] == scale
                    and r["participation_rate"] == float(rate)
                )

            degradation[f"{scale}|{rate}"] = pick("sealed") - pick("development")

    manifest = {
        "schema_id": SCHEMA_ID,
        "contract_version": CONTRACT_VERSION,
        "split_version": SPLIT_VERSION,
        "seal_from": SEAL_FROM,
        "seal_opening_number": opening,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        **provenance,
        "candidate": candidate,
        "development_dataset_sha256": hashes["development"],
        "sealed_source_dataset_sha256": hashes["sealed"],
        "scales": list(SCALES),
        "participation_rates": [float(r) for r in PARTICIPATION_RATES],
        "degradation": degradation,
        "broker_terms": {
            "evidence_state": BrokerTerms().evidence_state,
            "source": BrokerTerms().source,
        },
        "reading_note": (
            "Nested validation contract section 5: the sealed figures may not "
            "be read without the development ones beside them -- a candidate "
            "that was mediocre in both looks the same as one that collapsed. "
            "Section 3.3: this candidate may not now be adjusted; a parameter "
            "change after an opening makes a new candidate. ADR-0002 decision "
            "1 still binds on m0-execution returns."
        ),
    }
    return rows, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument(
        "--full",
        type=Path,
        required=True,
        help="the unsplit dataset. Sealed evaluation warms up on pre-seal bars",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ranking", choices=sorted(RANKINGS), required=True)
    parser.add_argument("--universe", choices=UNIVERSES, default="all")
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--stop-pct", type=Decimal, default=Decimal("0.08"))
    parser.add_argument("--max-holding-sessions", type=int, default=20)
    parser.add_argument(
        "--i-am-spending-a-seal-opening",
        action="store_true",
        help=(
            "required. The sealed segment is finite and does not regenerate; "
            "this flag exists so that spending some of it is never incidental"
        ),
    )
    args = parser.parse_args(argv)

    if not args.i_am_spending_a_seal_opening:
        raise SystemExit(
            "refusing to run without --i-am-spending-a-seal-opening.\n\n"
            "This evaluates a candidate against the 382 sealed sessions. They "
            "are finite, they do not regenerate, and every opening makes the "
            "next one worth slightly less. If you only want development-segment "
            "figures, use scripts/m6/run_ledger_backtest.py against the "
            "development split instead -- that spends nothing."
        )

    candidate = {
        "candidate_id": f"{args.ranking or 'arrival-order'}|{args.universe}"
        f"|lookback={args.lookback}|stop={args.stop_pct}"
        f"|hold={args.max_holding_sessions}",
        "ranking": args.ranking,
        "universe": args.universe,
    }

    ledger = args.out.parent / LEDGER_NAME
    rows, manifest = evaluate(
        development=args.development,
        full=args.full,
        candidate=candidate,
        ledger=ledger,
        lookback=args.lookback,
        stop_pct=args.stop_pct,
        max_holding_sessions=args.max_holding_sessions,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), args.out / "nested_validation.parquet")
    (args.out / "validation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Append-only, and appended last: a run that failed before producing an
    # artifact has not spent an opening, and recording one would overstate the
    # cost as surely as recording none would understate it.
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "evaluated_at": manifest["evaluated_at"],
                    "seal_opening_number": manifest["seal_opening_number"],
                    "candidate_id": candidate["candidate_id"],
                    "candidate_commit": manifest["candidate_commit"],
                    "candidate_commit_at": manifest["candidate_commit_at"],
                    "split_version": SPLIT_VERSION,
                    "artifact_root": str(args.out),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )

    print(f"封存區開封 #{manifest['seal_opening_number']}  候選 {candidate['candidate_id']}")
    for scale in SCALES:
        for rate in PARTICIPATION_RATES:
            print(f"\n{scale}  /  參與率 {rate}")
            for segment in ("development", "sealed"):
                row = next(
                    r
                    for r in rows
                    if r["segment"] == segment
                    and r["scale"] == scale
                    and r["participation_rate"] == float(rate)
                )
                print(
                    f"    {segment:<12} 報酬 {row['return_pct']:>8.2f}%"
                    f"  回撤 {row['drawdown_pct']:>6.2f}%"
                    f"  成交 {row['completed_trades']:>5}"
                    f"  場次 {row['sessions']:>5}"
                )
            print(f"    退化 {manifest['degradation'][f'{scale}|{rate}']:+.2f} 點")
    print(f"\n寫入 {args.out}")
    print(f"開封記錄追加至 {ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
