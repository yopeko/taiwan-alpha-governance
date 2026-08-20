"""M3.4: build `daily_prices_pit` and `corporate_actions_pit`.

Reads the M3.2 staging layer and emits the price and corporate-action
point-in-time tables.

The rules this build exists to enforce, all from the PIT contract §6.4/§6.6:

* **A missing OHLC stays missing.** No forward fill, no carrying yesterday's
  close. `ohlc_state` records *why* it is absent, because "the exchange
  published no regular OHLC" and "we never observed this security" are
  different facts with different consequences.

* **Activity is not tradability.** A row with turnover but no OHLC is
  recorded as exactly that. Deciding whether it could have been traded is
  M3.6's job, using market status as well.

* **An action is usable only once it was announced.** `announced_at` is kept
  separate from the effective date, and where the publisher gives no
  announcement date the row is marked so a later stage cannot quietly assume
  the effective date was knowable in advance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_ID = "tw-alpha-m3-prices-actions/1.0.0"
PRICE_SOURCES = {"TWSE-PRICE-HIST": "TWSE", "TPEX-PRICE-HIST": "TPEX"}
ACTION_SOURCES = {"TWSE-ACTIONS-HIST": "TWSE"}
# TPEx publishes no range-based ex-right history; its official route is one
# MOPS document per announcement, so it arrives as details rather than a
# table and is promoted from a different source id.
ACTION_DETAIL_SOURCES = {"MOPS-TPEX-ACTIONS-DETAIL": "TPEX"}
# TWT49U publishes the ex-rights calculation but no announcement date, so
# every TWSE row it produces is unusable point-in-time on its own. The date
# comes from the licensed-vendor lane, which contributes that one field and
# never defines which events exist.
RAW_V2 = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
TEJ_DIVIDEND_LANE = RAW_V2 / "m3_tej_dividends_2026-08-19"
WINDOW = (date(2025, 1, 1), date(2026, 8, 3))

OHLC_COMPLETE = "complete"
OHLC_SOURCE_NO_REGULAR = "source-reported-no-regular-ohlc"
OHLC_ACTIVITY_ONLY = "activity-without-ohlc"
OHLC_ABSENT = "no-price-fields-published"


def sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_index(staging: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (staging / "staging_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_manifest_index(staging: Path) -> dict[str, Path]:
    return {
        manifest.parent.name: manifest
        for manifest in (staging / "parsed_observations").rglob("parse_manifest.json")
    }


def parsed_rows(manifest_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    manifest = json.loads(manifest_path.read_bytes())
    rows_path = manifest.get("rows_path")
    if not rows_path:
        return [], []
    table = pq.read_table(manifest_path.parent / str(rows_path))
    return table.to_pylist(), list(table.column_names)


def first_present(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def classify_ohlc(row: dict[str, Any]) -> str:
    ohlc = [
        first_present(row, "open", "open_price"),
        first_present(row, "high", "high_price"),
        first_present(row, "low", "low_price"),
        first_present(row, "close", "close_price"),
    ]
    if all(value is not None for value in ohlc):
        return OHLC_COMPLETE
    activity = first_present(row, "volume", "trade_volume", "turnover", "trade_value")
    if activity not in (None, "", 0, "0"):
        return OHLC_ACTIVITY_ONLY
    if any(value is not None for value in ohlc):
        return OHLC_SOURCE_NO_REGULAR
    return OHLC_ABSENT


def build_prices(staging: Path, index: list[dict[str, Any]], manifests: dict[str, Path]):
    rows: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    columns_seen: set[str] = set()
    lo, hi = WINDOW
    for record in index:
        market = PRICE_SOURCES.get(record["source_id"])
        if not market:
            continue
        period = str(record["logical_period"])
        if not period.startswith("session:"):
            continue
        session = date.fromisoformat(period.split(":", 1)[1])
        if not (lo <= session <= hi):
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        source_rows, columns = parsed_rows(manifest_path)
        columns_seen.update(columns)
        for ordinal, source_row in enumerate(source_rows):
            symbol = str(first_present(source_row, "symbol", "security_id", "code") or "").strip()
            if not symbol:
                continue
            state = classify_ohlc(source_row)
            state_counts[state] = state_counts.get(state, 0) + 1
            rows.append(
                {
                    "market": market,
                    "session_date": session.isoformat(),
                    "symbol": symbol,
                    "open": first_present(source_row, "open", "open_price"),
                    "high": first_present(source_row, "high", "high_price"),
                    "low": first_present(source_row, "low", "low_price"),
                    "close": first_present(source_row, "close", "close_price"),
                    "volume": first_present(source_row, "volume", "trade_volume"),
                    "turnover": first_present(source_row, "turnover", "trade_value"),
                    "ohlc_state": state,
                    "activity_scope": "regular-session",
                    "price_basis": "raw-official-unadjusted",
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "quality_run_id": record.get("quality_run_id") or "",
                    "quality_decision": record.get("quality_decision") or "",
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    for row in rows:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("market", "session_date", "symbol", "snapshot_id")}
        )
    rows.sort(key=lambda r: (r["session_date"], r["market"], r["symbol"]))
    return rows, state_counts, sorted(columns_seen)


# The TPEx detail observation is addressed by the announcement it came from,
# and that is the only place its announcement date survives: the parsed
# document itself carries the ex-date and the amounts but not the date the
# announcement was published.
TPEX_DETAIL_PERIOD = re.compile(
    r"company:TPEX:(?P<symbol>\d{4,6}):announced:(?P<announced>\d{4}-\d{2}-\d{2})"
)

# What makes two rows the same corporate action. Deliberately includes the
# amounts: an announcement that restates the same ex-date with a different
# dividend is a revision, not a duplicate, and both must survive.
CONTENT_KEY = (
    "market",
    "symbol",
    "effective_date",
    "action_type",
    "cash_dividend",
    "stock_dividend_ratio",
)


def _action_row(
    record: dict[str, Any],
    market: str,
    symbol: str,
    source_row: dict[str, Any],
    ordinal: int,
    announced: str,
) -> dict[str, Any]:
    effective = first_present(source_row, "action_date", "ex_date", "date")
    return {
        "market": market,
        "symbol": symbol,
        "effective_date": str(effective) if effective else "",
        "announced_at": announced,
        # Without a publisher announcement date the earliest defensible
        # knowledge time is our own first observation.
        "availability_basis": (
            "publisher-exact" if announced else "first-observed-only"
        ),
        "action_type": first_present(source_row, "action_type"),
        "cash_dividend": first_present(source_row, "cash_dividend"),
        "stock_dividend_ratio": first_present(source_row, "stock_dividend_ratio"),
        "rights_ratio": first_present(source_row, "rights_ratio"),
        "subscription_price": first_present(source_row, "subscription_price"),
        "reference_price": first_present(
            source_row, "reference_price", "ex_reference_price"
        ),
        "prior_close": first_present(source_row, "prior_close", "pre_close"),
        "adjustment_factor": first_present(source_row, "adjustment_factor"),
        "limit_up": first_present(source_row, "limit_up", "limit_up_price"),
        "limit_down": first_present(source_row, "limit_down", "limit_down_price"),
        # TWSE publishes the reference price it used; TPEx publishes only the
        # dividend, so the two markets are not adjusted from the same evidence
        # and the difference must stay visible to whoever adjusts prices.
        "adjustment_evidence": (
            "publisher-reference-price"
            if first_present(source_row, "reference_price", "ex_reference_price")
            else "publisher-dividend-amount-only"
        ),
        "availability_reason": (
            "publisher-announcement-date" if announced else "publisher-supplies-none"
        ),
        "announcement_evidence_state": (
            "verified-snapshot" if announced else "missing-at-source"
        ),
        "source_id": record["source_id"],
        "snapshot_id": record["snapshot_id"],
        "parse_run_id": record["parse_run_id"],
        "evidence_tier": record["evidence_tier"],
        "evidence_state": "verified-snapshot",
        "source_row_ordinal": ordinal,
    }


def collapse_actions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per distinct action, announced as early as the publisher did.

    The same MOPS announcement is reachable from more than one listing, and a
    company may re-announce identical terms several times before the ex-date.
    Keeping every copy would multiply one dividend into several; keeping the
    latest announcement would claim the terms became knowable later than they
    did. The earliest announcement of identical content is the correct one.
    """

    best: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row[field]) for field in CONTENT_KEY)
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        # An empty announcement date must not win by sorting first.
        if row["announced_at"] and (
            not current["announced_at"] or row["announced_at"] < current["announced_at"]
        ):
            best[key] = row
    return list(best.values())


def build_reduction_actions(index: list[dict[str, Any]], manifests: dict[str, Path]):
    """A capital reduction restates the price, so it is also an action.

    The halt belongs in `market_status_pit` as an interval; this is the other
    half of the same event. On the resumption session the exchange publishes a
    new reference price, computed on the new share count, together with the
    limits it set around it — the same three facts an ex-rights row carries,
    and they belong in the same columns.

    Without this row a price adjuster looking at corporate actions sees nothing
    on the day a security's price legitimately jumps, and the standard limit
    rule applied to the pre-halt close is wrong on every reduction.
    """

    # Imported rather than reimplemented: how a listing row names its own
    # announcement document is one rule, and two copies of it would drift.
    from build_status_fundamentals import (  # noqa: E402
        REDUCTION_SOURCES,
        _detail_key,
        reduction_details,
    )

    def number(value: Any) -> float | None:
        """The reduction parser keeps published prices as exact text.

        This table stores them as doubles, so the conversion happens here and
        anything that is not a plain decimal becomes null rather than a
        coerced approximation.
        """

        if value is None:
            return None
        text = str(value).strip()
        if not re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,6})?", text):
            return None
        return float(text)

    details = reduction_details(index, manifests)
    rows: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] not in REDUCTION_SOURCES:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        source_rows, _columns = parsed_rows(manifest_path)
        for ordinal, source_row in enumerate(source_rows):
            if source_row.get("record_kind") != "resumption":
                continue
            resumption = str(source_row.get("resumption_date") or "")
            reference = source_row.get("resumption_reference_price")
            if not resumption or reference in (None, ""):
                continue
            key = _detail_key(source_row)
            detail = details.get(key) if key else None
            halt = str(detail.get("halt_date") or "") if detail else ""
            announced = key[1] if key else ""
            # Same ordering guard as the status table: an announcement that
            # does not precede its own halt means the join is wrong.
            if not (announced and halt and announced <= halt < resumption):
                announced = ""
            rows.append(
                {
                    "market": "TWSE",
                    "symbol": str(source_row["symbol"]),
                    "effective_date": resumption,
                    "announced_at": announced,
                    "availability_basis": (
                        "publisher-exact" if announced else "unknown-blocked"
                    ),
                    "action_type": "capital_reduction",
                    "cash_dividend": None,
                    "stock_dividend_ratio": None,
                    "rights_ratio": None,
                    "subscription_price": None,
                    "reference_price": number(reference),
                    "prior_close": number(source_row.get("prior_close")),
                    "adjustment_factor": None,
                    "limit_up": number(source_row.get("limit_up")),
                    "limit_down": number(source_row.get("limit_down")),
                    "adjustment_evidence": "publisher-resumption-reference-price",
                    "availability_reason": (
                        "publisher-announcement-date"
                        if announced
                        else "publisher-supplies-none"
                    ),
                    "announcement_evidence_state": (
                        "verified-snapshot" if announced else "missing-at-source"
                    ),
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    return rows


def build_par_value_actions(index: list[dict[str, Any]], manifests: dict[str, Path]):
    """A par-value change restates the price too, and by the largest factor.

    Splitting the shares ten for one divides the price by ten. Without this row
    the price table shows a ninety percent fall with no cause, which is both
    the largest fabricated loss a backtest can inherit and the easiest to
    mistake for a real collapse.

    No announcement date exists in either published table, so these rows are
    `unknown-blocked`: usable for explaining what happened, not for deciding
    what was knowable.
    """

    from build_status_fundamentals import PAR_VALUE_SOURCES  # noqa: E402

    def number(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,6})?", text):
            return None
        return float(text)

    rows: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] not in PAR_VALUE_SOURCES:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        source_rows, _columns = parsed_rows(manifest_path)
        for ordinal, source_row in enumerate(source_rows):
            if source_row.get("record_kind") != "resumption":
                continue
            resumption = str(source_row.get("resumption_date") or "")
            reference = source_row.get("resumption_reference_price")
            if not resumption or reference in (None, ""):
                continue
            rows.append(
                {
                    "market": "TWSE",
                    "symbol": str(source_row["symbol"]),
                    "effective_date": resumption,
                    "announced_at": "",
                    "availability_basis": "unknown-blocked",
                    "action_type": "par_value_change",
                    "cash_dividend": None,
                    "stock_dividend_ratio": None,
                    "rights_ratio": None,
                    "subscription_price": None,
                    "reference_price": number(reference),
                    "prior_close": number(source_row.get("prior_close")),
                    "adjustment_factor": None,
                    "limit_up": number(source_row.get("limit_up")),
                    "limit_down": number(source_row.get("limit_down")),
                    "adjustment_evidence": "publisher-resumption-reference-price",
                    # Not a conditional: neither TWSE par-value table carries an
                    # announcement date, and the forecast detail serves only
                    # pending changes, so for history there is nothing to have.
                    "availability_reason": "publisher-supplies-none",
                    "announcement_evidence_state": "missing-at-source",
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    return rows



def tej_dividend_announcements() -> dict[tuple[str, str], str]:
    """(symbol, ex-date) -> announcement date, from the licensed-vendor lane.

    The vendor supplies one field. It does not get to say which corporate
    actions happened: comparison in M3.9 found 109 events the exchange
    published and TEJ does not carry, so joining the other way round would
    delete them without a trace.

    Where the vendor holds more than one announcement for the same ex-date the
    earliest is taken, for the same reason the official actions are collapsed
    that way: identical terms announced twice were knowable from the first.
    """

    out: dict[tuple[str, str], str] = {}
    if not TEJ_DIVIDEND_LANE.is_dir():
        return out
    for manifest_path in TEJ_DIVIDEND_LANE.rglob("import_manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("module") != "dividend-announcement":
            continue
        table = manifest_path.parent / "normalized" / "rows.parquet"
        if not table.is_file():
            continue
        for row in pq.read_table(table).to_pylist():
            symbol = str(row.get("symbol") or "").strip()
            ex_date = str(row.get("ex_date") or "").strip()
            announced = str(row.get("announce_date") or "").strip()
            if not (symbol and ex_date and announced):
                continue
            key = (symbol, ex_date)
            if key not in out or announced < out[key]:
                out[key] = announced
    return out


def apply_announcements(
    rows: list[dict[str, Any]], announcements: dict[tuple[str, str], str]
) -> dict[str, int]:
    """Fill in the announcement date TWT49U omits, with three explicit outcomes.

    * `publisher-exact` — the vendor's date precedes the ex-date, so the action
      was knowable in advance.
    * `unknown-blocked` — the vendor's date is on or after the ex-date. The
      action is real but nobody could have acted on it before it happened, so
      it is kept and never made usable.
    * `first-observed-only` — the vendor has no row for this official event.
      First observation is the capture date, which is after every date in the
      window, so these remain unusable at any historical cutoff.

    Only rows that arrived without a date are touched. A row that already
    carries one got it from its own publisher, and a vendor must not overwrite
    the publisher.
    """

    counts: dict[str, int] = {}
    for row in rows:
        if row["announced_at"] or row["source_id"] != "TWSE-ACTIONS-HIST":
            continue
        announced = announcements.get((row["symbol"], row["effective_date"]), "")
        if not announced:
            reason = "no-vendor-row-for-this-official-event"
            basis = "first-observed-only"
        elif announced >= row["effective_date"]:
            reason = "announcement-not-earlier-than-effect"
            basis = "unknown-blocked"
            row["announced_at"] = announced
        else:
            reason = "vendor-announcement-precedes-effect"
            basis = "publisher-exact"
            row["announced_at"] = announced
        row["availability_basis"] = basis
        row["availability_reason"] = reason
        row["announcement_evidence_state"] = (
            "licensed-vendor-snapshot" if announced else "missing-at-source"
        )
        counts[basis] = counts.get(basis, 0) + 1
    return counts


def build_tpex_announcement_actions(index: list[dict[str, Any]], manifests: dict[str, Path]):
    """TPEx reductions and par-value changes as price-restatement rows.

    The announcement states the exchange ratio but not the reference price the
    exchange set on resumption — TPEx publishes that only for the next few
    days, so for history it does not exist. The ratio alone does not determine
    the reference price, so `adjustment_evidence` says so rather than letting a
    consumer assume a full adjustment basis is present.
    """

    from build_status_fundamentals import (  # noqa: E402
        TPEX_ANNOUNCEMENT_DETAIL_SOURCE,
    )

    rows: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] != TPEX_ANNOUNCEMENT_DETAIL_SOURCE:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        source_rows, _columns = parsed_rows(manifest_path)
        for ordinal, source_row in enumerate(source_rows):
            kind = str(source_row.get("change_kind") or "")
            if kind not in ("capital-reduction", "par-value-change"):
                continue
            symbol = str(source_row.get("symbol") or "")
            announced = str(source_row.get("announced_at") or "")
            halt = str(source_row.get("halt_from") or "")
            resumption = str(source_row.get("resumption_date") or "")
            if not (symbol and halt and resumption):
                continue
            usable = bool(announced and announced <= halt < resumption)
            per_share = source_row.get("shares_per_old_share")
            per_thousand = source_row.get("shares_per_thousand_old_shares")
            rows.append(
                {
                    "market": "TPEX",
                    "symbol": symbol,
                    "effective_date": resumption,
                    "announced_at": announced if usable else "",
                    "availability_basis": (
                        "publisher-exact" if usable else "unknown-blocked"
                    ),
                    "action_type": kind.replace("-", "_"),
                    "cash_dividend": None,
                    "stock_dividend_ratio": None,
                    "rights_ratio": None,
                    "subscription_price": None,
                    "reference_price": None,
                    "prior_close": None,
                    # Stated per share by par-value changes and per thousand by
                    # reductions; recorded in the unit the publisher used.
                    "adjustment_factor": (
                        float(per_share)
                        if per_share
                        else (float(per_thousand) / 1000 if per_thousand else None)
                    ),
                    "limit_up": None,
                    "limit_down": None,
                    "adjustment_evidence": "publisher-exchange-ratio-only",
                    "availability_reason": (
                        "publisher-announcement-date"
                        if announced
                        else "publisher-supplies-none"
                    ),
                    "announcement_evidence_state": (
                        "verified-snapshot" if announced else "missing-at-source"
                    ),
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    return rows


def build_actions(staging: Path, index: list[dict[str, Any]], manifests: dict[str, Path]):
    rows: list[dict[str, Any]] = build_reduction_actions(index, manifests)
    rows += build_par_value_actions(index, manifests)
    rows += build_tpex_announcement_actions(index, manifests)
    for record in index:
        market = ACTION_SOURCES.get(record["source_id"])
        detail_market = ACTION_DETAIL_SOURCES.get(record["source_id"])
        if not market and not detail_market:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue

        period_match = (
            TPEX_DETAIL_PERIOD.fullmatch(str(record["logical_period"]))
            if detail_market
            else None
        )
        source_rows, _columns = parsed_rows(manifest_path)
        for ordinal, source_row in enumerate(source_rows):
            symbol = str(first_present(source_row, "symbol", "security_id", "code") or "").strip()
            if not symbol:
                continue
            if detail_market:
                # A document whose code differs from the key it was requested
                # under would attach one company's dividend to another.
                if period_match is None or period_match.group("symbol") != symbol:
                    continue
                announced = period_match.group("announced")
                emit_market = detail_market
            else:
                published = first_present(source_row, "announced_at", "announcement_date")
                announced = str(published) if published else ""
                emit_market = market
            rows.append(
                _action_row(record, emit_market, symbol, source_row, ordinal, announced)
            )

    rows = collapse_actions(rows)
    vendor_counts = apply_announcements(rows, tej_dividend_announcements())
    for row in rows:
        row["record_id"] = sha(
            {
                k: str(row[k])
                for k in ("market", "symbol", "effective_date", "announced_at", "snapshot_id")
            }
        )
    rows.sort(key=lambda r: (r["effective_date"], r["market"], r["symbol"], r["announced_at"]))

    # A slot holding more than one row is a restatement, numbered so a caller
    # can take the newest version announced by its own cutoff rather than
    # silently receiving two answers.
    slots: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        slots.setdefault(
            (row["market"], row["symbol"], row["effective_date"]), []
        ).append(row)
    revised = 0
    for group in slots.values():
        if len(group) > 1:
            revised += 1
        for ordinal, row in enumerate(sorted(group, key=lambda r: r["announced_at"])):
            row["revision_ordinal"] = ordinal

    stats = {
        "vendor_announcement_outcomes": dict(sorted(vendor_counts.items())),
        "missing_announcement_date": sum(1 for r in rows if not r["announced_at"]),
        "announced_after_effective_date": sum(
            1
            for r in rows
            if r["announced_at"] and r["effective_date"]
            and r["announced_at"] > r["effective_date"]
        ),
        "restated_slots": revised,
    }
    return rows, stats


def write(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        [{k: (None if v == "" else v) for k, v in row.items()} for row in rows]
    )
    pq.write_table(table, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(staging_root: Path, out_root: Path) -> dict[str, Any]:
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")
    index = load_index(staging_root)
    manifests = parse_manifest_index(staging_root)

    prices, ohlc_states, columns = build_prices(staging_root, index, manifests)
    actions, action_stats = build_actions(staging_root, index, manifests)

    price_sha = write(out_root / "daily_prices_pit.parquet", prices)
    action_sha = write(out_root / "corporate_actions_pit.parquet", actions)

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "staging_dataset_id": json.loads(
            (staging_root / "dataset_manifest.json").read_bytes()
        )["dataset_id"],
        "window": {"start": WINDOW[0].isoformat(), "end": WINDOW[1].isoformat()},
        "daily_prices_pit": {
            "rows": len(prices),
            "sha256": price_sha,
            "ohlc_state_counts": dict(sorted(ohlc_states.items())),
            "distinct_sessions": len({r["session_date"] for r in prices}),
            "distinct_symbols": len({(r["market"], r["symbol"]) for r in prices}),
            "source_columns_seen": columns,
        },
        "corporate_actions_pit": {
            "rows": len(actions),
            "sha256": action_sha,
            **action_stats,
            "distinct_symbols": len({(r["market"], r["symbol"]) for r in actions}),
            "markets": sorted({r["market"] for r in actions}),
            "rows_by_market": {
                market: sum(1 for r in actions if r["market"] == market)
                for market in sorted({r["market"] for r in actions})
            },
            "publisher_exact": sum(
                1 for r in actions if r["availability_basis"] == "publisher-exact"
            ),
        },
        "notes": [
            "Prices are raw official and unadjusted; no adjusted series is "
            "derived here, and none may be without a documented method.",
            "Missing OHLC is preserved with a reason and never filled.",
            "TPEx actions come from MOPS announcement documents, which give "
            "the dividend but no reference price; `adjustment_evidence` "
            "records which of the two the row rests on.",
            "A slot with several rows is a restatement; take the highest "
            "`revision_ordinal` whose `announced_at` is within the cutoff.",
        ],
    }
    (out_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.staging_root, args.out_root), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
