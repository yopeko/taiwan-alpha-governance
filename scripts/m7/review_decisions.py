"""The three abandonment criteria, computed rather than remembered.

Contract section 7 fixes three criteria in advance, and proposal 002 section 9
gives the reason: a reading rule chosen after the results are in cannot be told
apart from a rule chosen to make the numbers look good. Writing them down is
half of that; the other half is something that computes them without being
asked to be kind.

WHY THIS PRINTS EVERYTHING BEFORE TWENTY

The criteria only mean something after twenty completed decisions. That is a
statement about when a **verdict** is safe, not about when the numbers may be
looked at. Hiding them until the threshold would leave someone unable to see
which way they are heading at decision nineteen -- and the contract's whole
argument is that process converges faster than profit, which is useless if the
process is not visible while it converges.

So the numbers always print. The verdict does not, until there are twenty.

THE 2x2 IS THE POINT

    thesis held + made money      skill
    thesis held + lost money      right, and something else outweighed it
    thesis failed + lost money    correctly punished
    thesis failed + MADE MONEY    luck

Contract section 6 names the last cell as the main reason the whole thing
exists: nobody goes back and asks whether the reasoning was right after a
profitable trade. It is counted here from two fields the recorder required to
be judged separately, so neither can be derived from the other.

WHAT THIS DOES NOT DO

It does not decide anything. Criterion one firing is a fact about a hit rate,
not an instruction to stop, and the contract says the track "should be
abandoned or substantially modified" -- which is a person's call.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "discretionary-research-v1.2.0"
JOURNAL_NAME = "decision_journal.jsonl"

# Contract section 7. Twenty completed decisions before a verdict, and the
# same twenty proposal 002 section 8 estimated at two to three years.
VERDICT_AFTER = 20


def load(root: Path) -> list[dict[str, Any]]:
    path = root / JOURNAL_NAME
    if not path.is_file():
        raise SystemExit(
            f"no {JOURNAL_NAME} in {root}. An empty review would report a "
            f"clean sheet for a track that has not started"
        )
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise SystemExit(f"{path} is empty")
    return rows


def pair(rows: list[dict[str, Any]]) -> list[tuple[dict, dict]]:
    """Completed decisions only: a thesis with an outcome against it."""

    theses = {r["decision_id"]: r for r in rows if r["stage"] == "thesis"}
    return [
        (theses[r["decision_id"]], r)
        for r in rows
        if r["stage"] == "outcome" and r["decision_id"] in theses
    ]


def two_by_two(pairs: list[tuple[dict, dict]]) -> dict[str, Any]:
    cells = {
        "skill": 0,
        "thesis_held_but_lost": 0,
        "luck": 0,
        "correctly_punished": 0,
        "return_not_recorded": 0,
    }
    for _, outcome in pairs:
        made = (outcome.get("controls") or {}).get("picks_return_pct")
        if made is None:
            # Only reachable for rows written under v1.0.0, when the outcome
            # stage had nowhere to put a return. Counted rather than dropped.
            cells["return_not_recorded"] += 1
            continue
        held = bool(outcome.get("thesis_held"))
        if held:
            cells["skill" if made > 0 else "thesis_held_but_lost"] += 1
        else:
            cells["luck" if made > 0 else "correctly_punished"] += 1
    return cells


def _median(values: list[float]) -> float | None:
    return st.median(values) if values else None


def criteria(pairs: list[tuple[dict, dict]]) -> dict[str, Any]:
    outcomes = [o for _, o in pairs]
    n = len(outcomes)
    held = sum(1 for o in outcomes if o.get("thesis_held"))
    hit_rate = (held / n * 100) if n else None

    percentiles = [
        (o.get("controls") or {}).get("percentile_of_picks") for o in outcomes
    ]
    percentiles = [p for p in percentiles if p is not None]
    percentile_median = _median(percentiles)

    # Criterion three compares like with like: only the decisions that carried
    # a not-bought list contribute, and both sides come from the same decision.
    with_list = [
        (mine, theirs)
        for mine, theirs in (
            (
                (o.get("controls") or {}).get("picks_return_pct"),
                (o.get("controls") or {}).get("considered_not_bought_pct"),
            )
            for o in outcomes
        )
        if mine is not None and theirs is not None
    ]
    bought_median = _median([m for m, _ in with_list])
    not_bought_median = _median([t for _, t in with_list])

    ready = n >= VERDICT_AFTER
    return {
        "completed_decisions": n,
        "decisions_until_verdict": max(0, VERDICT_AFTER - n),
        "verdict_available": ready,
        "one_thesis_hit_rate": {
            "value_pct": hit_rate,
            "threshold": "<= 50 fires",
            "fires": None if not ready or hit_rate is None else hit_rate <= 50,
        },
        "two_median_percentile_vs_random": {
            "value": percentile_median,
            "samples": len(percentiles),
            "threshold": "<= 50 fires",
            "fires": (
                None
                if not ready or percentile_median is None
                else percentile_median <= 50
            ),
        },
        "three_not_bought_beat_bought": {
            "bought_median_pct": bought_median,
            "not_bought_median_pct": not_bought_median,
            # Section 5 allows an empty not-bought list, so this criterion can
            # be short of samples while the other two are complete. Reported
            # rather than folded in, because "did not fire" and "had nothing to
            # fire on" are different facts and look identical in a summary.
            "samples": len(with_list),
            "decisions_without_a_not_bought_list": n - len(with_list),
            "threshold": "not-bought median > bought median fires",
            "fires": (
                None
                if not ready
                or bought_median is None
                or not_bought_median is None
                else not_bought_median > bought_median
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = load(args.root)
    pairs = pair(rows)
    checks = criteria(pairs)
    fired = [
        name
        for name, body in checks.items()
        if isinstance(body, dict) and body.get("fires")
    ]

    report = {
        "contract_version": CONTRACT_VERSION,
        "journal": str(args.root / JOURNAL_NAME),
        "theses": sum(1 for r in rows if r["stage"] == "thesis"),
        "open_theses": sum(1 for r in rows if r["stage"] == "thesis") - len(pairs),
        "two_by_two": two_by_two(pairs),
        "criteria": checks,
        "criteria_fired": fired,
        "reading_note": (
            "Nothing here decides anything. A criterion firing is a fact about "
            "the numbers; contract section 7 says the track should then be "
            "abandoned or substantially modified, and that is a person's call. "
            "Before twenty completed decisions every `fires` is null and the "
            "numbers are still printed -- proposal 002 section 8: process "
            "converges faster than profit, which is worth nothing if it cannot "
            "be watched while it does."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
