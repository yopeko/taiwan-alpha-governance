"""Append one backtest run to the development trial ledger.

The trial ledger contract in executable form, written to close an asymmetry:
this project counts seal openings carefully -- append-only ledger, guard
tests, three refusals -- and the count is 0. Nothing counted the thing that
was actually accumulating, and by 2026-08-28 that was at least nine
configurations, four of them a slot sweep that a decision was then taken from.

Nine unrecorded trials are worse than one recorded opening.

The distinction the ledger turns on is not "was this a real candidate" but
"did its result change anything". A run that was reported and never selected
on costs nothing in multiplicity; a run after which someone said "ten slots
then" costs one. Contract section 2.

Nothing here blocks a trial. It only makes having run one survive.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

CONTRACT_VERSION = "trial-ledger-v1.0.0"
LEDGER_NAME = "development_trials.jsonl"
PURPOSES = ("probe", "candidate", "sensitivity", "parameter-search")
RECORD_BASES = ("contemporaneous", "reconstructed")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def require_clean_tree() -> str:
    """`code_commit` has to point at the code that ran.

    Same rule as the nested-validation producer, for the same reason: a dirty
    tree means the commit names something other than what executed.
    """

    if git("status", "--porcelain"):
        raise SystemExit(
            "the working tree has uncommitted changes, so `code_commit` would "
            "name code other than what ran. Commit first, or pass "
            "--record-basis reconstructed if you are backfilling history"
        )
    return git("rev-parse", "HEAD")


def load(root: Path) -> list[dict]:
    path = root / LEDGER_NAME
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def config_key(config: dict[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False, sort_keys=True)


def build_row(
    *,
    existing: list[dict],
    config: dict[str, Any],
    dataset: str,
    purpose: str,
    influenced: bool,
    choice: str,
    result_pointer: str,
    basis: str,
    commit: str,
    rerun_reason: str,
) -> dict[str, Any]:
    if purpose not in PURPOSES:
        raise SystemExit(f"purpose must be one of {list(PURPOSES)}")
    if basis not in RECORD_BASES:
        raise SystemExit(f"record_basis must be one of {list(RECORD_BASES)}")
    if influenced and not choice:
        raise SystemExit(
            "influenced_a_choice is true but choice_made is empty. Saying a "
            "run changed something without saying what it changed is not "
            "saying anything -- contract section 4"
        )

    key = config_key(config)
    duplicate = [r for r in existing if config_key(r["config"]) == key]
    if duplicate and not rerun_reason:
        raise SystemExit(
            f"this configuration is already trial #{duplicate[0]['trial_number']}. "
            "Re-running is legitimate -- a fixed bug should be re-run -- but it "
            "needs --rerun-reason, or the count turns one trial into two or two "
            "into one"
        )

    return {
        "trial_number": len(existing) + 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "dataset": dataset,
        "code_commit": commit,
        "purpose": purpose,
        "influenced_a_choice": influenced,
        "choice_made": choice,
        "result_pointer": result_pointer or "未保存",
        "record_basis": basis,
        "rerun_reason": rerun_reason,
        "contract_version": CONTRACT_VERSION,
    }


def summarise(rows: list[dict]) -> dict[str, Any]:
    selecting = [r for r in rows if r["influenced_a_choice"]]
    return {
        "trials_total": len(rows),
        # The number that matters. Runs whose results were reported jointly
        # and never selected among do not inflate anything; runs a decision
        # was taken from do.
        "selection_budget_spent": len(selecting),
        "reconstructed": sum(1 for r in rows if r["record_basis"] == "reconstructed"),
        "contemporaneous": sum(
            1 for r in rows if r["record_basis"] == "contemporaneous"
        ),
        "by_purpose": {
            p: sum(1 for r in rows if r["purpose"] == p) for p in PURPOSES
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", required=True, help="JSON object")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--purpose", choices=PURPOSES, required=True)
    parser.add_argument("--influenced-a-choice", action="store_true")
    parser.add_argument("--choice-made", default="")
    parser.add_argument("--result", default="")
    parser.add_argument(
        "--record-basis", choices=RECORD_BASES, default="contemporaneous"
    )
    parser.add_argument("--rerun-reason", default="")
    parser.add_argument("--commit", default="", help="backfill only")
    args = parser.parse_args(argv)

    commit = args.commit
    if not commit:
        if args.record_basis == "contemporaneous":
            commit = require_clean_tree()
        else:
            commit = "unknown-backfilled"

    args.root.mkdir(parents=True, exist_ok=True)
    existing = load(args.root)
    row = build_row(
        existing=existing,
        config=json.loads(args.config),
        dataset=args.dataset,
        purpose=args.purpose,
        influenced=args.influenced_a_choice,
        choice=args.choice_made,
        result_pointer=args.result,
        basis=args.record_basis,
        commit=commit,
        rerun_reason=args.rerun_reason,
    )
    with (args.root / LEDGER_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    stats = summarise(load(args.root))
    print(f"試驗 #{row['trial_number']}  {row['purpose']}  {row['record_basis']}")
    print(f"  影響選擇 {row['influenced_a_choice']}  {row['choice_made']}")
    print(
        f"\n累計 {stats['trials_total']} 次試驗，其中 "
        f"**選擇預算已用 {stats['selection_budget_spent']}**"
    )
    print(
        f"  當時記錄 {stats['contemporaneous']}　事後重建 {stats['reconstructed']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
