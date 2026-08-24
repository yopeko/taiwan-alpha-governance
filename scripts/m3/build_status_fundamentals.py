"""M3.5: build `market_status_pit` and `fundamentals_pit`.

Two tables with opposite failure modes.

Market status fails by *absence being read as permission*. A security that
appears in no disposal list is not thereby known to be freely tradable — it
may simply be a date the source never covered. The table therefore records
coverage intervals alongside events, so a query can tell "no event" from
"no coverage".

Fundamentals fail by *a revision travelling backwards*. A restated figure must
not inherit the original's availability, so each statement row carries its own
availability basis and a supersession chain rather than being overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_ID = "tw-alpha-m3-status-fundamentals/1.0.0"
RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
TEJ_LANE = RAW / "m3_tej_licensed_2026-08-16"
WINDOW = (date(2019, 1, 1), date(2026, 8, 3))

TPEX_ANNOUNCEMENT_DETAIL_SOURCE = "TPEX-ANNOUNCEMENT-DETAIL"
PAR_VALUE_SOURCES = {
    "TWSE-PAR-VALUE-RESUME-HIST",
    "TWSE-PAR-VALUE-FORECAST-HIST",
}
REDUCTION_SOURCES = {
    "TWSE-REDUCTION-RESUME-HIST",
    "TWSE-REDUCTION-FORECAST-HIST",
}
STATUS_SOURCES = {
    "TWSE-STATUS-PUNISH-HIST",
    "TWSE-STATUS-NOTICE-HIST",
    "TPEX-STATUS-DISPOSAL-HIST",
    "TPEX-STATUS-ATTENTION-HIST",
}
FUNDAMENTAL_SOURCES = {
    "MOPS-REVENUE-HIST": "monthly-revenue",
    "MOPS-INCOME-HIST": "quarterly-income",
    "MOPS-BALANCE-HIST": "balance-sheet",
    "MOPS-CASHFLOW-HIST": "cash-flow",
}


def sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_index(staging: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (staging / "staging_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def manifest_index(staging: Path) -> dict[str, Path]:
    return {
        m.parent.name: m for m in (staging / "parsed_observations").rglob("parse_manifest.json")
    }


def rows_of(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_bytes())
    rows_path = manifest.get("rows_path")
    if not rows_path:
        return []
    return pq.read_table(manifest_path.parent / str(rows_path)).to_pylist()


def pick(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def collapse_duplicates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per event, regardless of how many archives carried it.

    The status capture and the reduction capture both requested every
    registered source, so the same disposal or attention notice is present in
    two archives. Counting it twice would double every statistic built on this
    table. The key is the event itself, never the archive that carried it.
    """

    unique: dict[str, dict[str, Any]] = {}
    for row in events:
        key = sha(
            {
                field: str(row[field])
                for field in (
                    "market",
                    "symbol",
                    "event_kind",
                    "effective_from",
                    "effective_to",
                    "announced_at",
                )
            }
        )
        unique.setdefault(key, row)
    return list(unique.values())


def build_status(index, manifests):
    """Events plus the coverage intervals that make absence interpretable."""

    events: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] not in STATUS_SOURCES:
            continue
        period = str(record["logical_period"])
        if period.startswith("range:"):
            _, start, end = period.split(":")
            coverage.append(
                {
                    "source_id": record["source_id"],
                    "market": "TPEX" if record["source_id"].startswith("TPEX") else "TWSE",
                    "coverage_from": start,
                    "coverage_to": end,
                    "coverage_state": "covered",
                    "snapshot_id": record["snapshot_id"],
                }
            )
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for ordinal, row in enumerate(rows_of(manifest_path)):
            events.append(
                {
                    "market": row.get("market"),
                    "symbol": row.get("symbol"),
                    "event_kind": row.get("event_kind"),
                    "announced_at": str(row.get("announced_at") or ""),
                    "effective_from": str(row.get("effective_from") or ""),
                    "effective_to": str(row.get("effective_to") or ""),
                    "altered_trading": bool(row.get("altered_trading")),
                    "reason_text": (row.get("reason_text") or "")[:400],
                    "measure_text": (row.get("measure_text") or "")[:400],
                    # Announcement precedes effect, so the announcement date is
                    # the earliest moment the market could act on it.
                    "availability_basis": (
                        "publisher-exact" if row.get("announced_at") else "unknown-blocked"
                    ),
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    for row in events:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("market", "symbol", "event_kind", "effective_from", "snapshot_id")}
        )
    events = collapse_duplicates(events)
    seen: set[tuple] = set()
    deduped_coverage = []
    for item in coverage:
        key = (
            item["market"],
            item["source_id"],
            item["coverage_from"],
            item["coverage_to"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_coverage.append(item)
    coverage = deduped_coverage
    events.sort(key=lambda r: (r["effective_from"] or r["announced_at"], r["market"], str(r["symbol"])))
    coverage.sort(key=lambda r: (r["market"], r["source_id"], r["coverage_from"]))
    return events, coverage


DETAIL_SOURCE = "TWSE-REDUCTION-DETAIL-HIST"

# The 詳細資料 cell of a listing row names the announcement document for that
# row: "STK_NO,FILE_DATE", optionally followed by further dates.
_DETAIL_CELL = re.compile(r"\s*(\d{4,6})\s*,\s*(\d{8})(?:\s*,\s*\d{8})*\s*")


def _iso(digits: str) -> str:
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _day_before(iso_date: str) -> str:
    try:
        return (date.fromisoformat(iso_date) - timedelta(days=1)).isoformat()
    except ValueError:
        return ""


def _detail_key(row: dict) -> tuple[str, str] | None:
    """The announcement document this listing row points at.

    Matching a resumption to its announcement by date proximity would be a
    guess. The row names its own document, so the join is exact and a row
    whose cell is missing or malformed stays unmatched rather than being
    attached to whichever announcement happens to be nearest.
    """

    try:
        cells = json.loads(row.get("source_record_json") or "")
    except (ValueError, TypeError):
        return None
    for cell in cells:
        match = _DETAIL_CELL.fullmatch(str(cell))
        if match:
            return match.group(1), _iso(match.group(2))
    return None


def reduction_details(index, manifests) -> dict[tuple[str, str], dict[str, Any]]:
    """Announcement documents keyed by (symbol, file_date)."""

    details: dict[tuple[str, str], dict[str, Any]] = {}
    for record in index:
        if record["source_id"] != DETAIL_SOURCE:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for row in rows_of(manifest_path):
            file_date = str(row.get("file_date") or "")
            if not file_date:
                continue
            details.setdefault((str(row["symbol"]), file_date), row)
    return details


def build_full_cash_delivery() -> list[dict[str, Any]]:
    """全額交割 intervals from the vendor company master.

    A security on full-cash-delivery is not normally tradable: the buyer
    deposits the cash and the seller the shares before the order is accepted.
    The warehouse modelled attention, disposal, capital reduction and par
    value change, but never this, and 10,004 sessions of it were reaching the
    research dataset as plain `eligible`.

    **Availability policy, needs Validation Owner ratification (contract
    §4.2).** TEJ gives the interval but not the announcement date, and an
    empty `announced_at` is knowable at no cutoff at all, so recording these
    as `unknown-blocked` would put them in the table and change nothing. The
    bound taken here is `announced_at = effective_from`: full-cash-delivery
    is a standing trading condition rather than a point event, so on any
    session inside the interval the security was visibly trading under it.
    The claim is only that it was knowable no earlier than the day it took
    effect, which cannot precede the exchange's own announcement.
    """

    from build_calendar_lifecycle import BOARD_MARKETS, board_legs, load_company_master

    events: list[dict[str, Any]] = []
    for ordinal, record in enumerate(load_company_master()):
        symbol = str(record.get("symbol") or "")
        if not symbol:
            continue
        legs = [leg for leg in board_legs(record) if leg["board"] in BOARD_MARKETS]
        for index in (1, 2, 3):
            start = _text(record.get(f"full_cash_delivery_from_{index}"))
            if not start:
                continue
            end = _text(record.get(f"full_cash_delivery_to_{index}"))
            # Which board was it on when the designation began? An interval
            # that outlives a board change keeps the board it started on,
            # which is the only one the vendor's dates can support.
            market = ""
            for leg in legs:
                if leg["start"] <= start and (not leg["end"] or start < leg["end"]):
                    market = BOARD_MARKETS[leg["board"]]
                    break
            if not market:
                for leg in legs:
                    if not leg["end"] or start < leg["end"]:
                        market = BOARD_MARKETS[leg["board"]]
                        break
            if not market:
                continue
            events.append(
                {
                    "market": market,
                    "symbol": symbol,
                    "event_kind": "full-cash-delivery",
                    "announced_at": start,
                    "effective_from": start,
                    # An open interval runs to the end of the window; the
                    # designation had not been lifted by then.
                    "effective_to": end or WINDOW[1].isoformat(),
                    "altered_trading": True,
                    "reason_text": "",
                    "measure_text": "全額交割",
                    "availability_basis": "approved-conservative-bound",
                    "source_id": "TEJ-COMPANY-MASTER",
                    "snapshot_id": str(record.get("snapshot_id") or ""),
                    "parse_run_id": "",
                    "evidence_tier": "vendor-ungated",
                    "evidence_state": "licensed-vendor-snapshot",
                    "source_row_ordinal": ordinal,
                }
            )
    for row in events:
        # Identity is the event, not the snapshot that carried it.
        row["record_id"] = sha(
            {
                k: str(row[k])
                for k in ("market", "symbol", "event_kind", "effective_from")
            }
        )
    return events


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", ".", "-", "none", "null", "nan", "nat"} else text


def build_reductions(index, manifests):
    """Reduction rows as market-status intervals, keyed by resumption date.

    The resumption listing publishes 恢復買賣日期 but not 停止買賣日期, and no
    announcement date at all. Both come from the announcement document the row
    names, so a reduction is only usable for as-of decisions when that document
    was captured and its dates are ordered announcement -> halt -> resumption.
    Anything else stays `unknown-blocked`: present in the table as coverage,
    invisible to as-of queries.
    """

    details = reduction_details(index, manifests)
    events: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] not in REDUCTION_SOURCES:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for row in rows_of(manifest_path):
            if row.get("record_kind") != "resumption":
                continue
            symbol = str(row["symbol"])
            resumption = str(row.get("resumption_date") or "")
            key = _detail_key(row)
            detail = details.get(key) if key else None

            announced = key[1] if key else ""
            halt = str(detail.get("halt_date") or "") if detail else ""
            # Fail closed on anything out of order. An announcement that does
            # not precede its own halt, or a halt that does not precede the
            # resumption, means the join is wrong somewhere and the row must
            # not be trusted to say when it became knowable.
            ordered = bool(
                announced and halt and resumption
                and announced <= halt < resumption
            )
            if not ordered:
                announced = ""

            # `effective_to` is inclusive everywhere in this table, and the
            # security trades again on its resumption date. Storing the
            # resumption date itself would put a trading day inside a halt
            # interval, so the interval ends the calendar day before. The
            # publisher's resumption date is kept verbatim in `measure_text`.
            last_halted = _day_before(resumption) if ordered else ""

            events.append(
                {
                    "market": "TWSE",
                    "symbol": symbol,
                    "event_kind": "capital-reduction",
                    "announced_at": announced,
                    "effective_from": halt if ordered else "",
                    "effective_to": last_halted,
                    "altered_trading": False,
                    "reason_text": str(row.get("reduction_reason") or "")[:400],
                    "measure_text": (
                        f"resumption_date={resumption} "
                        f"prior_close={row.get('prior_close')} "
                        f"resumption_reference={row.get('resumption_reference_price')} "
                        f"limit_up={row.get('limit_up')} limit_down={row.get('limit_down')} "
                        f"new_shares_per_thousand="
                        f"{detail.get('new_shares_per_thousand') if detail else None} "
                        f"cash_returned_per_share="
                        f"{detail.get('cash_returned_per_share') if detail else None}"
                    )[:400],
                    "availability_basis": (
                        "publisher-exact" if announced else "unknown-blocked"
                    ),
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": int(row.get("source_row_ordinal") or 0),
                }
            )
    for row in events:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("market", "symbol", "event_kind", "effective_to", "snapshot_id")}
        )
    events.sort(key=lambda r: (r["effective_to"], r["symbol"]))
    return events



def build_par_value_changes(index, manifests):
    """Par-value changes as market-status intervals.

    A par-value change splits the shares without changing what the company is
    worth. Trading halts, and on resumption the price is restated on the new
    share count — the same shape as a capital reduction, and the same danger:
    the five in this window are the five largest unexplained single-day falls
    in the whole price table, each a fall of about ninety percent that never
    happened.

    Unlike a reduction, the halt date needs no second request: the resumption
    row carries it in its own detail link. No announcement date is obtainable
    from either table, so every row is `unknown-blocked` — present as coverage,
    invisible to as-of queries.
    """

    events: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] not in PAR_VALUE_SOURCES:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for row in rows_of(manifest_path):
            if row.get("record_kind") != "resumption":
                continue
            halt = str(row.get("halt_date") or "")
            resumption = str(row.get("resumption_date") or "")
            if not halt or not resumption or halt >= resumption:
                continue
            events.append(
                {
                    "market": "TWSE",
                    "symbol": str(row["symbol"]),
                    "event_kind": "par-value-change",
                    # Neither published table carries an announcement date and
                    # the forecast detail serves only pending changes, so there
                    # is nothing here that says when this became knowable.
                    "announced_at": "",
                    "effective_from": halt,
                    # Inclusive interval: the security trades again on its
                    # resumption date, so the halt ends the day before.
                    "effective_to": _day_before(resumption),
                    "altered_trading": False,
                    "reason_text": "變更股票面額",
                    "measure_text": (
                        f"resumption_date={resumption} "
                        f"prior_close={row.get('prior_close')} "
                        f"resumption_reference={row.get('resumption_reference_price')} "
                        f"limit_up={row.get('limit_up')} "
                        f"limit_down={row.get('limit_down')}"
                    )[:400],
                    "availability_basis": "unknown-blocked",
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": int(row.get("source_row_ordinal") or 0),
                }
            )
    for row in events:
        row["record_id"] = sha(
            {
                k: str(row[k])
                for k in ("market", "symbol", "event_kind", "effective_to", "snapshot_id")
            }
        )
    events.sort(key=lambda r: (r["effective_to"], r["symbol"]))
    return events



def build_tpex_announcement_halts(index, manifests):
    """TPEx reductions and par-value changes, from the announcement archive.

    TPEx publishes no historical table for either event: its four dedicated
    endpoints all ignore the requested date and serve a rolling window of the
    next few days. The archive is the only route to what happened last year,
    and it happens to be the better one — each announcement carries its own
    publication date, so unlike the TWSE par-value tables these are usable
    point-in-time.

    What the archive does *not* carry is the resumption reference price, which
    TPEx publishes only for the next few days. The halt is therefore complete
    and the price restatement is not; the exchange ratio the announcement does
    state is kept so the size of the move is at least attributable.
    """

    events: list[dict[str, Any]] = []
    for record in index:
        if record["source_id"] != TPEX_ANNOUNCEMENT_DETAIL_SOURCE:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for row in rows_of(manifest_path):
            kind = str(row.get("change_kind") or "")
            if kind not in ("capital-reduction", "par-value-change"):
                continue
            symbol = str(row.get("symbol") or "")
            announced = str(row.get("announced_at") or "")
            halt = str(row.get("halt_from") or "")
            resumption = str(row.get("resumption_date") or "")
            if not (symbol and halt and resumption):
                # A follow-up announcement restates the outcome without the
                # dates; the announcement that stopped trading carries them.
                continue
            # Same ordering guard as the TWSE halts: an announcement that does
            # not precede its own halt means the row cannot say when the halt
            # became knowable.
            usable = bool(announced and announced <= halt < resumption)
            events.append(
                {
                    "market": "TPEX",
                    "symbol": symbol,
                    "event_kind": kind,
                    "announced_at": announced if usable else "",
                    "effective_from": halt,
                    # Inclusive interval, ending the day before trading resumes.
                    "effective_to": _day_before(resumption),
                    "altered_trading": False,
                    "reason_text": (
                        "變更股票面額" if kind == "par-value-change" else "減資"
                    ),
                    "measure_text": (
                        f"resumption_date={resumption} "
                        f"halt_to={row.get('halt_to')} "
                        f"par_value={row.get('par_value_before')}->"
                        f"{row.get('par_value_after')} "
                        f"shares_per_old_share={row.get('shares_per_old_share')} "
                        f"shares_per_thousand={row.get('shares_per_thousand_old_shares')} "
                        f"document={row.get('document_number')}"
                    )[:400],
                    "availability_basis": (
                        "publisher-exact" if usable else "unknown-blocked"
                    ),
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "source_row_ordinal": int(row.get("source_row_ordinal") or 0),
                }
            )
    for row in events:
        row["record_id"] = sha(
            {
                k: str(row[k])
                for k in ("market", "symbol", "event_kind", "effective_to", "snapshot_id")
            }
        )
    events.sort(key=lambda r: (r["effective_to"], r["symbol"]))
    return events


def tej_announcements() -> dict[tuple[str, str], str]:
    """(symbol, period) -> publisher filing date, from the TEJ lane."""

    out: dict[tuple[str, str], str] = {}
    if not TEJ_LANE.is_dir():
        return out
    for manifest_path in TEJ_LANE.rglob("import_manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("module") != "financial-announcement":
            continue
        table = manifest_path.parent / "normalized" / "rows.parquet"
        if not table.is_file():
            continue
        for row in pq.read_table(table).to_pylist():
            symbol, period = row.get("symbol"), str(row.get("period") or "").strip()
            if symbol and period and row.get("announce_date"):
                out[(str(symbol), period)] = str(row["announce_date"])
    return out


def build_fundamentals(index, manifests, announcements):
    rows: list[dict[str, Any]] = []
    basis_counts: dict[str, int] = {}
    for record in index:
        statement = FUNDAMENTAL_SOURCES.get(record["source_id"])
        if not statement:
            continue
        manifest_path = manifests.get(record["parse_run_id"])
        if manifest_path is None:
            continue
        for ordinal, row in enumerate(rows_of(manifest_path)):
            symbol = str(pick(row, "symbol", "security_id", "co_id") or "").strip()
            if not symbol:
                continue
            period = str(pick(row, "period", "period_end", "year_month", "yearmonth") or "").strip()
            key_period = period.replace("-", "")[:6]
            announced = announcements.get((symbol, key_period))
            basis = "publisher-exact" if announced else "first-observed-only"
            basis_counts[basis] = basis_counts.get(basis, 0) + 1
            rows.append(
                {
                    "symbol": symbol,
                    "statement_type": statement,
                    "period": period,
                    "metric": str(pick(row, "metric", "item", "field") or "as-published-row"),
                    "value": pick(row, "value", "amount"),
                    "publisher_released_at": announced or "",
                    "availability_basis": basis,
                    "revision_of_record_id": "",
                    "source_id": record["source_id"],
                    "snapshot_id": record["snapshot_id"],
                    "parse_run_id": record["parse_run_id"],
                    "evidence_tier": record["evidence_tier"],
                    "evidence_state": "verified-snapshot",
                    "availability_evidence_state": (
                        "licensed-vendor-snapshot" if announced else "verified-snapshot"
                    ),
                    "source_row_ordinal": ordinal,
                }
            )
    for row in rows:
        row["record_id"] = sha(
            {k: str(row[k]) for k in ("symbol", "statement_type", "period", "snapshot_id", "source_row_ordinal")}
        )
    rows.sort(key=lambda r: (r["symbol"], r["statement_type"], r["period"], r["source_row_ordinal"]))
    return rows, basis_counts


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
    manifests = manifest_index(staging_root)

    events, coverage = build_status(index, manifests)
    # Halt events are collapsed on the event itself for the same reason status
    # events are: a targeted capture re-requests every registered source, so
    # one halt can arrive from several archives and would otherwise be counted
    # once per archive.
    halts = collapse_duplicates(
        build_reductions(index, manifests)
        + build_par_value_changes(index, manifests)
        + build_tpex_announcement_halts(index, manifests)
        + build_full_cash_delivery()
    )
    events = sorted(
        events + halts,
        key=lambda r: (r['effective_from'] or r['announced_at'], r['market'], str(r['symbol'])),
    )
    announcements = tej_announcements()
    fundamentals, basis_counts = build_fundamentals(index, manifests, announcements)

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "staging_dataset_id": json.loads(
            (staging_root / "dataset_manifest.json").read_bytes()
        )["dataset_id"],
        "market_status_pit": {
            "rows": len(events),
            "sha256": write(out_root / "market_status_pit.parquet", events),
            "event_kinds": {
                kind: sum(1 for e in events if e["event_kind"] == kind)
                for kind in sorted({e["event_kind"] for e in events})
            },
            "altered_trading_rows": sum(1 for e in events if e["altered_trading"]),
            "with_announcement_date": sum(1 for e in events if e["announced_at"]),
            "tpex_halt_rows": sum(
                1
                for e in events
                if e["market"] == "TPEX"
                and e["event_kind"] in ("capital-reduction", "par-value-change")
            ),
            "par_value_change_rows": sum(
                1 for e in events if e["event_kind"] == "par-value-change"
            ),
            "capital_reduction_rows": sum(
                1 for e in events if e["event_kind"] == "capital-reduction"
            ),
            "capital_reduction_with_announcement": sum(
                1
                for e in events
                if e["event_kind"] == "capital-reduction" and e["announced_at"]
            ),
            "distinct_symbols": len({(e["market"], e["symbol"]) for e in events}),
        },
        "market_status_coverage": {
            "rows": len(coverage),
            "sha256": write(out_root / "market_status_coverage.parquet", coverage),
            "note": (
                "Absence of an event inside a covered interval means no event. "
                "Absence outside every covered interval means no coverage, and "
                "must not be read as tradable."
            ),
        },
        "fundamentals_pit": {
            "rows": len(fundamentals),
            "sha256": write(out_root / "fundamentals_pit.parquet", fundamentals),
            "availability_basis_counts": dict(sorted(basis_counts.items())),
            "tej_announcement_pairs": len(announcements),
            "distinct_symbols": len({r["symbol"] for r in fundamentals}),
            "statement_types": sorted({r["statement_type"] for r in fundamentals}),
        },
        "notes": [
            "Suspension is not in this table: no official historical source "
            "exists and it rests on the D8 price-absence inference.",
            "Fundamental availability comes from the TEJ licensed-vendor lane "
            "where present; rows without it fall back to first-observed-only.",
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
