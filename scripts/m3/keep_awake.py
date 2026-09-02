"""Run a command while telling Windows the system is in use.

M3.17 records why this exists. The six-year `build_staging` was killed by
system sleep after about six minutes, having produced 6,025 parse manifests
and no output; stdout and stderr went with the process, so it looked like a
silent failure. Two days earlier the TPEx capture died at 655 of 4,310 for the
same reason.

The difference between those two matters here. A capture resumes; a staging
build requires an empty directory and starts over. And the TPEx capture this
was written for **cannot** resume usefully -- it skips symbol-years it already
holds, so a run killed halfway leaves a lane that will never be completed by
running it again.

WHAT THIS DOES AND DOES NOT DO

`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` is a request
held by this thread for as long as the process lives. It is **not a settings
change**: nothing on the machine is reconfigured, the state lapses when the
process exits, and the display is deliberately left free to sleep --
`ES_DISPLAY_REQUIRED` is not set.

If a run still dies to sleep after this, the machine is on modern standby and
the power configuration has to be changed by a person. **This script does not
do that**, and it says so rather than escalating on its own.
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
from datetime import datetime, timezone

# winbase.h
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def request_awake() -> bool:
    """Hold the request. False when the call is unavailable or refused."""

    if not sys.platform.startswith("win"):
        return False
    try:
        previous = ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        )
    except Exception:  # noqa: BLE001
        return False
    # Zero means the call failed. Reported rather than assumed, because a
    # request that silently did nothing is how the first two runs died.
    return previous != 0


def release() -> None:
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label", default="", help="printed with the start and end lines"
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="the command to run, after --"
    )
    args = parser.parse_args(argv)

    command = [c for c in args.command if c != "--"]
    if not command:
        raise SystemExit("nothing to run: pass the command after --")

    held = request_awake()
    started = datetime.now(timezone.utc)
    label = args.label or command[0]
    print(f"[keep-awake] {label}")
    print(f"[keep-awake] system-required held: {held}")
    if not held:
        # Not fatal. A long run on a machine that will not sleep is fine, and
        # refusing to start would trade a possible failure for a certain one.
        print(
            "[keep-awake] the request was refused or is unavailable on this "
            "platform. The run continues; if it dies partway, sleep is the "
            "first thing to check and the power configuration is a person's "
            "decision, not this script's."
        )
    print(f"[keep-awake] started {started.isoformat()}")

    try:
        result = subprocess.run(command)
    finally:
        release()
        elapsed = datetime.now(timezone.utc) - started
        print(f"[keep-awake] released after {elapsed}")

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
