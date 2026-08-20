"""The M4 rules exist in two places and must never differ.

Taiwan Core holds the canonical module, because that is where the trading
system calls it from. This repository holds a mirror so that governance CI —
which has no Taiwan Core checkout — can still run the 118 pure-logic rule
tests on every push.

A mirror is only safe while it is provably a mirror. These tests are the
proof. They skip where Taiwan Core is absent, which is exactly the environment
that cannot fork the file anyway.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIRROR = REPO / "m4" / "rules.py"
CANONICAL = Path(
    r"C:\project\tw-sepa-screener\src\tw_sepa_screener\market_rules.py"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_mirror_exists_here():
    """Deleting it would silently remove the M4 tests from CI."""

    assert MIRROR.is_file(), (
        "m4/rules.py is gone; governance CI has no Taiwan Core checkout, so "
        "the M4 rule tests would stop running anywhere automated"
    )


def test_the_two_copies_are_byte_identical():
    if not CANONICAL.is_file():
        pytest.skip("Taiwan Core checkout not present on this machine")
    assert digest(MIRROR) == digest(CANONICAL), (
        "m4/rules.py and tw_sepa_screener.market_rules have diverged. One of "
        "them was edited directly; copy the intended version over the other "
        "rather than reconciling by hand"
    )


def test_the_canonical_module_is_importable_from_taiwan_core():
    """Byte-identity is not enough: it also has to load where it will be used."""

    if not CANONICAL.is_file():
        pytest.skip("Taiwan Core checkout not present on this machine")
    module = pytest.importorskip("tw_sepa_screener.market_rules")
    from decimal import Decimal

    # The published TWT49U figures for 2402 on 2025-08-01.
    assert module.price_limits(Decimal("39.12")) == (
        Decimal("43.00"),
        Decimal("35.25"),
    )


def test_the_mirror_and_the_import_agree_on_the_rules_version():
    if not CANONICAL.is_file():
        pytest.skip("Taiwan Core checkout not present on this machine")
    upstream = pytest.importorskip("tw_sepa_screener.market_rules")
    from m4 import rules as mirrored

    assert mirrored.RULES_VERSION == upstream.RULES_VERSION
