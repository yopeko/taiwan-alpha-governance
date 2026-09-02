"""Append one discretionary decision to the journal, in two stages.

The discretionary research contract in executable form. A profitable position
has four possible sources -- the judgement was right, the market rose, luck, or
some mix -- and without a mechanism those four are indistinguishable. People
record all of them as the first one.

The quantitative side has a sealed hold-out and random controls to measure
that. Judgement faces the identical risk with no backtest, so the controls have
to be built into how a decision is written down rather than into how it is
tested afterwards.

THE ONE THING THAT CANNOT BE RECOVERED

`thesis` must be committed before the order. One instance of buying first and
writing the reason afterwards turns the whole apparatus into rationalisation,
and it leaves no trace. Everything else here can be repaired later; this
cannot, which is why the clean-tree check exists.

Nothing here blocks a decision. It only makes having made one survive.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

CONTRACT_VERSION = "discretionary-research-v1.0.0"
JOURNAL_NAME = "decision_journal.jsonl"
STAGES = ("thesis", "outcome")

# Contract section 4. "I changed my mind" is not an exit reason; it is a new
# decision, and it needs its own thesis.
EXIT_REASONS = (
    "thesis-falsified",
    "thesis-achieved",
    "horizon-reached",
    "risk-rule",
)

# Contract section 2. A falsifier has to be an observable event about the
# business, not a price. "Down 20% means I was wrong" is a stop loss; it says
# nothing about whether the understanding was wrong.
#
# Narrow on purpose, and the first version was not. It listed "%", "跌" and
# "price", which rejected the contract's own example falsifiers -- "gross
# margin below 35% for two quarters" contains a percent sign, and average
# selling price is a business metric, not a stop.
#
# A guard that refuses most legitimate input trains people to work around it,
# and the contract says a guard that can be bypassed is not a guard. So this
# catches only wording that is unambiguously about the security's price, and
# it cannot catch a determined author. That limit is the design, not a defect:
# the contract carries the rule, this carries the obvious cases.
PRICE_WORDS = (
    "股價", "收盤價", "停損", "跌幅", "漲幅",
    "stop loss", "stop-loss", "drawdown", "share price",
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def require_clean_tree() -> str:
    """Contract section 8, and the reason it is the one guard that matters.

    `code_commit` has to name the state the thesis was written in. A dirty
    tree means it names something else, and the whole point of the timestamp
    is that it precedes the order.
    """

    if git("status", "--porcelain"):
        raise SystemExit(
            "the working tree has uncommitted changes, so `code_commit` would "
            "name something other than the state this thesis was written in. "
            "Commit first. This is the one check that cannot be repaired "
            "afterwards -- see the contract section 8"
        )
    return git("rev-parse", "HEAD")


def load(root: Path) -> list[dict]:
    path = root / JOURNAL_NAME
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def reject_price_falsifier(falsifier: str) -> None:
    hits = [w for w in PRICE_WORDS if w.lower() in falsifier.lower()]
    if hits:
        raise SystemExit(
            f"the falsifier reads like a price threshold ({hits}). A stop loss "
            f"answers 'how much am I willing to lose'; a falsifier answers "
            f"'what would show my understanding of this business was wrong'. "
            f"Both are required and they are different fields.\n\n"
            f"Rewrite it as an observable event -- a margin, an order, a "
            f"customer, a schedule. Contract section 2 says to rewrite rather "
            f"than bypass, because a guard that can be bypassed is not a guard."
        )


def build_thesis(existing: list[dict], args, commit: str) -> dict[str, Any]:
    if any(
        r["decision_id"] == args.decision_id and r["stage"] == "thesis"
        for r in existing
    ):
        raise SystemExit(
            f"{args.decision_id} already has a thesis. The journal is "
            f"append-only: a correction opens a new decision_id and names the "
            f"one it corrects, so that the first version stays readable"
        )
    reject_price_falsifier(args.falsifier)
    return {
        "decision_id": args.decision_id,
        "stage": "thesis",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "contract_version": CONTRACT_VERSION,
        "market": args.market,
        "symbol": args.symbol,
        "thesis": args.thesis,
        "falsifier": args.falsifier,
        "horizon_sessions": args.horizon_sessions,
        "target": args.target,
        "exit_rules": list(EXIT_REASONS),
        # Contract section 3.2: the population for the random baskets is the
        # universe **on the day of the purchase**. Recorded now, with a hash,
        # because choosing it after the exit would be choosing the control.
        "universe_snapshot": args.universe_snapshot,
        # Contract section 5. An empty list is allowed; a missing field is not.
        # "I looked at nothing else" and "I forgot to record it" read the same
        # in a summary, and only one of them is true.
        "considered_not_bought": json.loads(args.considered_not_bought),
        "corrects": args.corrects or None,
    }


def build_outcome(existing: list[dict], args, commit: str) -> dict[str, Any]:
    thesis = next(
        (
            r
            for r in existing
            if r["decision_id"] == args.decision_id and r["stage"] == "thesis"
        ),
        None,
    )
    if thesis is None:
        raise SystemExit(
            f"no thesis for {args.decision_id}. An outcome without one is a "
            f"result with no claim attached to it, which is the shape this "
            f"contract exists to prevent"
        )
    if any(
        r["decision_id"] == args.decision_id and r["stage"] == "outcome"
        for r in existing
    ):
        raise SystemExit(f"{args.decision_id} already has an outcome")
    if args.exit_reason not in EXIT_REASONS:
        raise SystemExit(
            f"{args.exit_reason!r} is not one of {list(EXIT_REASONS)}. "
            f"'I changed my mind' is not an exit reason -- it is a new "
            f"decision, and it needs its own thesis. Contract section 4"
        )
    return {
        "decision_id": args.decision_id,
        "stage": "outcome",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "contract_version": CONTRACT_VERSION,
        "entry_session": args.entry_session,
        "exit_session": args.exit_session,
        "exit_reason": args.exit_reason,
        # Two fields, and neither may be derived from the other. Contract
        # section 6: the cell that matters is "thesis wrong, made money", and
        # it only exists if these are judged separately.
        "thesis_held": args.thesis_held,
        "thesis_evidence": args.thesis_evidence,
        "falsifier_fired": args.falsifier_fired,
    }


def summarise(rows: list[dict]) -> dict[str, Any]:
    outcomes = [r for r in rows if r["stage"] == "outcome"]
    held = [r for r in outcomes if r["thesis_held"]]
    return {
        "theses": sum(1 for r in rows if r["stage"] == "thesis"),
        "outcomes": len(outcomes),
        "thesis_hit_rate_pct": (
            None if not outcomes else len(held) / len(outcomes) * 100
        ),
        # Contract section 7: at least twenty completed decisions before the
        # abandonment criteria mean anything. Printed so the count is never a
        # thing someone has to remember.
        "outcomes_until_criteria_apply": max(0, 20 - len(outcomes)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--decision-id", required=True)

    parser.add_argument("--market")
    parser.add_argument("--symbol")
    parser.add_argument("--thesis")
    parser.add_argument("--falsifier")
    parser.add_argument("--horizon-sessions", type=int)
    parser.add_argument("--target")
    parser.add_argument("--universe-snapshot")
    parser.add_argument("--considered-not-bought", help="JSON array, [] allowed")
    parser.add_argument("--corrects", default="")

    parser.add_argument("--entry-session")
    parser.add_argument("--exit-session")
    parser.add_argument("--exit-reason")
    parser.add_argument("--thesis-held", action="store_true")
    parser.add_argument("--thesis-not-held", action="store_true")
    parser.add_argument("--thesis-evidence")
    parser.add_argument("--falsifier-fired", action="store_true")
    args = parser.parse_args(argv)

    if args.stage == "thesis":
        missing = [
            name
            for name in (
                "market", "symbol", "thesis", "falsifier",
                "horizon_sessions", "target", "universe_snapshot",
                "considered_not_bought",
            )
            if getattr(args, name) is None
        ]
        if missing:
            raise SystemExit(f"a thesis needs {missing}")
    else:
        if args.thesis_held == args.thesis_not_held:
            raise SystemExit(
                "pass exactly one of --thesis-held / --thesis-not-held. It is "
                "a judgement someone has to make, and defaulting it would let "
                "the profitable-but-wrong case go unrecorded, which is the one "
                "the contract is for"
            )
        args.thesis_held = bool(args.thesis_held)
        for name in ("entry_session", "exit_session", "exit_reason", "thesis_evidence"):
            if getattr(args, name) is None:
                raise SystemExit(f"an outcome needs --{name.replace('_', '-')}")

    commit = require_clean_tree()
    args.root.mkdir(parents=True, exist_ok=True)
    existing = load(args.root)
    row = (
        build_thesis(existing, args, commit)
        if args.stage == "thesis"
        else build_outcome(existing, args, commit)
    )

    with (args.root / JOURNAL_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
    print()
    print(json.dumps(summarise(existing + [row]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
