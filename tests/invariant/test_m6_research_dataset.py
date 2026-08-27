"""M6 invariants for the frozen research dataset.

The dataset is the only thing a strategy sees. Everything M3 proved about
availability, tradability and price restatement has to survive the export, or
the strategy inherits none of it and the warehouse was decoration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

# Deliberately the pre-rebuild generation. M6 has not been re-run for the
# six-year window, so this dataset and the warehouse it was derived from are
# a matched pair; swapping in the new prices table would compare 382 sessions
# against 1,840 and read the difference as a defect.
from warehouse import (  # noqa: E402
    RESEARCH_DATASET as DATASET,
    RESEARCH_DATASET_PRICES,
)

WAREHOUSE_PRICES = RESEARCH_DATASET_PRICES / "daily_prices_pit.parquet"


def table():
    path = DATASET / "research_dataset.parquet"
    if not path.is_file():
        pytest.skip("research dataset not built on this machine")
    pq = pytest.importorskip("pyarrow.parquet")
    return pq.read_table(path)


@pytest.fixture(scope="module")
def dataset():
    return table()


@pytest.fixture(scope="module")
def warehouse():
    if not WAREHOUSE_PRICES.is_file():
        pytest.skip("price warehouse not built on this machine")
    pq = pytest.importorskip("pyarrow.parquet")
    return pq.read_table(WAREHOUSE_PRICES)


@pytest.fixture(scope="module")
def manifest():
    import json

    path = DATASET / "dataset_manifest.json"
    if not path.is_file():
        pytest.skip("research dataset not built on this machine")
    return json.loads(path.read_bytes())


# 3202 went to full-cash delivery on this date and never came off it. A market
# fact, so it belongs next to the tests rather than inside one of them.
FULL_CASH_FROM = "2024-11-19"


class TestNothingPricedIsDroppedInSilence:
    """A security the exchange quoted must reach the dataset, or be refused.

    The export walks the lifecycle table, which comes from the licensed-vendor
    lane, so the universe was in effect defined by what that vendor covered.
    Any security with official prices and no lifecycle row produced no row, no
    reason code and no warning: 44 securities and 11,350 official price rows,
    1.53% of the warehouse, gone without a trace. A FinMind cross-validation
    is what noticed, because a warehouse checked only against its own sources
    reports itself complete however much it is missing.

    Two of those mattered on their own. 3202 樺晟 traded 57 sessions and then
    delisted inside the window, and dropping exactly the securities that stop
    existing is how survivorship bias gets in. 5236 凌陽創新 moved from TPEx
    to TWSE on 2026-07-16, and its 14 TWSE sessions are the only ones in the
    whole dataset where M4's transferred_from_tpex exception applies.

    Being out of scope is a verdict, not an absence. It has to be visible.
    """

    def priced(self, warehouse):
        return set(
            zip(warehouse["market"].to_pylist(), warehouse["symbol"].to_pylist())
        )

    def exported(self, dataset):
        return set(zip(dataset["market"].to_pylist(), dataset["symbol"].to_pylist()))

    def test_every_priced_security_reaches_the_dataset(self, dataset, warehouse):
        missing = sorted(self.priced(warehouse) - self.exported(dataset))
        assert not missing, (
            f"{len(missing)} securities have official prices but no row in the "
            f"dataset: {missing[:12]}"
        )

    def test_a_delisted_security_is_kept_rather_than_erased(self, dataset, warehouse):
        """The securities that stop existing are the ones bias needs kept."""

        assert ("TPEX", "3202") in self.exported(dataset)

    def phases(self, dataset, symbol, market):
        rows = sorted(
            (session, state)
            for candidate, board, session, state in zip(
                dataset["symbol"].to_pylist(),
                dataset["market"].to_pylist(),
                dataset["session_date"].to_pylist(),
                dataset["tradability_state"].to_pylist(),
            )
            if candidate == symbol and board == market
        )
        assert rows, f"{symbol} has no rows at all"
        return rows, {
            state: [s for s, st in rows if st == state] for _, state in rows
        }

    def test_a_losing_security_can_actually_be_bought_before_it_dies(self, dataset):
        """Present is not enough; a backtest has to be able to lose on it.

        6806 森崴能源 is the case the universe has to contain. It was plainly
        tradable from the first session of the window, fell 113.50 to 34.75,
        and delisted on 2026-06-23. A universe drawn from filings keeps the
        survivors and drops exactly this, so the drop never happens to anyone.

        Eligible is the specific claim being made. A security that is only
        *present* changes nothing: nothing trades an `unknown` or a
        `restricted`, so a loser that never reaches `eligible` still cannot
        cost a backtest a cent.
        """

        rows, by_state = self.phases(dataset, "6806", "TWSE")
        eligible = by_state.get("eligible") or []
        assert len(eligible) > 250, (
            f"6806 is tradable on only {len(eligible)} sessions; it traded "
            "normally for most of the window before delisting"
        )
        # Its listing, not the window's first session. Pinned to 2025-01-02
        # until 2026-08-27, which was true only of the 382-session build and
        # said nothing about 6806.
        assert eligible[0] == "2021-11-15"
        assert not [d for d in eligible if d >= "2026-06-23"], (
            "6806 delisted on 2026-06-23; no session at or after that date "
            "may read eligible"
        )
        assert max(rows)[1] == "ineligible"

    def test_a_delisted_security_keeps_its_phases_in_order(self, dataset):
        """3202 樺晟, whose three phases are three different claims.

        Restricted from the first session, because it was on full-cash
        delivery from 2024-11-19 and stayed there; then listed but absent
        from the closing table, which is a suspension inferred rather than
        observed; then delisted on 2025-07-21 and gone for good.

        Those 57 sessions read `eligible` until 全額交割 was modelled, which
        is why this is not the survivorship test any more: the security whose
        loss a backtest can actually take is 6806 above. Being visible and
        being tradable are separate properties and both have to be checked.
        """

        rows, by_state = self.phases(dataset, "3202", "TPEX")
        eligible = by_state.get("eligible") or []
        # It traded normally for years before 全額交割. The old assertion said
        # it never did, which was true only because the 382-session window
        # started after that date.
        assert eligible, "3202 traded on normal terms before full-cash delivery"
        assert max(eligible) == "2024-11-18", (
            "3202 went to full-cash delivery on 2024-11-19; the last eligible "
            "session must be the one before it"
        )
        assert not [d for d in eligible if d >= FULL_CASH_FROM], (
            "eligible after full-cash delivery began would claim 3202 was "
            "available on normal terms when it was not"
        )
        restricted = by_state.get("restricted") or []
        assert restricted[-1] == "2025-04-02"
        assert min(by_state.get("blocked") or ["9999"]) == "2025-04-07"
        assert min(by_state.get("ineligible") or ["9999"]) == "2025-07-21"
        assert min(by_state.get("ineligible") or ["9999"]) == "2025-07-21"
        assert max(rows)[1] == "ineligible"

    def test_full_cash_delivery_is_never_silently_normal(self, dataset):
        """全額交割 is not a normal trading condition and must not read as one.

        The buyer deposits the cash and the seller the shares before the
        order is accepted. 10,004 sessions of it were reaching the dataset as
        plain `eligible` because the warehouse modelled attention, disposal,
        capital reduction and par value change but not this.
        """

        states = dataset["tradability_state"].to_pylist()
        reasons = dataset["reason_codes"].to_pylist()
        marked = [
            i for i, reason in enumerate(reasons)
            if "status-full-cash-delivery" in (reason or "")
        ]
        assert len(marked) > 5000, (
            f"only {len(marked)} full-cash-delivery sessions reached the "
            "dataset; the vendor master carries far more than that"
        )
        assert not [i for i in marked if states[i] == "eligible"]

    def test_a_market_transfer_keeps_both_legs(self, dataset, warehouse):
        exported = self.exported(dataset)
        assert {("TPEX", "5236"), ("TWSE", "5236")} <= exported, (
            "5236 transferred from TPEx to TWSE inside the window; the TWSE "
            "leg carries the only sessions where the no-limit exception for a "
            "transferred security applies"
        )

    def test_an_out_of_scope_security_is_refused_and_says_why(self, dataset):
        """創新板 is excluded by Owner decision D1, which is a decision to state.

        Silence would look identical to the bug this class exists to prevent.
        """

        symbols = dataset["symbol"].to_pylist()
        reasons = dataset["reason_codes"].to_pylist()
        states = dataset["tradability_state"].to_pylist()
        rows = [i for i, s in enumerate(symbols) if s == "2258"]
        assert rows, "no rows for an innovation-board security at all"
        assert all(states[i] == "ineligible" for i in rows)
        # Only once it is on the board. Before it listed the honest reason is
        # `not-yet-on-any-board`, and requiring the innovation-board code for
        # every session -- as this did until 2026-08-27 -- demanded a reason
        # that would have been false for 1,186 of them.
        on_board = [
            i for i in rows if "not-yet-on-any-board" not in (reasons[i] or "")
        ]
        assert on_board, "2258 never reaches the board in this window"
        assert all(
            "out-of-scope-innovation-board" in (reasons[i] or "") for i in on_board
        )

    def test_no_ordinary_share_is_mistaken_for_the_innovation_board(self, dataset):
        """群創 and 緯創 end in 創 without being on it.

        The marker is the suffix after the last hyphen, checked against the
        exchange's own board listing. A naive endswith would have thrown six
        listed companies, two of them large caps, out of the universe.
        """

        symbols = dataset["symbol"].to_pylist()
        reasons = dataset["reason_codes"].to_pylist()
        for symbol in ("3481", "3231", "8016", "3437", "6722", "1470"):
            rows = [i for i, s in enumerate(symbols) if s == symbol]
            assert rows, f"{symbol} is missing from the dataset entirely"
            assert not any(
                "out-of-scope-innovation-board" in (reasons[i] or "") for i in rows
            ), f"{symbol} was wrongly classified as innovation board"


class TestTheWarehouseVerdictSurvives:
    def test_every_row_carries_a_tradability_verdict(self, dataset):
        states = dataset["tradability_state"].to_pylist()
        assert all(states)
        assert set(states) <= {"eligible", "restricted", "blocked", "ineligible", "unknown"}

    def test_refusals_keep_their_reasons(self, dataset):
        """A strategy that was refused has to be able to say by which rule."""

        states = dataset["tradability_state"].to_pylist()
        reasons = dataset["reason_codes"].to_pylist()
        silent = [
            i
            for i, state in enumerate(states)
            if state in {"blocked", "unknown"} and not reasons[i]
        ]
        assert not silent, f"{len(silent)} refusals carry no reason code"

    def test_not_everything_is_eligible(self, dataset):
        """If the verdict were always the same it would carry no information."""

        states = set(dataset["tradability_state"].to_pylist())
        assert len(states) > 1


class TestPricesStayRaw:
    def test_no_adjusted_series_leaked_in(self, dataset, manifest):
        assert any("unadjusted" in note for note in manifest["notes"])

    def test_a_security_without_a_quote_has_no_close(self, dataset):
        closes = dataset["close"].to_pylist()
        states = dataset["price_state"].to_pylist()
        leaked = [
            i
            for i, state in enumerate(states)
            if state == "absent-from-official-table" and closes[i] is not None
        ]
        assert not leaked, (
            f"{len(leaked)} rows have a close on a session the exchange did not "
            "publish one"
        )


class TestLimitsNeverGuess:
    """The limit is where a wrong number is most expensive and least visible."""

    ALLOWED = {
        "publisher-exact",
        "computed-official-ex-rights-formula",
        "computed-from-previous-close",
        "blocked-restatement-without-reference-prices",
        "blocked-no-previous-close",
        "blocked-tick-band",
    }

    def test_every_limit_declares_where_it_came_from(self, dataset):
        assert set(dataset["limit_basis"].to_pylist()) <= self.ALLOWED

    def test_a_blocked_limit_is_absent_rather_than_approximate(self, dataset):
        bases = dataset["limit_basis"].to_pylist()
        ups = dataset["limit_up"].to_pylist()
        wrong = [
            i
            for i, basis in enumerate(bases)
            if basis.startswith("blocked") and ups[i] is not None
        ]
        assert not wrong, f"{len(wrong)} blocked limits carry a value anyway"

    def test_a_restatement_session_never_uses_the_previous_close(self, dataset):
        """M4.1 measured that base and it is wrong on every cash-increase row.

        A session with a corporate action takes the published limits, or the
        official two-reference formula, or nothing. Falling back to the
        previous close there would be confidently wrong on 1,665 sessions.
        """

        actions = dataset["corporate_action_state"].to_pylist()
        bases = dataset["limit_basis"].to_pylist()
        wrong = [
            i
            for i, state in enumerate(actions)
            if state not in ("no-action", "no-coverage")
            and bases[i] == "computed-from-previous-close"
        ]
        assert not wrong, (
            f"{len(wrong)} restatement sessions took their limits from the "
            "previous close"
        )

    def test_the_exchange_published_limits_are_actually_used(self, dataset):
        """They exist in the action table; the export must not drop them again.

        This began as 25 rows because the parser's typed output omitted the two
        limit columns and the builder never looked at the preserved raw record.
        """

        bases = dataset["limit_basis"].to_pylist()
        assert bases.count("publisher-exact") > 1000


class TestTheDatasetIsReproducible:
    def test_it_names_the_warehouse_it_came_from(self, manifest):
        assert manifest["warehouse_dataset_id"]
        for root in ("calendar", "prices", "status"):
            assert manifest["warehouse_roots"][root]

    def test_it_hashes_its_own_content(self, manifest):
        import hashlib

        path = DATASET / "research_dataset.parquet"
        assert manifest["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_it_covers_the_whole_m3_window(self, manifest):
        """382 sessions until the six-year rebuild landed on 2026-08-25.

        Pinned rather than derived on purpose: this is the test that notices
        the dataset silently changing size. It stayed at 382 for two days
        after the rebuild because nothing pointed it at the new build.
        """

        assert manifest["sessions"] == 1840
        assert manifest["window"]["start"] == "2019-01-02"
        assert manifest["window"]["end"] == "2026-08-03"

    def test_the_warmup_limit_is_stated_rather_than_left_to_be_discovered(self, manifest):
        """1,840 sessions minus a 250-session warmup leaves about 1,590.

        The 382-session build left 132, which was not enough to conclude
        anything and was the stated reason M6 could not produce a strategy
        result. The rebuild removed that limit; the note stays required,
        because a reader must not have to assume the window is the sample.
        """

        assert any("warmup" in note.lower() for note in manifest["notes"])
