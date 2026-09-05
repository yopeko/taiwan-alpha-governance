"""Recompute every stored run's drawdown from its own equity curve.

WHY THIS IS A TOOL AND NOT A RE-RUN

`drawdown_pct` was `ledger.drawdown` -- the fall from the high-water mark **to
the last session** -- and the driver printed it under the heading 最大回撤 from
its first version. The two agree only when a run ends at its worst point, and
the most-cited artefact in this repository does exactly that, which is why it
survived every reading.

Every report carries `equity`: the whole daily NAV series. So the true maximum
is already inside each file and the correction costs one pass, not the hours a
re-run of the same artefacts would take. That distinction is the whole reason
this exists rather than a rerun script -- compare the 2026-09-04 stop-fill fix,
which changed fills and therefore every downstream number, and cost 42 arms.

WHAT IT DOES NOT DO

It does not rewrite the artefacts. A stored report is what the run produced,
and editing it in place would leave no way to tell a corrected file from one
that was always right. The correction is emitted as a table, and the code that
produces new reports has been fixed separately.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_ledger_backtest import max_drawdown_pct  # noqa: E402


def corrections(roots: list[Path]) -> list[dict[str, Any]]:
    """One row per stored run that carries an equity curve.

    A report without `equity` cannot be corrected and is reported as such
    rather than skipped: an artefact this tool cannot check is exactly the one
    a reader would otherwise assume it had.
    """

    found: list[dict[str, Any]] = []
    for root in roots:
        paths = sorted(root.rglob("*.json")) if root.is_dir() else [root]
        for path in paths:
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(report, dict) or "drawdown_pct" not in report:
                continue
            equity = report.get("equity")
            reported = float(report["drawdown_pct"])
            if not equity:
                found.append(
                    {
                        "report": str(path),
                        "reported_drawdown_pct": reported,
                        "true_max_drawdown_pct": None,
                        "understated_by_pp": None,
                        "note": "no equity curve; cannot be corrected without a re-run",
                    }
                )
                continue
            true = max_drawdown_pct(equity)
            found.append(
                {
                    "report": str(path),
                    "strategy": (report.get("strategy") or {}).get("name", ""),
                    "ranking_function": (report.get("strategy") or {}).get(
                        "ranking_function", ""
                    ),
                    "opening_cash": report.get("opening_cash"),
                    "return_pct": report.get("return_pct"),
                    "reported_drawdown_pct": reported,
                    "true_max_drawdown_pct": true,
                    "understated_by_pp": true - reported,
                    "note": "",
                }
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path, nargs="+")
    parser.add_argument("--csv", type=Path)
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="print rows understated by at least this many points",
    )
    args = parser.parse_args(argv)

    rows = corrections(args.roots)
    if not rows:
        raise SystemExit(
            f"no stored runs under {[str(r) for r in args.roots]}. Nothing to "
            f"correct is a result, but an empty sweep is usually a wrong path"
        )
    fixable = [r for r in rows if r["true_max_drawdown_pct"] is not None]
    gaps = [r["understated_by_pp"] for r in fixable]

    print(f"掃描 {len(rows)} 份報告，其中 {len(fixable)} 份帶權益曲線")
    if len(rows) != len(fixable):
        print(f"  **{len(rows) - len(fixable)} 份沒有權益曲線，無法修正**")
    if not gaps:
        return 0
    print()
    print(f"  低估中位 {statistics.median(gaps):+.2f}pp"
          f"   最大 {max(gaps):+.2f}pp"
          f"   低估 > 5pp 的有 {sum(1 for g in gaps if g > 5)} 份")
    print()
    print(f"  {'報告':<52}{'報告值':>9}{'真正最大':>10}{'差':>9}")
    for row in sorted(fixable, key=lambda r: -r["understated_by_pp"]):
        if row["understated_by_pp"] < args.threshold:
            continue
        name = Path(row["report"]).name.replace(".json", "")
        parent = Path(row["report"]).parent.name
        print(
            f"  {parent + '/' + name:<52}"
            f"{row['reported_drawdown_pct']:>9.2f}"
            f"{row['true_max_drawdown_pct']:>10.2f}"
            f"{row['understated_by_pp']:>+9.2f}"
        )

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0])
        with args.csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print()
        print(f"寫入 {args.csv}（{len(rows)} 列）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
