"""The guard on the guards: a suite that skips must not look like one that passes.

On 2026-08-25 the six-year rebuild finished and the suite reported 422 passed
with the count unchanged from before it. Every M3 invariant file was reading
the previous generation's scratch directory. Nothing was red, nothing was
skipped, and nothing had been checked.

These tests are cheap and they are the reason the rest can be trusted. They
fail rather than skip whenever this machine could have built the warehouse and
did not, so the two states the summary line cannot tell apart -- everything
verified, and nothing looked at -- can never both be green.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

from conftest import TAIWAN_CORE  # noqa: E402
from warehouse import (  # noqa: E402
    GENERATION,
    WAREHOUSE_ROOTS,
    WINDOW,
    missing_roots,
)


def test_the_generation_is_named():
    """A warehouse nobody named is one nobody can tell is stale."""

    assert GENERATION.strip(), "tests/warehouse.py must say which build it reads"
    assert WINDOW[0] < WINDOW[1]


def test_there_are_roots_to_check():
    """An empty mapping would make every check below vacuous."""

    assert WAREHOUSE_ROOTS, "no warehouse roots declared; the guard guards nothing"


def test_the_warehouse_is_present_or_this_machine_cannot_build_it():
    if not TAIWAN_CORE.is_dir():
        pytest.skip("no Taiwan Core checkout; the warehouse cannot exist here")
    absent = missing_roots()
    assert not absent, (
        f"warehouse roots missing on a machine that has Taiwan Core: {absent}. "
        "The M3 invariant tests would each skip on their own and the summary "
        "would read as a pass. Rebuild, or point tests/warehouse.py at the "
        "build you mean."
    )


def test_every_root_carries_a_manifest():
    """A directory that exists but was never finished is not a build.

    The 2026-08-25 01:06 staging run died to system sleep and left 19,986
    files and no manifest. Existence is not completion.
    """

    if not TAIWAN_CORE.is_dir():
        pytest.skip("no Taiwan Core checkout; the warehouse cannot exist here")
    if missing_roots():
        pytest.skip("covered by the presence test above")
    incomplete = [
        name
        for name, root in WAREHOUSE_ROOTS.items()
        if not (root / "dataset_manifest.json").is_file()
    ]
    assert not incomplete, f"warehouse roots with no dataset_manifest.json: {incomplete}"


def test_every_root_was_built_from_one_staging_layer():
    """Three tables from three different staging builds are not one warehouse."""

    if not TAIWAN_CORE.is_dir() or missing_roots():
        pytest.skip("no warehouse to compare")
    import json

    ids = {}
    for name, root in WAREHOUSE_ROOTS.items():
        manifest = root / "dataset_manifest.json"
        if not manifest.is_file():
            continue
        ids[name] = json.loads(manifest.read_bytes()).get("staging_dataset_id")
    assert len(set(ids.values())) == 1, (
        f"tables built from different staging layers: {ids}. Any cross-table "
        "invariant would be comparing two different worlds."
    )
