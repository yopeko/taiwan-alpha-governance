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
# TWSE spells this path "reducation". Fifteen guesses at "reduction" all
# returned the 747-byte error page; the real path was recovered from the page
# source. Endpoint paths are extracted, never guessed.
TWSE_REDUCTION_RESUME_URL = "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU"
TWSE_REDUCTION_FORECAST_URL = "https://www.twse.com.tw/rwd/zh/reducation/TWTAVU"
# Both reduction tables end in a 詳細資料 column holding "STK_NO,FILE_DATE".
# The listing page turns that cell into a link by stripping every character
# outside [\w,.-]; the detail page then splits it on the comma into STK_NO
# and FILE_DATE. Both facts were read out of the page scripts, not guessed.
TWSE_REDUCTION_DETAIL_URL = "https://www.twse.com.tw/rwd/zh/reducation/TWTAVUDetail"
# Found through /rwd/zh/reportIndex/reportIndex, which lists all 117 TWSE
# reports with their column names and paths. Three earlier guesses at where
# a par-value report might live were all wrong; the index answered it in one
# request and should be the first stop for any future endpoint hunt.
TWSE_PAR_VALUE_RESUME_URL = "https://www.twse.com.tw/rwd/zh/change/TWTB8U"
TWSE_PAR_VALUE_FORECAST_URL = "https://www.twse.com.tw/rwd/zh/change/TWTB7U"
# TPEx publishes no historical reduction or par-value table at all: its four
# such endpoints (bulletin/revivt, decap, pvChgAnn, pvChgRslt) each ignore the
# requested date and echo a rolling window of the next few days. The history
# lives only in the market-announcement archive, which does take a real range
# and whose category 2 covers 除權、除息、增資、減資、換股.
TPEX_ANNOUNCEMENT_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/announcement"
TPEX_ANNOUNCEMENT_DETAIL_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/annDetail"
# Category 2 of the archive. The category list is published by the query page
# itself as a select element, so this is read from the publisher, not assumed.
TPEX_ANNOUNCEMENT_CORPORATE_CATEGORY = "2"
# The exchange's own regulation knowledge base, addressable per article.
# M4 implements 第63條 (the ten percent band) and 第58條之3第3項第3款
# (what that band is measured from on an ex-rights session), so the text of
# both is archived rather than merely cited.
TWSE_REGULATION_URL = (
    "https://twse-regulation.twse.com.tw/TW/law/DOC01.aspx"
)
# 臺灣證券交易所股份有限公司營業細則.
TWSE_OPERATING_RULES_CODE = "FL007304"

# Trading-status and delisting sources are NOT defined here. All seven were
# already in the M2 P0 allowlist and were simply never captured for M3:
#
#   TWSE-DELISTING                   終止上市公司, historical
#   TPEX-DELISTING-HIST              下櫃公司, historical
#   TWSE-TRADING-SUSPENSION          TWTAWU, current-only, short halts
#   TWSE-TRADING-ALTERED-TRADING     TWT85U, current-only
#   TPEX-TRADING-SUSPENSION-TODAY    current-only, short halts
#   TPEX-TRADING-SUSPENSION-HISTORY  historical, short halts
#   TPEX-TRADING-ALTERED-TRADING     tpex_cmode, current-only, and the only
#                                    endpoint on either exchange stating a
#                                    long-term suspension as a flag
#
# Re-declaring them here made every URL resolve to two sources and the
# capture failed closed, which is the registry doing its job. Check the P0
# allowlist before adding a source: the gap was capture, not registration.

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
        source_id="TWSE-REDUCTION-RESUME-HIST",
        publisher="TWSE",
        endpoint_id="capital-reduction-resumption-history",
        url_prefixes=(TWSE_REDUCTION_RESUME_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TWSE-REDUCTION-FORECAST-HIST",
        publisher="TWSE",
        endpoint_id="capital-reduction-forecast-history",
        url_prefixes=(TWSE_REDUCTION_FORECAST_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TWSE-REDUCTION-DETAIL-HIST",
        publisher="TWSE",
        endpoint_id="capital-reduction-detail-history",
        url_prefixes=(TWSE_REDUCTION_DETAIL_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TWSE-PAR-VALUE-RESUME-HIST",
        publisher="TWSE",
        endpoint_id="par-value-change-resumption-history",
        url_prefixes=(TWSE_PAR_VALUE_RESUME_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TWSE-PAR-VALUE-FORECAST-HIST",
        publisher="TWSE",
        endpoint_id="par-value-change-forecast-history",
        url_prefixes=(TWSE_PAR_VALUE_FORECAST_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TWSE-REGULATION-OPERATING-RULES",
        publisher="TWSE",
        endpoint_id="operating-rules-article",
        url_prefixes=(TWSE_REGULATION_URL,),
        required_parameters=(("FLCODE", TWSE_OPERATING_RULES_CODE),),
    ),
    RawSourceDefinition(
        source_id="TPEX-ANNOUNCEMENT-HIST",
        publisher="TPEX",
        endpoint_id="market-announcement-history",
        url_prefixes=(TPEX_ANNOUNCEMENT_URL,),
        required_parameters=(("response", "json"),),
    ),
    RawSourceDefinition(
        source_id="TPEX-ANNOUNCEMENT-DETAIL",
        publisher="TPEX",
        endpoint_id="market-announcement-detail",
        url_prefixes=(TPEX_ANNOUNCEMENT_DETAIL_URL,),
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
    "TWSE-REDUCTION-RESUME-HIST": {
        "url": TWSE_REDUCTION_RESUME_URL,
        "calendar": "gregorian",
    },
    "TWSE-REDUCTION-FORECAST-HIST": {
        "url": TWSE_REDUCTION_FORECAST_URL,
        "calendar": "gregorian",
    },
    "TWSE-PAR-VALUE-RESUME-HIST": {
        "url": TWSE_PAR_VALUE_RESUME_URL,
        "calendar": "gregorian",
    },
    "TWSE-PAR-VALUE-FORECAST-HIST": {
        "url": TWSE_PAR_VALUE_FORECAST_URL,
        "calendar": "gregorian",
    },
    # A third date format, and the only source so far needing an extra
    # parameter beyond the range: ROC and plain YYYYMMDD are both rejected
    # here with 日期參數錯誤.
    "TPEX-ANNOUNCEMENT-HIST": {
        "url": TPEX_ANNOUNCEMENT_URL,
        "calendar": "gregorian-slash",
        "extra_parameters": {"cate": TPEX_ANNOUNCEMENT_CORPORATE_CATEGORY},
    },
}


def build_m3_registry() -> RawSourceRegistry:
    """P0 formal allowlist plus the M3 historical market-status endpoints."""

    return RawSourceRegistry(tuple(P0_FORMAL_SOURCES) + M3_MARKET_STATUS_SOURCES)


def format_date(value: date, calendar: str) -> str:
    if calendar == "roc":
        return f"{value.year - 1911}/{value.month:02d}/{value.day:02d}"
    if calendar == "gregorian-slash":
        return value.strftime("%Y/%m/%d")
    return value.strftime("%Y%m%d")


def request_parameters(source_id: str, start: date, end: date) -> dict[str, str]:
    spec = SOURCE_SPECS[source_id]
    calendar = str(spec["calendar"])
    parameters = {
        "response": "json",
        "startDate": format_date(start, calendar),
        "endDate": format_date(end, calendar),
    }
    extra = spec.get("extra_parameters")
    if isinstance(extra, dict):
        parameters.update({str(k): str(v) for k, v in extra.items()})
    return parameters


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


# The detail endpoint is addressed by security and announcement file, not by a
# date range, so it is deliberately absent from SOURCE_SPECS: the range capture
# loop has no meaningful chunk to request for it. Its keys are derived from the
# 詳細資料 column of an already-captured listing, never enumerated blindly.
def detail_parameters(stk_no: str, file_date: str) -> dict[str, str]:
    """Request parameters for one capital-reduction announcement document."""

    return {"response": "json", "STK_NO": stk_no, "FILE_DATE": file_date}


def detail_period(stk_no: str, file_date: str) -> str:
    return f"detail:{stk_no}:{file_date}"


def announcement_detail_parameters(content_file: str, doc_id: str) -> dict[str, str]:
    """Request parameters for one archived market announcement."""

    return {"response": "json", "content_file": content_file, "docId": doc_id}


def announcement_detail_period(doc_id: str) -> str:
    return f"announcement:{doc_id}"


def regulation_article_parameters(article: str) -> dict[str, str]:
    """Request parameters for one article of the TWSE operating rules."""

    return {"FLCODE": TWSE_OPERATING_RULES_CODE, "FLNO": article}


def regulation_article_period(article: str) -> str:
    return f"article:{TWSE_OPERATING_RULES_CODE}:{article}"
