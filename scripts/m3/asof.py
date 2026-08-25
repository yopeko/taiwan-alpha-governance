"""M3.6: the single as-of reconstruction interface.

Everything before this work package proved the data was captured, reproducible
and carried lineage. None of it proved the thing the warehouse exists for: that
asking about 2025-03-14 cannot return something only knowable on 2025-03-15.

This is deliberately the only way to read historical state, and it is
deliberately unhelpful. It refuses to guess. Where evidence is missing the
answer is `unknown` or `blocked`, never a default that happens to look
tradable.

Contract: docs/contracts/pit-warehouse-contract.md section 7.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq

INTERFACE_VERSION = "tw-alpha-m3-asof/1.0.0"


class AsOfError(ValueError):
    """Raised when a query cannot be answered safely."""


def _sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# Boards outside the M0 universe, and the reason code each one earns. A
# security is refused for the board it was on that session, never for the one
# it is on today.
OUT_OF_SCOPE_BOARDS = {
    "TIB": "out-of-scope-innovation-board",
    "REG": "out-of-scope-emerging-board",
    "ROTC": "out-of-scope-emerging-board",
    "GISA": "out-of-scope-go-incubation-board",
    "PUB": "out-of-scope-public-but-unlisted",
    "PSB": "out-of-scope-public-but-unlisted",
    "UNPUB": "out-of-scope-public-but-unlisted",
}


def on_innovation_board(name: str) -> bool:
    """Does the exchange's short name look like a 創新板 security?

    Kept as a cross-check, never as the scope decision. TWSE suffixes 創 to
    most innovation-board short names, and the test is on the segment after
    the last hyphen because 緯創, 群創, 矽創, 榮創, 輝創 and 大統新創 are
    ordinary listed companies whose names simply end in 創.

    It is sound but incomplete, which is why the board interval decides
    instead. Checked against the exchange's own board listing on 2026-08-21
    it matched 30 of 30 with no false positive -- but that listing only ever
    shows today, so the check itself could not see the securities that had
    already left. 6902 GOGOLOOK and 6794 向榮生技 were quoted under plain
    names for the 85 and 190 sessions before they moved to the main board,
    and a name-based rule let all 275 through.
    """

    name = (name or "").strip()
    if "-" not in name:
        return False
    return name.rsplit("-", 1)[1].endswith("創")


@dataclass(frozen=True)
class SecurityState:
    security_instance_id: str
    market: str
    symbol: str
    membership_state: str
    session_state: str
    market_status_state: str
    price_state: str
    corporate_action_state: str
    tradability_state: str
    reason_codes: tuple[str, ...]
    lineage: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class ReconstructionResult:
    as_of_session: str
    decision_as_of: str
    markets: tuple[str, ...]
    dataset_id: str
    session_states: dict[str, str]
    securities: tuple[SecurityState, ...]
    coverage: dict[str, Any]
    output_hash: str

    def by_tradability(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.securities:
            counts[item.tradability_state] = counts.get(item.tradability_state, 0) + 1
        return dict(sorted(counts.items()))


class Warehouse:
    """Loads the M3.3-M3.5 tables and answers as-of questions about them."""

    def __init__(self, calendar_root: Path, prices_root: Path, status_root: Path) -> None:
        self.calendar_root = Path(calendar_root)
        self.prices_root = Path(prices_root)
        self.status_root = Path(status_root)
        self._calendar = self._csv(self.calendar_root / "trading_calendar_pit.csv")
        self._intervals = self._csv(self.calendar_root / "security_intervals.csv")
        self._prices = self._parquet(self.prices_root / "daily_prices_pit.parquet")
        self._actions = self._parquet(self.prices_root / "corporate_actions_pit.parquet")
        self._action_window = self._window_of(self.prices_root)
        self._status = self._parquet(self.status_root / "market_status_pit.parquet")
        self._coverage = self._parquet(self.status_root / "market_status_coverage.parquet")
        self._names = self._name_history()
        self._priced_securities = self._priced()
        self._boards = self._board_history()
        self.dataset_id = self._dataset_id()

    def _board_history(self) -> dict[str, list[dict[str, str]]]:
        """Board intervals per symbol, or empty when the table is absent."""

        path = self.calendar_root / "security_board_intervals.csv"
        if not path.is_file():
            return {}
        history: dict[str, list[dict[str, str]]] = {}
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                history.setdefault(str(row["symbol"]), []).append(row)
        for entries in history.values():
            entries.sort(key=lambda r: r["effective_from"])
        return history

    def board_as_of(self, symbol: str, session: str) -> tuple[str, str]:
        """(board, market) this security sat on that session.

        Both empty when the master does not carry the security. The board is
        "" with a market of "before-first-listing" or "after-last-listing"
        when it does carry it but the session falls outside every interval,
        which is a different answer from not knowing.
        """

        entries = self._boards.get(symbol, [])
        if not entries:
            return "", ""
        for row in entries:
            start, end = row["effective_from"], row["effective_to"]
            if start and start > session:
                continue
            if end and session >= end:
                continue
            return row["board"], row["market"]
        if session < entries[0]["effective_from"]:
            return "", "before-first-listing"
        return "", "after-last-listing"

    def in_company_master(self, symbol: str) -> bool:
        """Does the vendor's company master carry this security at all?

        The master is keyed on there being a company. A security the exchange
        quotes which has no company behind it is a fund, a note or a trust --
        every one of the eight in this window is an ETF -- and M0 is common
        shares only.
        """

        return symbol in self._boards

    def _name_history(self) -> dict[tuple[str, str], list[tuple[str, str]]]:
        """Every short name the exchange printed for a security, by session.

        Kept as a history rather than one name per security because a name is
        point-in-time too: a security that reaches the innovation board is
        renamed when it gets there, and classifying an earlier session by a
        later name would be lookahead in the classifier itself.
        """

        history: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for row in self._prices:
            name = _iso(row.get("security_name"))
            if not name:
                continue
            key = (str(row.get("market")), str(row.get("symbol")))
            history.setdefault(key, []).append((_iso(row.get("session_date")), name))
        for entries in history.values():
            entries.sort()
        return history

    def _priced(self) -> dict[tuple[str, str], dict[str, str]]:
        return {
            (str(row.get("market")), str(row.get("symbol"))): {
                "market": str(row.get("market")),
                "symbol": str(row.get("symbol")),
            }
            for row in self._prices
        }

    def name_as_of(self, market: str, symbol: str, session: str) -> str:
        """The most recent name printed on or before this session."""

        entries = self._names.get((market, symbol)) or []
        seen = ""
        for when, name in entries:
            if when > session:
                break
            seen = name
        return seen

    def _universe(
        self, prices: dict[tuple[str, str], dict[str, Any]], markets: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """Lifecycle intervals, plus anything the exchange quoted regardless.

        The lifecycle table comes from the licensed-vendor lane. Letting it
        decide the universe means the vendor decides which securities exist,
        and a security it does not cover disappears with its prices. It is
        allowed to be silent; it is not allowed to be the reason a quote
        vanishes.
        """

        rows = list(self._intervals)
        known = {(row["market"], row["symbol"]) for row in rows}
        for market, symbol in sorted(self._priced_securities):
            if market in markets and (market, symbol) not in known:
                rows.append(
                    {
                        "security_instance_id": "",
                        "market": market,
                        "symbol": symbol,
                        "listing_date": "",
                        "delisting_date": "",
                        "lifecycle_state": "absent",
                    }
                )
        return rows

    @staticmethod
    def _csv(path: Path) -> list[dict[str, str]]:
        if not path.is_file():
            raise AsOfError(f"missing table: {path}")
        with path.open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _parquet(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            raise AsOfError(f"missing table: {path}")
        return pq.read_table(path).to_pylist()

    def _dataset_id(self) -> str:
        parts = {}
        for label, root in (
            ("calendar", self.calendar_root),
            ("prices", self.prices_root),
            ("status", self.status_root),
        ):
            manifest = root / "dataset_manifest.json"
            parts[label] = (
                json.loads(manifest.read_bytes()).get("staging_dataset_id", "")
                if manifest.is_file()
                else ""
            )
        return _sha(parts)

    @staticmethod
    def is_knowable(announced_at: str, decision_as_of: str) -> bool:
        """A fact is knowable only once its publisher announced it.

        An empty announcement date means the publisher gave none, so the fact
        is knowable at no historical cutoff at all. Returning True here would
        be the single most damaging bug in the warehouse, so it is a named
        function with its own tests rather than an inline comparison.
        """

        if not announced_at:
            return False
        return announced_at <= decision_as_of

    @staticmethod
    def _window_of(root: Path) -> tuple[str, str]:
        """The period the builder actually covered, as it recorded it.

        Without this, "no action on this date" and "this date was never built"
        are the same answer, and a query outside the window would silently
        report every security as having no corporate action.
        """

        manifest = root / "dataset_manifest.json"
        if not manifest.is_file():
            return ("", "")
        window = json.loads(manifest.read_bytes()).get("window") or {}
        return (str(window.get("start") or ""), str(window.get("end") or ""))

    def _has_action_coverage(self, session: str) -> bool:
        start, end = self._action_window
        return bool(start and end and start <= session <= end)

    def _actions_for(self, market: str, session: str):
        """Corporate actions taking effect on this very session.

        Deliberately *not* filtered by announcement date. The exchange restated
        the price on this day whether or not it told anyone in advance, and a
        return computed across the day is wrong either way. Hiding the event
        for want of an announcement would not protect against lookahead — the
        effect is contemporaneous, not future — it would only hide a price
        discontinuity that actually happened.

        Whether it could have been anticipated is a separate question, answered
        by `announced_at` and reported as its own reason code.
        """

        found: dict[str, list[dict[str, Any]]] = {}
        for row in self._actions:
            if row.get("market") != market:
                continue
            if _iso(row.get("effective_date")) != session:
                continue
            found.setdefault(str(row.get("symbol")), []).append(row)
        return found

    def _status_for(self, market: str, session: str, decision_as_of: str):
        applicable: dict[str, list[dict[str, Any]]] = {}
        for row in self._status:
            if row.get("market") != market:
                continue
            announced = _iso(row.get("announced_at"))
            if not self.is_knowable(announced, decision_as_of):
                continue
            start = _iso(row.get("effective_from"))
            end = _iso(row.get("effective_to"))
            if start and end:
                if not (start <= session <= end):
                    continue
            elif announced != session:
                continue
            applicable.setdefault(str(row.get("symbol")), []).append(row)
        return applicable

    def _has_status_coverage(self, market: str, session: str) -> bool:
        for row in self._coverage:
            if row.get("market") != market:
                continue
            if _iso(row.get("coverage_from")) <= session <= _iso(row.get("coverage_to")):
                return True
        return False

    def reconstruct(
        self,
        *,
        as_of_session: str,
        decision_as_of: str,
        markets: Iterable[str] = ("TWSE", "TPEX"),
        symbols: Iterable[str] | None = None,
    ) -> ReconstructionResult:
        markets = tuple(markets)
        if decision_as_of < as_of_session:
            raise AsOfError(
                "decision_as_of precedes the session being reconstructed: the "
                "caller is asking what was known before the day happened"
            )

        session_states = {
            row["market"]: row["session_state"]
            for row in self._calendar
            if row["session_date"] == as_of_session and row["market"] in markets
        }
        for market in markets:
            session_states.setdefault(market, "unknown")

        wanted = set(symbols) if symbols else None
        prices = {
            (row["market"], row["symbol"]): row
            for row in self._prices
            if _iso(row.get("session_date")) == as_of_session
        }
        status = {m: self._status_for(m, as_of_session, decision_as_of) for m in markets}
        coverage_flags = {m: self._has_status_coverage(m, as_of_session) for m in markets}
        actions = {m: self._actions_for(m, as_of_session) for m in markets}
        action_covered = self._has_action_coverage(as_of_session)

        states: list[SecurityState] = []
        for interval in self._universe(prices, markets):
            market = interval["market"]
            if market not in markets:
                continue
            symbol = interval["symbol"]
            if wanted and symbol not in wanted:
                continue

            reasons: list[str] = []
            session_state = session_states.get(market, "unknown")

            listing = interval.get("listing_date") or ""
            delisting = interval.get("delisting_date") or ""
            if interval.get("lifecycle_state") == "absent":
                # The exchange quoted this security and the lifecycle source
                # has never heard of it. Refusing to say anything is the one
                # thing that must not happen: it is how 11,350 official price
                # rows left the dataset without a trace.
                membership = "unknown"
                reasons.append("not-in-lifecycle-source")
            elif not listing:
                membership = "unknown"
                reasons.append("listing-date-missing-at-source")
            elif as_of_session < listing:
                membership = "not-yet-listed"
            elif delisting and as_of_session >= delisting:
                membership = "delisted"
            else:
                membership = "listed"

            price_row = prices.get((market, symbol))
            if session_state != "official-open":
                price_state = "not-a-session"
            elif price_row is None:
                # The session happened and a closing table was published, yet
                # this security is absent from it. Under D8 that is treated as
                # not normally traded, and it is a policy inference, not a fact.
                price_state = "absent-from-official-table"
                reasons.append("suspension-inferred-from-price-absence")
            else:
                ohlc = _iso(price_row.get("ohlc_state"))
                price_state = ohlc or "unknown"

            if not coverage_flags[market]:
                status_state = "no-coverage"
                reasons.append("market-status-not-covered-for-this-date")
            else:
                events = status[market].get(symbol, [])
                if not events:
                    status_state = "no-event-in-covered-window"
                else:
                    kinds = sorted({str(e.get("event_kind")) for e in events})
                    status_state = "+".join(kinds)
                    reasons.extend(f"status-{k}" for k in kinds)
                    if any(e.get("altered_trading") for e in events):
                        reasons.append("status-altered-trading")

            if not action_covered:
                action_state = "no-coverage"
                reasons.append("corporate-actions-not-covered-for-this-date")
            else:
                effective = actions[market].get(symbol, [])
                if not effective:
                    action_state = "no-action"
                else:
                    kinds = sorted(
                        {str(a.get("action_type") or "unspecified") for a in effective}
                    )
                    action_state = "+".join(kinds)
                    reasons.extend(f"action-{k}" for k in kinds)
                    # The close on an ex-date is quoted on a different basis
                    # from the previous close. A strategy that differences them
                    # without adjusting reads the distribution as a loss.
                    reasons.append("price-not-comparable-to-previous-close")
                    if not any(
                        _iso(a.get("announced_at")) and _iso(a.get("announced_at")) < as_of_session
                        for a in effective
                    ):
                        # Either the publisher gave no announcement date or it
                        # gave one no earlier than the effect. Nobody could
                        # have positioned for this in advance.
                        reasons.append("action-not-announced-in-advance")

            # Fail closed: eligible only when every input is positively known.
            board, board_market = self.board_as_of(symbol, as_of_session)
            out_of_scope = OUT_OF_SCOPE_BOARDS.get(board)
            if board_market in ("before-first-listing", "after-last-listing"):
                # The master carries this security and puts it on no board
                # that session. Saying so beats `unknown`, which is what a
                # symbol-keyed lookup used to return for the TWSE leg of a
                # security that had already moved to TPEx.
                tradability = "ineligible"
                reasons.append(
                    "not-yet-on-any-board"
                    if board_market == "before-first-listing"
                    else "off-every-board"
                )
            elif board_market and board_market != market:
                tradability = "ineligible"
                reasons.append("not-on-this-market-this-session")
            elif out_of_scope:
                # Owner decision D1, 2026-08-21: boards other than 上市 and
                # 上櫃 are out of M0 scope. Stated as a verdict with a reason
                # rather than left out, because an absence reads exactly like
                # the export bug this replaced. Decided on the board the
                # security was on that session, from dated vendor fields --
                # its board today is a different question.
                tradability = "ineligible"
                reasons.append(out_of_scope)
            elif not self.in_company_master(symbol) and symbol.startswith("00"):
                # Owner decision D3: quoted, but no company behind it. Both
                # signals are required -- absence alone would silently drop a
                # real company the vendor happened to miss, which is the exact
                # failure that hid 3202.
                tradability = "ineligible"
                reasons.append("out-of-scope-etf-or-etn")
            elif session_state != "official-open":
                # Ahead of the membership checks, because a market that did
                # not open is a fact and beats any gap in what we know about
                # the security. Reaching `unknown` here would trade a definite
                # refusal for a vague one.
                tradability = "ineligible"
            elif membership == "unknown":
                tradability = "unknown"
            elif membership in {"not-yet-listed", "delisted"}:
                tradability = "ineligible"
            elif price_state == "absent-from-official-table":
                tradability = "blocked"
            elif status_state == "no-coverage" or action_state == "no-coverage":
                tradability = "unknown"
            elif price_state != "complete":
                tradability = "blocked"
                reasons.append("incomplete-ohlc")
            elif status_state != "no-event-in-covered-window":
                tradability = "restricted"
            else:
                tradability = "eligible"

            states.append(
                SecurityState(
                    security_instance_id=interval["security_instance_id"],
                    market=market,
                    symbol=symbol,
                    membership_state=membership,
                    session_state=session_state,
                    market_status_state=status_state,
                    price_state=price_state,
                    corporate_action_state=action_state,
                    tradability_state=tradability,
                    reason_codes=tuple(sorted(set(reasons))),
                    lineage=tuple(
                        x for x in [str((price_row or {}).get("record_id") or "")] if x
                    ),
                )
            )

        states.sort(key=lambda s: (s.market, s.symbol))
        payload = {
            "interface": INTERFACE_VERSION,
            "as_of_session": as_of_session,
            "decision_as_of": decision_as_of,
            "markets": list(markets),
            "dataset_id": self.dataset_id,
            "states": [
                [
                    s.market,
                    s.symbol,
                    s.membership_state,
                    s.tradability_state,
                    s.corporate_action_state,
                ]
                for s in states
            ],
        }
        return ReconstructionResult(
            as_of_session=as_of_session,
            decision_as_of=decision_as_of,
            markets=markets,
            dataset_id=self.dataset_id,
            session_states=session_states,
            securities=tuple(states),
            coverage={
                "session_states": session_states,
                "status_coverage": coverage_flags,
                "corporate_action_coverage": action_covered,
                "corporate_action_window": list(self._action_window),
                "securities_considered": len(states),
            },
            output_hash=_sha(payload),
        )


def default_warehouse() -> Warehouse:
    """The current build, read from one place rather than pinned here.

    These were three literals naming the 2025-2026 generation. Every caller
    that took the default -- the as-of reconstruction itself among them --
    would have gone on answering questions from the previous warehouse after
    the six-year rebuild, and answered them successfully.
    """

    from current_build import CALENDAR, PRICES, STATUS

    return Warehouse(CALENDAR, PRICES, STATUS)
