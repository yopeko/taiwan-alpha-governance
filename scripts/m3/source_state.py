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
