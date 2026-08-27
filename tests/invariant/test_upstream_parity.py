"""The upstreamed modules exist in two places and must never differ.

Taiwan Core holds the canonical modules, because that is where the trading
system calls them from. This repository holds mirrors so that governance CI —
which has no Taiwan Core checkout — can still run the pure-logic rule and
ledger tests on every push.

A mirror is only safe while it is provably a mirror. These tests are the
proof. They skip where Taiwan Core is absent, which is exactly the environment
that cannot fork the file anyway.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CORE_SRC = Path(r"C:\project\tw-sepa-screener\src\tw_sepa_screener")

# (mirror in this repository, canonical module in Taiwan Core, import name)
UPSTREAMED = (
    (REPO / "m4" / "rules.py", CORE_SRC / "market_rules.py", "market_rules"),
    (REPO / "m5" / "ledger.py", CORE_SRC / "ledger.py", "ledger"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("mirror,canonical,name", UPSTREAMED)
def test_the_mirror_exists_here(mirror, canonical, name):
    """Deleting one would silently remove its tests from CI."""

    assert mirror.is_file(), (
        f"{mirror.name} is gone; governance CI has no Taiwan Core checkout, so "
        f"the {name} tests would stop running anywhere automated"
    )


@pytest.mark.parametrize("mirror,canonical,name", UPSTREAMED)
def test_the_two_copies_are_byte_identical(mirror, canonical, name):
    if not canonical.is_file():
        pytest.skip("Taiwan Core checkout not present on this machine")
    assert digest(mirror) == digest(canonical), (
        f"{mirror.name} and tw_sepa_screener.{name} have diverged. One of them "
        "was edited directly; copy the intended version over the other rather "
        "than reconciling by hand"
    )


@pytest.mark.parametrize("mirror,canonical,name", UPSTREAMED)
def test_the_canonical_copy_is_under_version_control(mirror, canonical, name):
    """Byte-identity to an untracked file proves less than it looks like.

    Found on 2026-08-27: neither `market_rules.py` nor `ledger.py` had ever
    been committed in Taiwan Core. They sat in its working tree, untracked and
    not ignored, while M4.2 and the milestone register both described them as
    the canonical copy and this repository's copies as mirrors of them.

    Every other test in this file passed throughout. They compare two files
    and check that one imports; none of them asks whether the side called
    canonical has any history. A file with no commit cannot be diffed, blamed,
    reverted or recovered, so the direction of authority was backwards: the
    mirror was the only version under control.
    """

    if not canonical.is_file():
        pytest.skip("Taiwan Core checkout not present on this machine")
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", canonical.name],
        cwd=canonical.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"tw_sepa_screener/{canonical.name} is not tracked in Taiwan Core's "
        "git. It is described as the canonical copy, and an untracked file "
        "has no history to be canonical with -- commit it there, or say in "
        "the milestone register which copy actually is authoritative"
    )


def test_the_canonical_rules_are_importable_from_taiwan_core():
    """Byte-identity is not enough: it also has to load where it will be used."""

    module = pytest.importorskip("tw_sepa_screener.market_rules")
    from decimal import Decimal

    # The published TWT49U figures for 2402 on 2025-08-01.
    assert module.price_limits(Decimal("39.12")) == (
        Decimal("43.00"),
        Decimal("35.25"),
    )


def test_the_canonical_ledger_is_importable_from_taiwan_core():
    module = pytest.importorskip("tw_sepa_screener.ledger")
    assert module.LEDGER_VERSION.startswith("tw-alpha-m5-ledger/")


def test_the_mirrors_and_the_imports_agree_on_their_versions():
    rules = pytest.importorskip("tw_sepa_screener.market_rules")
    book = pytest.importorskip("tw_sepa_screener.ledger")
    from m4 import rules as mirrored_rules
    from m5 import ledger as mirrored_ledger

    assert mirrored_rules.RULES_VERSION == rules.RULES_VERSION
    assert mirrored_ledger.LEDGER_VERSION == book.LEDGER_VERSION


def test_the_ledger_fallback_import_would_resolve():
    """The mirror falls back to `m4.rules` where Taiwan Core is absent.

    That branch never runs on a machine which has both, so it is checked by
    name instead: every symbol the fallback imports must exist in the mirror it
    would fall back to. Without this, CI would be the first to find out.
    """

    from m4 import rules as mirrored_rules

    needed = (
        "BrokerTerms",
        "RULES_VERSION",
        "RuleError",
        "Side",
        "classify_lot",
        "settlement_date",
        "trade_costs",
    )
    missing = [name for name in needed if not hasattr(mirrored_rules, name)]
    assert not missing, f"the ledger's fallback import would fail on: {missing}"
