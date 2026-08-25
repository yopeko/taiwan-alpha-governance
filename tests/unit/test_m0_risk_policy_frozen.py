"""ADR-0002 decision 5: the ADR changes what may be claimed, not the policy.

The ADR separates the scale a strategy is measured at from the scale it would
be executed at. That distinction only means anything while M0 section 8 stays
put -- an ADR about interpretation that quietly moved the capital or the slot
count would be an amendment wearing the wrong hat.

Two copies have to agree, and neither is decorative. The contract table is
what a person reads; the constants in `m5/ledger.py` are what refuses a trade.
A drift between them means the account is run under a policy nobody approved,
and the ledger would win silently because it is the one that executes.

The values are written out here a third time on purpose. Deriving them from
either side would make this test agree with whichever it derived from.
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from m5.ledger import (  # noqa: E402
    POLICY_HARD_RISK_CAP,
    POLICY_INITIAL_CAPITAL,
    POLICY_MAX_POSITIONS,
    POLICY_MAX_WEIGHT_PER_NAME,
    POLICY_MIN_CASH_RESERVE,
    POLICY_PLANNED_RISK,
    POLICY_TOTAL_OPEN_RISK_CAP,
)

CONTRACT = REPO / "docs" / "m0-project-contract.md"

# M0 section 8 as of m0-v1.1.0.
#
# The baseline moved once, and how it moved is the point. On 2026-08-25 this
# test failed on four assertions the moment the constants changed -- which is
# what it is for. A policy change has to be an approved amendment with its own
# decision record, never a quiet edit that nothing notices.
#
# v1.0.0 -> v1.1.0 (Owner decision D16): max_positions 2 -> 10 and
# total_open_risk_cap 2.00% -> 7.50%. Everything else unchanged, including by
# ADR-0002, which explicitly does not amend this section.
BASELINE = {
    "initial_capital": Decimal("10000"),
    "max_positions": 10,
    "max_weight_per_name": Decimal("0.45"),
    "min_cash_reserve": Decimal("0.10"),
    "planned_risk": Decimal("0.0075"),
    "hard_risk_cap": Decimal("0.0100"),
    "total_open_risk_cap": Decimal("0.0750"),
}

# M0 section 8.1 halts a canary at an 8% drawdown. A total open risk cap at or
# above that would permit a set of compliant positions whose stops, all
# reached, trigger the halt: one rule allowing what another stops. 10% was
# authorised and 7.50% chosen to keep the gap.
HARD_STOP_DRAWDOWN = Decimal("0.08")


def contract_section_8() -> str:
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("## 8. NT$10,000")
    return text[start : text.index("### 8.1", start)]


class TestTheLedgerStillEnforcesTheBaseline:
    def test_initial_capital(self):
        assert POLICY_INITIAL_CAPITAL == BASELINE["initial_capital"]

    def test_slot_count(self):
        """The number ADR-0002 background 3 is entirely about."""

        assert POLICY_MAX_POSITIONS == BASELINE["max_positions"]

    def test_weight_and_cash_caps(self):
        assert POLICY_MAX_WEIGHT_PER_NAME == BASELINE["max_weight_per_name"]
        assert POLICY_MIN_CASH_RESERVE == BASELINE["min_cash_reserve"]

    def test_risk_caps(self):
        assert POLICY_PLANNED_RISK == BASELINE["planned_risk"]
        assert POLICY_HARD_RISK_CAP == BASELINE["hard_risk_cap"]
        assert POLICY_TOTAL_OPEN_RISK_CAP == BASELINE["total_open_risk_cap"]

    def test_the_planned_target_stays_under_the_hard_cap(self):
        """Ordering, not just values: a target above its own ceiling is a bug."""

        assert POLICY_PLANNED_RISK < POLICY_HARD_RISK_CAP
        assert POLICY_HARD_RISK_CAP <= POLICY_TOTAL_OPEN_RISK_CAP

    def test_the_slot_count_equals_the_risk_budget(self):
        """Not an independent number, and it must not become one.

        D16 raised both together. Raising only the slot cap would let it
        permit what the risk cap forbids; raising only the risk cap would
        leave capacity nothing can use.
        """

        assert POLICY_MAX_POSITIONS * POLICY_PLANNED_RISK <= POLICY_TOTAL_OPEN_RISK_CAP
        assert (
            POLICY_MAX_POSITIONS + 1
        ) * POLICY_PLANNED_RISK > POLICY_TOTAL_OPEN_RISK_CAP

    def test_the_risk_cap_stays_below_the_hard_stop(self):
        """M0 8.1, and the reason 7.50% was chosen over the authorised 10%."""

        assert POLICY_TOTAL_OPEN_RISK_CAP < HARD_STOP_DRAWDOWN, (
            "a fully compliant book could be stopped out by the drawdown rule "
            "before the risk cap ever refused anything"
        )


@pytest.fixture(scope="module")
def section() -> str:
    return contract_section_8()


class TestTheContractStillSaysTheSame:
    def test_the_section_is_findable(self, section):
        """Guards the guard: an empty slice would satisfy every check below."""

        assert len(section) > 200, "M0 section 8 did not parse; the rest proves nothing"

    @pytest.mark.parametrize(
        "phrase",
        [
            "NT$10,000",
            "| 最大持股數 | **10**（v1.1.0；原為 2）|",
            "45%",
            "10%",
            "0.75% NAV",
            "1.00% NAV",
            "**7.50% NAV**（v1.1.0；原為 2.00%）",
        ],
    )
    def test_the_table_still_carries_the_baseline(self, section, phrase):
        assert phrase in section, (
            f"M0 section 8 no longer states {phrase!r}. Changing the risk "
            "policy needs its own Owner decision and a contract version bump; "
            "ADR-0002 explicitly does not do it (decision 5)."
        )

    def test_the_refusal_rule_survives(self, section):
        """The sentence the whole sizing design rests on."""

        assert "no_trade" in section
        assert "不可向上取整後突破上限" in section


class TestTheAdrDidNotQuietlyAmendThePolicy:
    def test_the_adr_says_so_itself(self):
        adr = (
            REPO
            / "docs"
            / "adr"
            / "0002-measurement-scale-separate-from-execution-scale.md"
        )
        text = adr.read_text(encoding="utf-8")
        assert "不因本 ADR 變動" in text, (
            "ADR-0002 decision 5 is the clause this whole test enforces; if it "
            "is gone, the contract between the two documents is gone with it"
        )
        # Accepted, not still a draft: a proposal cannot bind anything.
        assert re.search(r"\*\*Accepted", text)
