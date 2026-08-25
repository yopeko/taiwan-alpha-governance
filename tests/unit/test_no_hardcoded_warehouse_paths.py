"""No module may name a warehouse directory except the one that defines them.

Three incidents, one shape, and the third was found by the fix for the second.

1. Five invariant test files each hardcoded a scratch path. The six-year
   rebuild landed elsewhere and all five went on reading the 2025-2026 build:
   422 passed, the count unchanged, nothing checked.

2. `tests/warehouse.py` was written to fix that.

3. `validate_m3_7.py` had the same four constants. It is not a test file, so
   it was not looked at. It rebuilt from `tw-alpha-m3-staging-10`, compared
   828,736 price rows against themselves, and reported `verdict: passed` for
   a warehouse nobody had asked about -- while the six-year table holds
   3,316,101 rows.

What makes this worth a rule rather than three fixes: the failure is silent
and its output is green. Nothing is red, nothing is skipped, and the artifact
under test is simply not the artifact anyone meant.

Generations are additive by design. Old roots stay on disk so old reports stay
re-readable, which is precisely why a stale pointer keeps working and keeps
being believed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SINGLE_SOURCE = REPO / "scripts" / "m3" / "current_build.py"

# A warehouse directory: the scratch base plus a build-shaped name. Written as
# a pattern rather than a list of the roots that exist today, so a path
# invented tomorrow is caught by the same rule.
WAREHOUSE_PATH = re.compile(
    r"tw-alpha-m3-(?:staging|pit)[a-z-]*-\d+|tw-alpha-m6-dataset-\d+"
)

SEARCH_ROOTS = (REPO / "scripts", REPO / "tests", REPO / "m4", REPO / "m5")


def python_files() -> list[Path]:
    found: list[Path] = []
    for root in SEARCH_ROOTS:
        if root.is_dir():
            found.extend(
                p
                for p in root.rglob("*.py")
                # This file names the roots in its own docstring while
                # explaining which ones went wrong, so it is swept out of its
                # own rule rather than made to talk around them.
                if "__pycache__" not in p.parts
                and p not in (SINGLE_SOURCE, Path(__file__).resolve())
            )
    return sorted(found)


def test_there_are_modules_to_check():
    """Guards the guard: an empty sweep would make the rule vacuous."""

    files = python_files()
    assert len(files) > 20, f"only {len(files)} modules swept; the rule proves nothing"


def test_the_single_source_exists_and_names_the_roots():
    assert SINGLE_SOURCE.is_file(), f"{SINGLE_SOURCE} is the only place these belong"
    text = SINGLE_SOURCE.read_text(encoding="utf-8")
    assert WAREHOUSE_PATH.search(text), (
        "the single source names no warehouse root, so every other module "
        "would have to invent one"
    )


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_no_module_hardcodes_a_warehouse_path(path: Path):
    offenders = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        # A comment may name a root when explaining which one went wrong; the
        # defect is a module *resolving* one, not a sentence mentioning it.
        if line.lstrip().startswith("#"):
            continue
        match = WAREHOUSE_PATH.search(line)
        if match:
            offenders.append(f"{number}: {match.group(0)}")
    assert not offenders, (
        f"{path.relative_to(REPO)} names a warehouse directory: {offenders}. "
        "Import it from scripts/m3/current_build.py instead -- a pinned path "
        "keeps working after the warehouse moves, and reports green."
    )
