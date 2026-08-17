"""M3 registry extension: official historical market-status endpoints.

These four endpoints accept a date range and serve history back to at least
2020, unlike the nine current-only OpenAPI snapshots already registered in
Taiwan Core. They are defined here rather than in
`tw_sepa_screener.sources.raw_registry` so the Taiwan Core source-state
fingerprint stays at its governance baseline; the registry is composed at
runtime instead.

Discovery evidence:
docs/evidence/m3-market-status-source-discovery-2026-08-16.md
"""

from __future__ import annotations

from datetime import date

from tw_sepa_screener.raw_capture import RawSourceDefinition, RawSourceRegistry
from tw_sepa_screener.sources.raw_registry import P0_FORMAL_SOURCES

TWSE_PUNISH_URL = "https://www.twse.com.tw/rwd/zh/announcement/punish"
TWSE_NOTICE_URL = "https://www.twse.com.tw/rwd/zh/announcement/notice"
TPEX_DISPOSAL_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal"
TPEX_ATTENTION_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/attention"

M3_MARKET_STATUS_SOURCES = (
    RawSourceDefinition(
        source_id="TWSE-STATUS-PUNISH-HIST",
        publisher="TWSE",
        endpoint_id="trading-status-punish-history",
        url_prefixes=(TWSE_PUNISH_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TWSE-STATUS-NOTICE-HIST",
        publisher="TWSE",
        endpoint_id="trading-status-notice-history",
        url_prefixes=(TWSE_NOTICE_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TPEX-STATUS-DISPOSAL-HIST",
        publisher="TPEX",
        endpoint_id="trading-status-disposal-history",
        url_prefixes=(TPEX_DISPOSAL_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TPEX-STATUS-ATTENTION-HIST",
        publisher="TPEX",
        endpoint_id="trading-status-attention-history",
        url_prefixes=(TPEX_ATTENTION_URL,),
        required_parameters=(("response", "json"),),
    ),
)

# TWSE takes Gregorian YYYYMMDD; TPEx takes ROC YYY/MM/DD and, critically,
# does NOT error on an unrecognised parameter — it silently returns the
# current week. Every response must therefore be checked against the range
# that was actually requested.
SOURCE_SPECS: dict[str, dict[str, object]] = {
    "TWSE-STATUS-PUNISH-HIST": {"url": TWSE_PUNISH_URL, "calendar": "gregorian"},
    "TWSE-STATUS-NOTICE-HIST": {"url": TWSE_NOTICE_URL, "calendar": "gregorian"},
    "TPEX-STATUS-DISPOSAL-HIST": {"url": TPEX_DISPOSAL_URL, "calendar": "roc"},
    "TPEX-STATUS-ATTENTION-HIST": {"url": TPEX_ATTENTION_URL, "calendar": "roc"},
}


def build_m3_registry() -> RawSourceRegistry:
    """P0 formal allowlist plus the M3 historical market-status endpoints."""

    return RawSourceRegistry(tuple(P0_FORMAL_SOURCES) + M3_MARKET_STATUS_SOURCES)


def format_date(value: date, calendar: str) -> str:
    if calendar == "roc":
        return f"{value.year - 1911}/{value.month:02d}/{value.day:02d}"
    return value.strftime("%Y%m%d")


def request_parameters(source_id: str, start: date, end: date) -> dict[str, str]:
    calendar = str(SOURCE_SPECS[source_id]["calendar"])
    return {
        "response": "json",
        "startDate": format_date(start, calendar),
        "endDate": format_date(end, calendar),
    }


def echoed_range_matches(payload: object, start: date, end: date) -> bool:
    """Guard against TPEx silently ignoring the requested range.

    TPEx echoes the range it actually served in a top-level `date` field as
    `YYYYMMDD~YYYYMMDD`. TWSE does not echo a range, so absence of the field
    is not treated as a mismatch.
    """

    if not isinstance(payload, dict):
        return False
    echoed = payload.get("date")
    if not isinstance(echoed, str) or "~" not in echoed:
        return True
    expected = f"{start.strftime('%Y%m%d')}~{end.strftime('%Y%m%d')}"
    return echoed.strip() == expected
