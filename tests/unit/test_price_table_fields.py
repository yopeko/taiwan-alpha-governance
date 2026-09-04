"""The price table has to carry what the contract says it carries.

PIT contract section 6.4 requires `daily_prices_pit` to preserve
"volume／turnover／transactions". It preserved two of the three for the life
of the project.

The parsers were never the problem: `transactions` appears in every
`source_columns_seen` list the builder has ever written, for both markets.
The row construction picked `volume` and `turnover` by name and did not pick
the third, and nothing compared the built columns against the sentence that
required them.

It surfaced sideways -- FinMind's free daily feed returns
`Trading_turnover`, a per-security transaction count, and the question "why
does a vendor have a field the warehouse lacks" turned out to have the answer
"it does not lack it". Two days before that, the regime-continuity
measurement wanted this field, found it missing, and narrowed itself to a
market-wide total from the raw blobs.

So this test reads the contract.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m3"))

BUILDER = (REPO / "scripts" / "m3" / "build_prices_actions.py").read_text(
    encoding="utf-8"
)
CONTRACT = (REPO / "docs" / "contracts" / "pit-warehouse-contract.md").read_text(
    encoding="utf-8"
)

# The sentence the requirement lives in, section 6.4. Matched rather than
# restated: a test that hardcodes the field list would still pass if someone
# widened the contract and left the builder alone, which is the exact shape
# that let this one through.
REQUIREMENT = re.compile(r"保存 raw official price basis[^\n]*")


def required_measures() -> list[str]:
    """The measure fields section 6.4 names, in the order it names them."""

    sentence = REQUIREMENT.search(CONTRACT)
    assert sentence, "section 6.4's requirement sentence is not where it was"
    names = re.search(r"([a-z]+)／([a-z]+)／([a-z]+)", sentence.group(0))
    assert names, sentence.group(0)
    return list(names.groups())


def built_fields() -> set[str]:
    """The keys the builder puts in a price row."""

    block = BUILDER.split("rows.append(")[1].split("collapse_quotes")[0]
    return set(re.findall(r'^\s*"([a-z_]+)":', block, flags=re.MULTILINE))


def test_the_contract_still_names_three_measures():
    """If this fails the contract changed, and the test below is measuring
    against a sentence that no longer says what it did."""

    assert required_measures() == ["volume", "turnover", "transactions"]


def test_every_measure_the_contract_names_is_built():
    """The defect. Two of three were built for the life of the project."""

    missing = [name for name in required_measures() if name not in built_fields()]
    assert not missing, (
        f"PIT contract section 6.4 requires {missing} in daily_prices_pit and "
        f"the builder does not construct them"
    )


def test_the_field_scan_found_the_real_row():
    """A scan that matched nothing would make the test above vacuous."""

    fields = built_fields()
    assert {"market", "symbol", "session_date", "close", "ohlc_state"} <= fields
    assert len(fields) >= 15, sorted(fields)


def test_transactions_is_taken_from_the_official_parse_not_a_vendor():
    """FinMind supplies the same measure and is a vendor. The warehouse's
    daily prices are `official-captured`, and a vendor field in that table
    would mix evidence states inside one row."""

    assert 'first_present(source_row, "transactions")' in BUILDER
    # The word appears in a comment explaining how the omission surfaced. What
    # must not appear is a code path: no vendor host, no vendor client.
    assert "finmindtrade" not in BUILDER
    assert "urllib" not in BUILDER and "requests" not in BUILDER
