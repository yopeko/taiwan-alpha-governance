"""The window arithmetic the control comparison rests on.

Option 乙 compares two candidates only where both were trading, which makes
the window boundary a computed thing rather than a given one. Everything
downstream -- return, drawdown, trade counts, costs -- is recomputed against
that boundary, so a boundary that is off by a session silently moves every
figure in the comparison.

These are unit tests on the arithmetic. The contract tests that read a real
comparison artifact live in tests/invariant.

The drawdown case is the one worth reading. The whole reason the contract
forbids carrying figures in from the full run is that a drawdown can happen
before the comparison starts, and a comparison that inherits it is reporting
a loss neither candidate took during the period being compared.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "m6"))

from compare_candidates import trading_span, window_metrics  # noqa: E402


def bars(*navs: tuple[str, float]) -> list[dict]:
    return [{"session": s, "nav": n} for s, n in navs]


def trade(
    entry: str,
    exit_: str,
    *,
    price: float = 100.0,
    qty: int = 1000,
    symbol: str = "0000",
) -> dict:
    return {
        "market": "TWSE",
        "symbol": symbol,
        "entry_session": entry,
        "exit_session": exit_,
        "entry_price": price,
        "exit_price": price,
        "quantity": qty,
        "exit_reason": "stop",
    }


class TestTheWindowComesFromTradesNotFromTheDataset:
    def test_it_is_the_first_entry_and_the_last_exit(self):
        result = {"trades": [trade("2020-03-02", "2020-03-10"), trade("2019-05-01", "2019-05-09")]}
        assert trading_span(result) == ("2019-05-01", "2020-03-10")

    def test_a_candidate_that_never_traded_has_no_span(self):
        """Being present in the dataset is not the same as trading.

        The 12-1 momentum candidate could not score anything for its first 252
        sessions. Counting those as its window is precisely the mistake that
        made the M6.3 comparison meaningless.
        """

        assert trading_span({"trades": []}) is None


class TestEveryFigureIsRecomputedInsideTheWindow:
    def test_return_is_rebased_to_the_window_opening_nav(self):
        result = {
            "equity": bars(
                ("2019-01-02", 100.0),
                ("2020-01-16", 200.0),
                ("2020-06-30", 240.0),
            ),
            "trades": [],
        }
        metrics = window_metrics(result, "2020-01-16", "2020-06-30")
        assert metrics["nav_at_window_start"] == 200.0
        assert metrics["return_pct_in_window"] == pytest.approx(20.0)

    def test_a_drawdown_before_the_window_does_not_count(self):
        """The reason the contract forbids carrying figures in.

        This account halved before the comparison began and rose steadily
        through it. Its full-run drawdown is 50%; inside the window it is
        zero, and reporting 50% would attribute a loss to a period in which
        it did not happen.
        """

        result = {
            "equity": bars(
                ("2019-01-02", 100.0),
                ("2019-06-03", 50.0),
                ("2020-01-16", 80.0),
                ("2020-06-30", 120.0),
            ),
            "trades": [],
        }
        metrics = window_metrics(result, "2020-01-16", "2020-06-30")
        assert metrics["drawdown_pct_in_window"] == pytest.approx(0.0)

    def test_a_drawdown_inside_the_window_does_count(self):
        result = {
            "equity": bars(
                ("2020-01-16", 100.0),
                ("2020-03-02", 60.0),
                ("2020-06-30", 90.0),
            ),
            "trades": [],
        }
        metrics = window_metrics(result, "2020-01-16", "2020-06-30")
        assert metrics["drawdown_pct_in_window"] == pytest.approx(40.0)

    def test_trades_are_counted_by_the_session_they_closed_in(self):
        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [
                trade("2019-11-01", "2019-12-01"),
                trade("2019-12-20", "2020-02-03"),
                trade("2020-03-02", "2020-03-20"),
                trade("2020-06-01", "2020-08-01"),
            ],
        }
        metrics = window_metrics(result, "2020-01-16", "2020-06-30")
        assert metrics["completed_trades_in_window"] == 2

    def test_costs_come_only_from_the_trades_that_counted(self):
        inside = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [trade("2020-03-02", "2020-03-20")],
        }
        outside = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [trade("2019-03-02", "2019-03-20")],
        }
        assert window_metrics(inside, "2020-01-16", "2020-06-30")["cost_total_in_window"] > 0
        assert window_metrics(outside, "2020-01-16", "2020-06-30")["cost_total_in_window"] == 0


class TestWhatOptionYiCosts:
    """The disclosure that makes 乙 honest rather than convenient."""

    def test_a_position_open_across_the_boundary_is_reported(self):
        """Opened before the window, closed inside it: carried in."""

        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [trade("2019-11-01", "2020-02-03")],
        }
        metrics = window_metrics(result, "2020-01-16", "2020-06-30")
        assert metrics["open_positions_at_window_start"] == 1
        assert metrics["cost_basis_carried_into_window"] > 0

    def test_one_position_sold_in_two_legs_counts_once(self):
        """A holding that is neither whole board lots nor a pure odd lot is
        sold as two orders, so it leaves two trade records. Counting records
        reported 16 positions carried into a window under a ten-slot policy.
        """

        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [
                trade("2019-11-01", "2020-02-03", qty=1000),
                trade("2019-11-01", "2020-02-03", qty=437),
            ],
        }
        metrics = window_metrics(result, "2020-01-16", "2020-06-30")
        assert metrics["open_positions_at_window_start"] == 1
        # Both legs still count towards what was carried in.
        assert metrics["cost_basis_carried_into_window"] == pytest.approx(143700.0)

    def test_two_different_names_still_count_twice(self):
        """Guards the guard: deduplication must not collapse real positions."""

        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [
                trade("2019-11-01", "2020-02-03", symbol="1101"),
                trade("2019-11-01", "2020-02-03", symbol="2330"),
            ],
        }
        assert window_metrics(result, "2020-01-16", "2020-06-30")[
            "open_positions_at_window_start"
        ] == 2

    def test_the_same_name_entered_twice_counts_twice(self):
        """Different entry sessions are different positions, same symbol."""

        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [
                trade("2019-11-01", "2020-02-03"),
                trade("2019-12-05", "2020-02-10"),
            ],
        }
        assert window_metrics(result, "2020-01-16", "2020-06-30")[
            "open_positions_at_window_start"
        ] == 2

    def test_a_position_opened_inside_the_window_is_not_carried(self):
        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [trade("2020-03-02", "2020-03-20")],
        }
        assert window_metrics(result, "2020-01-16", "2020-06-30")[
            "open_positions_at_window_start"
        ] == 0

    def test_a_position_closed_before_the_window_is_not_carried(self):
        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [trade("2019-11-01", "2019-12-01")],
        }
        assert window_metrics(result, "2020-01-16", "2020-06-30")[
            "open_positions_at_window_start"
        ] == 0

    def test_a_flat_account_reports_zero_rather_than_nothing(self):
        """Zero is the disclosure too. An absent field reads as unchecked."""

        result = {
            "equity": bars(("2020-01-16", 100.0), ("2020-06-30", 100.0)),
            "trades": [],
        }
        metrics = window_metrics(result, "2020-01-16", "2020-06-30")
        assert metrics["open_positions_at_window_start"] == 0
        assert metrics["cost_basis_carried_into_window"] == 0.0


class TestItRefusesRatherThanGuessing:
    def test_an_empty_window_is_refused(self):
        """Silently returning zeroes would look like a candidate that flat-lined."""

        result = {"equity": bars(("2019-01-02", 100.0)), "trades": []}
        with pytest.raises(SystemExit):
            window_metrics(result, "2020-01-16", "2020-06-30")


class TestTheContractDocumentSaysWhatTheCodeDoes:
    def test_the_contract_records_the_option_that_was_chosen(self):
        contract = (
            REPO / "docs" / "contracts" / "control-comparison-contract.md"
        ).read_text(encoding="utf-8")
        assert "control-comparison-v1.1.0" in contract
        assert "乙" in contract

    def test_the_contract_requires_both_scales_and_both_rates(self):
        """Eight rows. Four would let the favourable combination be chosen."""

        contract = (
            REPO / "docs" / "contracts" / "control-comparison-contract.md"
        ).read_text(encoding="utf-8")
        for phrase in ("m0-execution", "reference-measurement", "0.001"):
            assert phrase in contract
        assert "8 列" in contract

    def test_the_universe_is_a_candidate_attribute_not_an_assumption(self):
        """v1.1.0. Refusing TPEx odd-lot entries changed which names were
        held, not how much of them was reachable: -3.57% against -37.76% at
        the reference scale. A setting that changes the holdable set belongs
        to the candidate; one that changes reachable quantity belongs on the
        axis."""

        contract = (
            REPO / "docs" / "contracts" / "control-comparison-contract.md"
        ).read_text(encoding="utf-8")
        assert "no-tpex-odd-lot-entry" in contract
        assert "屬於候選定義" in contract

    def test_the_producer_declares_the_version_the_contract_carries(self):
        """The third time this pair has been found disagreeing.

        The candidate report producer said v1.0.0 while its document had moved
        to v1.1.0, and this producer was written with the same defect on the
        same day the first one was fixed. A version string nobody compares is
        a claim nobody checks.
        """

        import re

        contract = (
            REPO / "docs" / "contracts" / "control-comparison-contract.md"
        ).read_text(encoding="utf-8")
        declared = (REPO / "scripts" / "m6" / "compare_candidates.py").read_text(
            encoding="utf-8"
        )
        version = re.search(
            r'CONTRACT_VERSION = "(control-comparison-v[0-9.]+)"', declared
        )
        assert version, "the producer no longer declares a contract version"
        assert version.group(1) in contract, (
            f"the producer declares {version.group(1)}, which the contract "
            "document does not mention"
        )

    def test_the_driver_and_the_contract_agree_on_the_universes(self):
        """Two copies of an enumeration must move together."""

        sys.path.insert(0, str(REPO / "scripts" / "m6"))
        from run_ledger_backtest import UNIVERSES

        contract = (
            REPO / "docs" / "contracts" / "control-comparison-contract.md"
        ).read_text(encoding="utf-8")
        for name in UNIVERSES:
            if name == "all":
                continue
            assert name in contract, f"the contract does not list {name}"

    def test_the_contract_names_the_disclosure_option_yi_owes(self):
        contract = (
            REPO / "docs" / "contracts" / "control-comparison-contract.md"
        ).read_text(encoding="utf-8")
        assert "open_positions_at_window_start" in contract
