"""Recompute the tw-sepa-screener source-state fingerprint.

Same algorithm as the M2/M3 baselines: tracked + untracked files under
src/tw_sepa_screener, tests, and pyproject.toml; each line is
`relative_path|file_sha256`, sorted, LF-joined, then SHA-256 of the whole.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(r"C:\project\tw-sepa-screener")
TARGETS = ("src/tw_sepa_screener", "tests", "pyproject.toml")

# The Taiwan Core commit every capture in this repository was produced against.
PRODUCER_COMMIT = "fb87f62f8c2c68e2b85982cd102a35fd935bc0a4"

# The current source-state fingerprint, and the single place it is written
# down. It used to be copied into eight scripts, which is the same shape as
# every other drift this repository has had to fix: a value that must move
# together, kept in places that move separately.
#
# History, because a capture's provenance is only readable if the fingerprint
# it recorded can be resolved back to a state:
#
#   d4ef6c0f…  180 files.  M2 release through M3 capture. Every archive dated
#              2026-08-03 to 2026-08-19 records this one.
#   898ef48a…  182 files.  M4 upstreamed: market_rules.py and its smoke test
#              added to Taiwan Core.
#
# Superseding the value here does not rewrite what an existing archive
# recorded. Those are historical facts and stay as captured.
SOURCE_STATE_FINGERPRINT = (
    "898ef48aa2395e8c2d4e27e3e0a30a4d06c0c61ca90409cb32d65af92c585fc2"
)

SOURCE_STATE_HISTORY: tuple[tuple[str, str], ...] = (
    (
        "d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9",
        "M2 release through M3 capture",
    ),
    (
        "898ef48aa2395e8c2d4e27e3e0a30a4d06c0c61ca90409cb32d65af92c585fc2",
        "M4 upstreamed to Taiwan Core",
    ),
)


def producer(commit: str | None = None, fingerprint: str | None = None) -> dict[str, str]:
    """Producer metadata for a capture or a build.

    Both parts stay overridable so an operator reproducing an older run can
    pass the state it actually ran under, instead of silently stamping today's.
    """

    return {
        "name": "tw-sepa-screener",
        "commit": commit or PRODUCER_COMMIT,
        "dirty_fingerprint": fingerprint or SOURCE_STATE_FINGERPRINT,
    }


def current_fingerprint() -> str:
    """Recompute the fingerprint from the Taiwan Core checkout on this machine."""

    lines = []
    for relative in git_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        lines.append(f"{relative}|{hashlib.sha256(path.read_bytes()).hexdigest()}")
    payload = "".join(f"{line}\n" for line in sorted(lines)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *TARGETS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> None:
    lines = []
    total = 0
    for relative in git_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{relative}|{digest}")
        total += 1
    payload = "".join(f"{line}\n" for line in sorted(lines)).encode("utf-8")
    print(
        json.dumps(
            {
                "files": total,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "head": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
