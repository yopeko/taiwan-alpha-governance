"""Compare what was captured on a trading day against what the warehouse
later reconstructs for it.

The shadow observation contract in executable form.

Why this exists. The whole warehouse rests on one claim -- "this is what was
knowable on date D" -- and that claim has only ever been guaranteed by
construction: lanes carry `announced_at`, the as-of interface fails closed,
tests watch both. Nothing has ever compared it against what was actually
visible on the day.

Zero divergence is the strongest validation this warehouse can get. A non-zero
one is the most valuable thing it can find.

The counter cannot be hurried. Section 4 of the contract: only official
sessions count, days whose capture failed do not count, and no day can be
counted retroactively -- an observation made later is a reconstruction, which
is the thing being compared against rather than a second copy of it. Writing
this on 2026-08-28 means the count is 0 and there is no way for it not to be.

This does not advance M0 section 9's promotion track. Strategy shadow needs a
`validated` candidate; there is none, and comparison 001 returned no winner.
What is observed here is the pipeline, which section 9.2 names as the
precondition for `shadow -> paper` anyway: data arrival, signal timing, and
no-trade reasons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))

from asof import default_warehouse  # noqa: E402

CONTRACT_VERSION = "shadow-observation-v1.0.0"
SCHEMA_ID = "tw-alpha-m9-shadow-observation/1.0.0"
THRESHOLD_TRADING_DAYS = 60
LEDGER_NAME = "shadow_observations.jsonl"
MANIFEST_NAME = "shadow_manifest.json"

# Section 3. A divergence has to land in one of these, and only the last one
# is a defect. The first three already have machinery handling them; the
# fourth means the as-of claim does not hold somewhere.
REASON_CODES = (
    "late-arriving-official-data",
    "revision-of-published-value",
    "capture-failure-on-the-day",
    "unexplained",
)


def digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def divergence(observed: dict[str, Any], rebuilt: dict[str, Any]) -> dict[str, int]:
    """Four numbers, kept apart on purpose.

    Merging them into one score would let a worsening in one hide behind an
    improvement in another -- the same reason the candidate report keeps
    scarcity and sizing refusals separate.
    """

    obs_sessions = observed.get("session_states", {})
    reb_sessions = rebuilt.get("session_states", {})
    session_divergence = sum(
        1
        for market in set(obs_sessions) | set(reb_sessions)
        if obs_sessions.get(market) != reb_sessions.get(market)
    )

    obs_universe = {tuple(k) for k in observed.get("universe", [])}
    reb_universe = {tuple(k) for k in rebuilt.get("universe", [])}

    obs_state = {tuple(k): v for k, v in observed.get("tradability", {}).items()}
    reb_state = {tuple(k): v for k, v in rebuilt.get("tradability", {}).items()}
    shared = set(obs_state) & set(reb_state)

    obs_bars = {tuple(k): v for k, v in observed.get("bars", {}).items()}
    reb_bars = {tuple(k): v for k, v in rebuilt.get("bars", {}).items()}
    shared_bars = set(obs_bars) & set(reb_bars)

    return {
        "session_state_divergence": session_divergence,
        # The one that matters most: it measures survivorship directly. A
        # universe reconstructed later that differs from the one that existed
        # on the day is exactly what a backtest can see and the day could not.
        "universe_divergence": len(obs_universe ^ reb_universe),
        "tradability_divergence": sum(
            1 for key in shared if obs_state[key] != reb_state[key]
        ),
        "price_divergence": sum(
            1 for key in shared_bars if obs_bars[key] != reb_bars[key]
        ),
    }


def reconstruct_snapshot(session: str, decision_as_of: str) -> dict[str, Any]:
    """The warehouse's answer, shaped so it can be compared field by field."""

    warehouse = default_warehouse()
    result = warehouse.reconstruct(
        as_of_session=session, decision_as_of=decision_as_of
    )
    universe = []
    tradability = {}
    for item in result.securities:
        key = [item.market, item.symbol]
        universe.append(key)
        tradability[json.dumps(key, ensure_ascii=False)] = item.tradability_state
    return {
        "dataset_id": result.dataset_id,
        "session_states": dict(result.session_states),
        "universe": universe,
        "tradability": tradability,
        "bars": {},
        "output_hash": result.output_hash,
    }


def counts_towards_threshold(
    observation: dict[str, Any], reasons: tuple[str, ...]
) -> bool:
    """Contract section 4.

    Only official sessions, and never a day whose capture failed. A day nobody
    observed cannot be counted as observed, and counting it would make the
    threshold arrive sooner by having watched less.

    An `unexplained` divergence does not stop the day counting -- counting
    days and fixing defects are different jobs -- but the contract requires
    every one of them closed before the threshold is reached.
    """

    if "capture-failure-on-the-day" in reasons:
        return False
    return any(
        state == "official-open"
        for state in observation.get("session_states", {}).values()
    )


def load_ledger(root: Path) -> list[dict]:
    path = root / LEDGER_NAME
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def observe(
    *,
    root: Path,
    session: str,
    observation_path: Path,
    decision_as_of: str,
    reasons: tuple[str, ...],
) -> dict[str, Any]:
    observed = json.loads(observation_path.read_bytes())
    if observed.get("session_date") != session:
        raise SystemExit(
            f"the observation file is for {observed.get('session_date')}, not "
            f"{session}. Comparing one day's capture against another day's "
            "reconstruction would produce a divergence that means nothing"
        )

    existing = load_ledger(root)
    if any(row["session_date"] == session for row in existing):
        raise SystemExit(
            f"{session} is already in the ledger, which is append-only. A "
            "second observation of the same day would be a reconstruction "
            "competing with the observation, not a correction of it"
        )

    rebuilt = reconstruct_snapshot(session, decision_as_of)
    gaps = divergence(observed, rebuilt)
    total = sum(gaps.values())
    if total and not reasons:
        raise SystemExit(
            f"{session} diverges ({gaps}) and no reason code was given. "
            f"Contract section 3: every non-zero divergence lands in one of "
            f"{list(REASON_CODES)}, and `unexplained` is a defect to be "
            "opened rather than a value to be omitted"
        )
    unknown = [code for code in reasons if code not in REASON_CODES]
    if unknown:
        raise SystemExit(f"unknown reason codes {unknown}; section 3 lists them")

    return {
        "session_date": session,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "observation_source": str(observation_path),
        "observation_sha256": digest(observed),
        "reconstruction_dataset_id": rebuilt["dataset_id"],
        "reconstruction_output_hash": rebuilt["output_hash"],
        "decision_as_of": decision_as_of,
        **gaps,
        "divergence_total": total,
        "divergence_reason_codes": list(reasons),
        "counts_towards_threshold": counts_towards_threshold(observed, reasons),
        "contract_version": CONTRACT_VERSION,
    }


def write_manifest(root: Path) -> dict[str, Any]:
    rows = load_ledger(root)
    counted = [r for r in rows if r["counts_towards_threshold"]]
    manifest = {
        "schema_id": SCHEMA_ID,
        "contract_version": CONTRACT_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "trading_days_observed": len(counted),
        "threshold": THRESHOLD_TRADING_DAYS,
        "first_observation": counted[0]["session_date"] if counted else None,
        "latest_observation": counted[-1]["session_date"] if counted else None,
        "unexplained_open": sum(
            1 for r in rows if "unexplained" in r["divergence_reason_codes"]
        ),
        "reading_note": (
            "Pipeline shadow, not strategy shadow. This does not advance M0 "
            "section 9's promotion track: that needs a validated candidate and "
            "there is none. The count cannot be hurried -- section 4 forbids "
            "counting a day retroactively, because an observation made later "
            "is the reconstruction being compared against."
        ),
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument(
        "--decision-as-of",
        help="defaults to the session itself, which is the strict reading",
    )
    parser.add_argument(
        "--reason",
        action="append",
        default=[],
        choices=REASON_CODES,
        help="required when anything diverges; repeatable",
    )
    args = parser.parse_args(argv)

    args.root.mkdir(parents=True, exist_ok=True)
    row = observe(
        root=args.root,
        session=args.session,
        observation_path=args.observation,
        decision_as_of=args.decision_as_of or args.session,
        reasons=tuple(args.reason),
    )
    with (args.root / LEDGER_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    manifest = write_manifest(args.root)

    print(f"{row['session_date']}  差異合計 {row['divergence_total']}")
    for key in (
        "session_state_divergence",
        "universe_divergence",
        "tradability_divergence",
        "price_divergence",
    ):
        print(f"    {key:<26} {row[key]}")
    print(f"    計入門檻 {row['counts_towards_threshold']}")
    print(
        f"\n已觀察 {manifest['trading_days_observed']} / "
        f"{manifest['threshold']} 個交易日"
        f"　未結案 unexplained {manifest['unexplained_open']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
