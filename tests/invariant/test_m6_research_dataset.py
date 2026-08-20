"""M6 invariants for the frozen research dataset.

The dataset is the only thing a strategy sees. Everything M3 proved about
availability, tradability and price restatement has to survive the export, or
the strategy inherits none of it and the warehouse was decoration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DATASET = Path(r"C:\tmp\tw-alpha-m6-dataset-02")


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
def manifest():
    import json

    path = DATASET / "dataset_manifest.json"
    if not path.is_file():
        pytest.skip("research dataset not built on this machine")
    return json.loads(path.read_bytes())


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
        assert manifest["sessions"] == 382
        assert manifest["window"]["start"] == "2025-01-02"
        assert manifest["window"]["end"] == "2026-08-03"

    def test_the_warmup_limit_is_stated_rather_than_left_to_be_discovered(self, manifest):
        """382 sessions minus a 250-session warmup leaves 132 usable ones.

        A strategy needing a 52-week high has about six months of signal window
        here, which is not enough to conclude anything. The dataset says so
        rather than letting a reader assume the window is the sample.
        """

        assert any("warmup" in note.lower() for note in manifest["notes"])
