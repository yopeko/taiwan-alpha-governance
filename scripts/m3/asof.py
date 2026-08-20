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


@dataclass(frozen=True)
class SecurityState:
    security_instance_id: str
    market: str
    symbol: str
    membership_state: str
    session_state: str
    market_status_state: str
    price_state: str
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
        self._status = self._parquet(self.status_root / "market_status_pit.parquet")
        self._coverage = self._parquet(self.status_root / "market_status_coverage.parquet")
        self.dataset_id = self._dataset_id()

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

        states: list[SecurityState] = []
        for interval in self._intervals:
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
            if not listing:
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

            # Fail closed: eligible only when every input is positively known.
            if membership == "unknown":
                tradability = "unknown"
            elif membership in {"not-yet-listed", "delisted"}:
                tradability = "ineligible"
            elif session_state != "official-open":
                tradability = "ineligible"
            elif price_state == "absent-from-official-table":
                tradability = "blocked"
            elif status_state == "no-coverage":
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
                [s.market, s.symbol, s.membership_state, s.tradability_state]
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
                "securities_considered": len(states),
            },
            output_hash=_sha(payload),
        )


def default_warehouse() -> Warehouse:
    return Warehouse(
        Path(r"C:\tmp\tw-alpha-m3-pit-01"),
        Path(r"C:\tmp\tw-alpha-m3-pit-prices-05"),
        Path(r"C:\tmp\tw-alpha-m3-pit-status-08"),
    )
