"""M3 parser extension: offline parsers for the historical market-status feeds.

The four endpoints added in M3.1d have no parser in the Taiwan Core P0
registry, so their observations could not enter the staging lane. These
parsers close that gap.

They are defined here rather than in `tw_sepa_screener.parsers.formal` so the
Taiwan Core source-state fingerprint stays at its governance baseline; the
registry is composed at runtime, matching how `market_status_sources.py`
extends the source registry.

Design rules carried from the PIT contract:

* Disposal carries both an announcement date and an effective interval, so
  both are preserved separately and never collapsed.
* Placeholder rows such as the TPEx "no disposal today" filler become
  rejects with a reason, never silently dropped and never parsed as if they
  described a security.
* Missing values stay null. Nothing is forward-filled or inferred.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa

from tw_sepa_screener.parser_registry import (
    ParseBatch,
    ParserCodeResource,
    ParserDefinition,
    ParserRegistry,
)
from tw_sepa_screener.parsers.formal import P0_FORMAL_PARSER_DEFINITIONS

PARSER_CONTRACT = "m3-market-status/1"

# Text that marks a disposal announcement as also placing the security on
# the altered trading method (full-delivery) regime.
ALTERED_TRADING_MARKERS = ("變更交易方法", "全額交割")

SCHEMA = pa.schema(
    [
        pa.field("market", pa.string(), nullable=False),
        pa.field("event_kind", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("security_name", pa.string(), nullable=True),
        pa.field("announced_at", pa.date32(), nullable=True),
        pa.field("effective_from", pa.date32(), nullable=True),
        pa.field("effective_to", pa.date32(), nullable=True),
        pa.field("cumulative_count", pa.string(), nullable=True),
        pa.field("reason_text", pa.string(), nullable=True),
        pa.field("measure_text", pa.string(), nullable=True),
        pa.field("altered_trading", pa.bool_(), nullable=True),
        pa.field("source_row_ordinal", pa.int32(), nullable=False),
        pa.field("source_record_json", pa.string(), nullable=False),
    ]
)

REJECT_SCHEMA = pa.schema(
    [
        pa.field("source_row_ordinal", pa.int32(), nullable=False),
        pa.field("reject_reason", pa.string(), nullable=False),
        pa.field("source_record_json", pa.string(), nullable=False),
    ]
)

_CODE_RESOURCE = ParserCodeResource(
    "scripts/m3/market_status_parsers.py",
    Path(__file__).read_bytes(),
)


def _roc_or_iso(value: Any) -> date | None:
    """Accept 114/03/28, 114.03.28, 114年03月28日 and 2025-03-28."""

    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 7:
        year, month, day = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7])
    elif len(digits) == 8:
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _interval(value: Any) -> tuple[date | None, date | None]:
    parts = re.split(r"[~～]", str(value or ""))
    if len(parts) != 2:
        return None, None
    return _roc_or_iso(parts[0]), _roc_or_iso(parts[1])


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _tables(payload: Mapping[str, Any]) -> list[tuple[list[str], list[list[Any]]]]:
    """Normalise the TWSE flat shape and the TPEx nested shape."""

    out: list[tuple[list[str], list[list[Any]]]] = []
    if isinstance(payload.get("data"), list):
        out.append(
            ([str(f) for f in payload.get("fields") or []], payload["data"])
        )
    for table in payload.get("tables") or []:
        if isinstance(table, dict) and isinstance(table.get("data"), list):
            out.append(
                ([str(f) for f in table.get("fields") or []], table["data"])
            )
    return out


def _index_of(fields: list[str], *needles: str) -> int | None:
    for i, field_name in enumerate(fields):
        if any(needle in field_name for needle in needles):
            return i
    return None


def _build_parse_fn(market: str, event_kind: str):
    def parse_fn(
        payload: bytes,
        _raw_manifest: Mapping[str, Any],
        _config: Mapping[str, Any],
    ) -> ParseBatch:
        document = json.loads(payload.decode("utf-8-sig"))
        rows: list[dict[str, Any]] = []
        rejects: list[dict[str, Any]] = []
        ordinal = 0

        for fields, data in _tables(document):
            symbol_i = _index_of(fields, "證券代號", "股票代號")
            name_i = _index_of(fields, "證券名稱", "股票名稱")
            announced_i = _index_of(fields, "公布日期", "公告日期")
            if announced_i is None:
                announced_i = _index_of(fields, "日期")
            interval_i = _index_of(fields, "處置起迄", "處置起訖")
            reason_i = _index_of(fields, "處置條件", "處置原因", "注意交易資訊")
            measure_i = _index_of(fields, "處置措施", "處置內容")
            count_i = _index_of(fields, "累計")

            for raw_row in data:
                record = json.dumps(raw_row, ensure_ascii=False, sort_keys=False)
                ordinal += 1
                symbol = (
                    _clean(raw_row[symbol_i])
                    if symbol_i is not None and len(raw_row) > symbol_i
                    else None
                )
                if not symbol or not symbol[:4].isdigit():
                    # Placeholder or footer rows carry no security. They are
                    # recorded as rejects so their existence stays visible.
                    rejects.append(
                        {
                            "source_row_ordinal": ordinal,
                            "reject_reason": "row-has-no-security-code",
                            "source_record_json": record,
                        }
                    )
                    continue

                effective_from = effective_to = None
                if interval_i is not None and len(raw_row) > interval_i:
                    effective_from, effective_to = _interval(raw_row[interval_i])

                measure_text = (
                    _clean(raw_row[measure_i])
                    if measure_i is not None and len(raw_row) > measure_i
                    else None
                )
                body = " ".join(str(cell) for cell in raw_row)
                rows.append(
                    {
                        "market": market,
                        "event_kind": event_kind,
                        "symbol": symbol[:6],
                        "security_name": (
                            _clean(raw_row[name_i])
                            if name_i is not None and len(raw_row) > name_i
                            else None
                        ),
                        "announced_at": (
                            _roc_or_iso(raw_row[announced_i])
                            if announced_i is not None and len(raw_row) > announced_i
                            else None
                        ),
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "cumulative_count": (
                            _clean(raw_row[count_i])
                            if count_i is not None and len(raw_row) > count_i
                            else None
                        ),
                        "reason_text": (
                            _clean(raw_row[reason_i])
                            if reason_i is not None and len(raw_row) > reason_i
                            else None
                        ),
                        "measure_text": measure_text,
                        "altered_trading": (
                            any(marker in body for marker in ALTERED_TRADING_MARKERS)
                            if event_kind == "disposal"
                            else None
                        ),
                        "source_row_ordinal": ordinal,
                        "source_record_json": record,
                    }
                )

        rows.sort(key=lambda r: (r["symbol"], r["source_row_ordinal"]))
        return ParseBatch(
            rows=pa.Table.from_pylist(rows, schema=SCHEMA),
            rejects=pa.Table.from_pylist(rejects, schema=REJECT_SCHEMA)
            if rejects
            else None,
            diagnostics={
                "parser_contract": PARSER_CONTRACT,
                "row_count": len(rows),
                "reject_count": len(rejects),
            },
        )

    return parse_fn


def _definition(
    parser_id: str, source_id: str, endpoint_id: str, market: str, event_kind: str
) -> ParserDefinition:
    return ParserDefinition(
        parser_id=parser_id,
        source_ids=(source_id,),
        endpoint_ids=(endpoint_id,),
        output_schema=SCHEMA,
        primary_key=("market", "event_kind", "symbol", "source_row_ordinal"),
        sort_keys=("market", "event_kind", "symbol", "source_row_ordinal"),
        parse_fn=_build_parse_fn(market, event_kind),
        code_resources=(_CODE_RESOURCE,),
        default_config={
            "parser_contract": PARSER_CONTRACT,
            "security_scope": "four-digit-common-stock-v1",
            "missing_value_policy": "preserved-not-filled",
            "record_preservation": "canonical-source-record-json",
        },
    )


M3_MARKET_STATUS_PARSERS: tuple[ParserDefinition, ...] = (
    _definition(
        "twse-announcement-punish-history/1",
        "TWSE-STATUS-PUNISH-HIST",
        "trading-status-punish-history",
        "TWSE",
        "disposal",
    ),
    _definition(
        "twse-announcement-notice-history/1",
        "TWSE-STATUS-NOTICE-HIST",
        "trading-status-notice-history",
        "TWSE",
        "attention",
    ),
    _definition(
        "tpex-bulletin-disposal-history/1",
        "TPEX-STATUS-DISPOSAL-HIST",
        "trading-status-disposal-history",
        "TPEX",
        "disposal",
    ),
    _definition(
        "tpex-bulletin-attention-history/1",
        "TPEX-STATUS-ATTENTION-HIST",
        "trading-status-attention-history",
        "TPEX",
        "attention",
    ),
)


REDUCTION_SCHEMA = pa.schema(
    [
        pa.field("market", pa.string(), nullable=False),
        pa.field("record_kind", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("security_name", pa.string(), nullable=True),
        pa.field("halt_date", pa.date32(), nullable=True),
        pa.field("resumption_date", pa.date32(), nullable=True),
        pa.field("prior_close", pa.string(), nullable=True),
        pa.field("resumption_reference_price", pa.string(), nullable=True),
        pa.field("limit_up", pa.string(), nullable=True),
        pa.field("limit_down", pa.string(), nullable=True),
        pa.field("reduction_reason", pa.string(), nullable=True),
        pa.field("exchange_ratio", pa.string(), nullable=True),
        pa.field("cash_returned_per_share", pa.string(), nullable=True),
        pa.field("source_row_ordinal", pa.int32(), nullable=False),
        pa.field("source_record_json", pa.string(), nullable=False),
    ]
)


def _build_reduction_parse_fn(record_kind: str):
    """Parse the capital-reduction resumption and forecast tables.

    Both publish the prior close alongside the resumption reference price, so
    the adjustment ratio is stated by the exchange rather than inferred from a
    price gap — which the PIT contract forbids inferring.

    The forecast table is announced before the halt, so it carries the dates
    that make a reduction knowable in advance; the resumption table states
    what actually happened. They are kept as separate `record_kind` values
    rather than merged, because one is a plan and the other is an outcome.
    """

    def parse_fn(payload, _raw_manifest, _config) -> ParseBatch:
        document = json.loads(payload.decode("utf-8-sig"))
        rows: list[dict] = []
        rejects: list[dict] = []
        ordinal = 0
        for fields, data in _tables(document):
            names = [str(f) for f in fields]
            i_sym = _index_of(names, "股票代號")
            i_name = _index_of(names, "名稱")
            i_halt = _index_of(names, "停止買賣日期")
            i_resume = _index_of(names, "恢復買賣日期")
            i_prev = _index_of(names, "停止買賣前收盤價格")
            i_ref = _index_of(names, "恢復買賣參考價")
            i_up = _index_of(names, "漲停價格")
            i_down = _index_of(names, "跌停價格")
            i_why = _index_of(names, "減資原因")
            i_ratio = _index_of(names, "減資換股率")
            i_cash = _index_of(names, "每股退還股款")

            for raw_row in data:
                ordinal += 1
                record = json.dumps(raw_row, ensure_ascii=False)

                def cell(idx):
                    if idx is None or len(raw_row) <= idx:
                        return None
                    return _clean(raw_row[idx])

                def price(idx):
                    """Numeric cells only.

                    The forecast table reuses the column name
                    恢復買賣參考價 for a link parameter string such as
                    "1563,20260818,20260907". Accepting it would put a
                    fake price into the table under a real price name.
                    """

                    value = cell(idx)
                    if value is None:
                        return None
                    # Strict decimal only. Stripping separators first would
                    # turn "1563,20260818,20260907" into a valid float.
                    if not re.fullmatch(r"[0-9]{1,7}(\.[0-9]{1,4})?", value):
                        return None
                    return value

                def day(idx):
                    if idx is None or len(raw_row) <= idx:
                        return None
                    return _roc_or_iso(raw_row[idx])

                symbol = cell(i_sym)
                if not symbol or not symbol[:4].isdigit():
                    rejects.append(
                        {
                            "source_row_ordinal": ordinal,
                            "reject_reason": "row-has-no-security-code",
                            "source_record_json": record,
                        }
                    )
                    continue
                rows.append(
                    {
                        "market": "TWSE",
                        "record_kind": record_kind,
                        "symbol": symbol[:6],
                        "security_name": cell(i_name),
                        "halt_date": day(i_halt),
                        "resumption_date": day(i_resume),
                        "prior_close": price(i_prev),
                        "resumption_reference_price": price(i_ref),
                        "limit_up": price(i_up),
                        "limit_down": price(i_down),
                        "reduction_reason": cell(i_why),
                        "exchange_ratio": cell(i_ratio),
                        "cash_returned_per_share": price(i_cash),
                        "source_row_ordinal": ordinal,
                        "source_record_json": record,
                    }
                )
        rows.sort(key=lambda r: (r["symbol"], r["source_row_ordinal"]))
        return ParseBatch(
            rows=pa.Table.from_pylist(rows, schema=REDUCTION_SCHEMA),
            rejects=pa.Table.from_pylist(rejects, schema=REJECT_SCHEMA)
            if rejects
            else None,
            diagnostics={
                "parser_contract": PARSER_CONTRACT,
                "row_count": len(rows),
                "reject_count": len(rejects),
            },
        )

    return parse_fn


def _reduction_definition(
    parser_id: str, source_id: str, endpoint_id: str, record_kind: str
) -> ParserDefinition:
    return ParserDefinition(
        parser_id=parser_id,
        source_ids=(source_id,),
        endpoint_ids=(endpoint_id,),
        output_schema=REDUCTION_SCHEMA,
        primary_key=("market", "record_kind", "symbol", "source_row_ordinal"),
        sort_keys=("market", "record_kind", "symbol", "source_row_ordinal"),
        parse_fn=_build_reduction_parse_fn(record_kind),
        code_resources=(_CODE_RESOURCE,),
        default_config={
            "parser_contract": PARSER_CONTRACT,
            "security_scope": "four-digit-common-stock-v1",
            "missing_value_policy": "preserved-not-filled",
            "record_preservation": "canonical-source-record-json",
        },
    )


M3_REDUCTION_PARSERS: tuple[ParserDefinition, ...] = (
    _reduction_definition(
        "twse-capital-reduction-resumption/1",
        "TWSE-REDUCTION-RESUME-HIST",
        "capital-reduction-resumption-history",
        "resumption",
    ),
    _reduction_definition(
        "twse-capital-reduction-forecast/1",
        "TWSE-REDUCTION-FORECAST-HIST",
        "capital-reduction-forecast-history",
        "forecast",
    ),
)


REDUCTION_DETAIL_SCHEMA = pa.schema(
    [
        pa.field("market", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("security_name", pa.string(), nullable=True),
        pa.field("file_date", pa.date32(), nullable=True),
        pa.field("halt_date", pa.date32(), nullable=True),
        pa.field("new_shares_per_thousand", pa.string(), nullable=True),
        pa.field("cash_returned_per_share", pa.string(), nullable=True),
        pa.field("cash_dividend_per_share", pa.string(), nullable=True),
        pa.field("source_row_ordinal", pa.int32(), nullable=False),
        pa.field("source_record_json", pa.string(), nullable=False),
    ]
)


def _reduction_detail_parse_fn(
    payload: bytes,
    raw_manifest: Mapping[str, Any],
    _config: Mapping[str, Any],
) -> ParseBatch:
    """Parse one capital-reduction announcement document.

    This is the only place the exchange states the halt date for a reduction
    that has already resumed: the resumption table publishes 恢復買賣日期 but
    not 停止買賣日期, so without this document the halt interval has an end and
    no beginning.

    `FILE_DATE` never appears in the response body — it is the request key that
    addresses the announcement document. It is read back from the observation
    manifest rather than re-derived, so the parsed row can only ever carry the
    key that was actually requested.
    """

    document = json.loads(payload.decode("utf-8-sig"))
    parameters = raw_manifest.get("request_parameters") or {}
    file_date = _roc_or_iso(str(parameters.get("FILE_DATE") or ""))
    requested_symbol = str(parameters.get("STK_NO") or "").strip()

    rows: list[dict] = []
    rejects: list[dict] = []
    ordinal = 0
    for fields, data in _tables(document):
        names = [str(f) for f in fields]
        i_sym = _index_of(names, "股票代號")
        i_name = _index_of(names, "股票名稱")
        i_halt = _index_of(names, "停止買賣日期")
        i_new = _index_of(names, "每壹仟股換發新股票")
        i_cash = _index_of(names, "每股退還股款")
        i_div = _index_of(names, "原股每股配發現金股利")

        for raw_row in data:
            ordinal += 1
            record = json.dumps(raw_row, ensure_ascii=False)

            def cell(idx):
                if idx is None or len(raw_row) <= idx:
                    return None
                return _clean(raw_row[idx])

            symbol = cell(i_sym)
            if not symbol or not symbol[:4].isdigit():
                rejects.append(
                    {
                        "source_row_ordinal": ordinal,
                        "reject_reason": "row-has-no-security-code",
                        "source_record_json": record,
                    }
                )
                continue
            symbol = symbol[:6].strip()
            # A document served under a different code than the one requested
            # would silently attach one company's reduction to another.
            if requested_symbol and symbol != requested_symbol:
                rejects.append(
                    {
                        "source_row_ordinal": ordinal,
                        "reject_reason": "symbol-differs-from-requested-key",
                        "source_record_json": record,
                    }
                )
                continue
            rows.append(
                {
                    "market": "TWSE",
                    "symbol": symbol,
                    "security_name": cell(i_name),
                    "file_date": file_date,
                    "halt_date": (
                        _roc_or_iso(raw_row[i_halt])
                        if i_halt is not None and len(raw_row) > i_halt
                        else None
                    ),
                    "new_shares_per_thousand": cell(i_new),
                    "cash_returned_per_share": cell(i_cash),
                    "cash_dividend_per_share": cell(i_div),
                    "source_row_ordinal": ordinal,
                    "source_record_json": record,
                }
            )
    rows.sort(key=lambda r: (r["symbol"], r["source_row_ordinal"]))
    return ParseBatch(
        rows=pa.Table.from_pylist(rows, schema=REDUCTION_DETAIL_SCHEMA),
        rejects=pa.Table.from_pylist(rejects, schema=REJECT_SCHEMA)
        if rejects
        else None,
        diagnostics={
            "parser_contract": PARSER_CONTRACT,
            "row_count": len(rows),
            "reject_count": len(rejects),
        },
    )


REDUCTION_DETAIL_PARSER = ParserDefinition(
    parser_id="twse-capital-reduction-detail/1",
    source_ids=("TWSE-REDUCTION-DETAIL-HIST",),
    endpoint_ids=("capital-reduction-detail-history",),
    output_schema=REDUCTION_DETAIL_SCHEMA,
    primary_key=("market", "symbol", "file_date", "source_row_ordinal"),
    sort_keys=("market", "symbol", "file_date", "source_row_ordinal"),
    parse_fn=_reduction_detail_parse_fn,
    code_resources=(_CODE_RESOURCE,),
    default_config={
        "parser_contract": PARSER_CONTRACT,
        "security_scope": "four-digit-common-stock-v1",
        "missing_value_policy": "preserved-not-filled",
        "record_preservation": "canonical-source-record-json",
    },
)


def build_m3_parser_registry() -> ParserRegistry:
    """P0 formal parsers plus the M3 market-status parsers."""

    return ParserRegistry(
        tuple(P0_FORMAL_PARSER_DEFINITIONS)
        + M3_MARKET_STATUS_PARSERS
        + M3_REDUCTION_PARSERS
        + (REDUCTION_DETAIL_PARSER,)
    )
