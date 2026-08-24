"""M3.3: build `trading_calendar_pit`, `security_events` and `security_intervals`.

Reads the M3.2 staging layer and the TEJ licensed-vendor lane, and emits the
first two canonical point-in-time table families.

Three rules this build exists to enforce:

* **A session is proved, never inferred.** A date is `official-open` only
  because the exchange published a closing table for it, and `official-closed`
  only because both markets explicitly returned nothing. The two markets
  express "nothing" differently — TWSE rejects the parse, TPEx returns zero
  rows — and both forms are recognised.

* **A symbol is not an identity.** 2301 and 2432 each appear in both the
  delisted and the current records, so membership is keyed on a
  `security_instance_id` derived from market, symbol and listing interval.

* **A missing listing date is not permission to trade.** Such a security gets
  `membership_state=unknown`, never `eligible`, exactly as M0 requires.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_ID = "tw-alpha-m3-calendar-lifecycle/1.0.0"
RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
TEJ_LANE = RAW / "m3_tej_licensed_2026-08-16"
# The lane above was imported from a TEJ quarterly-financials export, so its
# universe is really "securities that filed a statement in those periods".
# That silently drops companies which stopped filing -- and not filing is what
# gets a company delisted, so the selection mechanism removes securities
# precisely because they are failing. The company-master lane is keyed on the
# company existing rather than on it reporting, and fills those holes.
TEJ_MASTER_LANE = RAW / "m3_tej_master_2026-08-22"
# The exchanges' own delisting lists (D11). Dated and historical, so unlike
# the suspension flags captured alongside them these can be used point in
# time. They outrank the vendor: a delisting is the exchange's act.
#
# The vendor is silent on board transfers -- 6589, 6423 and 5236 each ended a
# leg on one board and TEJ records only the surviving one -- so this is not
# merely corroboration, it closes three intervals nothing else closes.
TRADING_STATUS_CAPTURE = Path(r"C:\tmp\tw-alpha-m3-trading-status-01")
WINDOW_START = date(2019, 1, 1)
WINDOW_END = date(2026, 8, 3)
MARKETS = ("TWSE", "TPEX")

PRICE_SOURCES = {"TWSE-PRICE-HIST": "TWSE", "TPEX-PRICE-HIST": "TPEX"}


def sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_index(staging: Path) -> list[dict[str, Any]]:
    path = staging / "staging_index.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_manifest_for(staging: Path, parse_run_id: str) -> Path | None:
    for manifest in (staging / "parsed_observations").rglob("parse_manifest.json"):
        if manifest.parent.name == parse_run_id:
            return manifest
    return None


def build_calendar(staging: Path, index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per market-date, with the evidence that decided its state."""

    observed: dict[tuple[str, str], dict[str, Any]] = {}
    for record in index:
        market = PRICE_SOURCES.get(record["source_id"])
        if not market:
            continue
        period = str(record["logical_period"])
        if not period.startswith("session:"):
            continue
        observed[(market, period.split(":", 1)[1])] = record

    # A session that produced no parseable rows is `official-no-data`; the
    # staging index only holds parsed observations, so an absent entry for a
    # captured date is itself the no-data signal.
    rows: list[dict[str, Any]] = []
    cursor = WINDOW_START
    while cursor <= WINDOW_END:
        iso = cursor.isoformat()
        present = {m: observed.get((m, iso)) for m in MARKETS}
        any_open = any(
            record and int(record.get("row_count", 0)) > 0 for record in present.values()
        )
        for market in MARKETS:
            record = present[market]
            row_count = int(record.get("row_count", 0)) if record else 0
            if record and row_count > 0:
                session_state = "official-open"
                basis = "official-closing-table-published"
                quality = record.get("quality_decision")
            elif any_open:
                # The other market traded, so this one's silence is not a
                # market-wide closure. Fail closed rather than guess.
                session_state = "unknown"
                basis = "single-market-absence-only"
                quality = record.get("quality_decision") if record else None
            else:
                session_state = "official-closed"
                basis = (
                    "zero-row-response"
                    if record
                    else "parse-rejected-no-data-response"
                )
                quality = record.get("quality_decision") if record else None
            rows.append(
                {
                    "market": market,
                    "session_date": iso,
                    "session_state": session_state,
                    "evidence_basis": basis,
                    "observed_row_count": row_count,
                    "quality_decision": quality or "",
                    "snapshot_id": (record or {}).get("snapshot_id", ""),
                    "parse_run_id": (record or {}).get("parse_run_id", ""),
                    "evidence_tier": (record or {}).get("evidence_tier", "no-parsed-observation"),
                }
            )
        cursor += timedelta(days=1)
    for row in rows:
        row["record_id"] = sha({k: row[k] for k in ("market", "session_date", "session_state")})
    return rows


def load_tej_lifecycle() -> list[dict[str, Any]]:
    """Filings-derived rows, then master-derived rows for what they missed.

    The master lane is additive on purpose. It is read second and only
    contributes securities the filings lane never carried, so bringing in a
    company master cannot quietly restate a listing interval that the existing
    lane already established -- a restatement is a thing to look at, not to
    absorb.
    """

    out = _load_lane(TEJ_LANE)
    seen = {(row["market"], row["symbol"]) for row in out}
    for record in load_company_master():
        for leg in board_legs(record):
            market = BOARD_MARKETS.get(leg["board"])
            if not market or (market, record["symbol"]) in seen:
                continue
            if not overlaps_window(leg["start"], leg["end"]):
                # The master reaches back to the 1960s. A leg that closed
                # before this warehouse opens is history, not a gap.
                continue
            out.append(
                {
                    "market": market,
                    "symbol": record["symbol"],
                    "security_name": record.get("security_name"),
                    "listing_date": leg["start"],
                    "delisting_date": leg["end"],
                    "evidence_state": "licensed-vendor-snapshot",
                    "snapshot_id": record.get("snapshot_id"),
                    "source_locator": record.get("source_locator"),
                    "membership_source": "company-master",
                }
            )
            seen.add((market, record["symbol"]))
    return out


def load_official_delistings() -> dict[tuple[str, str], dict[str, str]]:
    """(market, symbol) -> the exchange's own delisting date and reason."""

    out: dict[tuple[str, str], dict[str, str]] = {}
    observations = TRADING_STATUS_CAPTURE / "raw_observations"
    if not observations.is_dir():
        return out
    for manifest_path in observations.rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        source_id = str(manifest.get("source_id"))
        if source_id not in ("TWSE-DELISTING", "TPEX-DELISTING-HIST"):
            continue
        blob = str(manifest.get("blob_id") or manifest.get("payload_sha256") or "")
        path = TRADING_STATUS_CAPTURE / "raw_blobs" / "sha256" / blob[:2] / blob / "payload.bin"
        if not blob or not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            payload = json.loads(gzip.decompress(raw).decode("utf-8"))
        except (OSError, gzip.BadGzipFile, ValueError):
            payload = json.loads(raw.decode("utf-8", "replace"))
        snapshot = str(manifest.get("blob_id") or "")
        if source_id == "TWSE-DELISTING":
            for row in payload or []:
                out[("TWSE", str(row["Code"]))] = {
                    "delisting_date": _roc(row.get("DelistingDate")),
                    "reason": "",
                    "snapshot_id": snapshot,
                }
        else:
            tables = (payload or {}).get("tables") or []
            for row in (tables[0].get("data") if tables else []) or []:
                out[("TPEX", str(row[0]))] = {
                    "delisting_date": _roc(row[2]),
                    # The exchange cites the rule it acted under, which is how
                    # a transfer is told from a failure.
                    "reason": str(row[3])[:120],
                    "snapshot_id": snapshot,
                }
    return {k: v for k, v in out.items() if v["delisting_date"]}


def _roc(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def apply_official_delistings(
    intervals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Let the exchange close the interval it actually closed.

    Only the last interval of a security is touched, and only when the vendor
    is silent or agrees. A genuine disagreement is not resolved here: it means
    one of the two is wrong about a fact the exchange owns, and picking a
    winner silently is how a wrong delisting date survives review.
    """

    official = load_official_delistings()
    stats = {"agreed": 0, "filled": 0, "skipped_earlier_life": 0, "conflicts": []}

    # A symbol is not an identity. 2432 was delisted on 2008-09-01, and the
    # code was later reissued to a company still trading; the exchange's list
    # carries only the symbol and the date, so matching it to whichever
    # interval happens to be last would attribute a 2008 delisting to a
    # security first listed years afterwards. The official record belongs to
    # the life that was open on that date, or to none of ours.
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in intervals:
        key = (row["market"], row["symbol"])
        record = official.get(key)
        if record and row["listing_date"] > record["delisting_date"]:
            continue
        current = latest.get(key)
        if current is None or row["listing_date"] > current["listing_date"]:
            latest[key] = row

    for key, record in official.items():
        row = latest.get(key)
        if row is None:
            # Every interval we hold for this symbol starts after the
            # exchange closed the life it is describing.
            if any(r["market"] == key[0] and r["symbol"] == key[1] for r in intervals):
                stats["skipped_earlier_life"] += 1
            continue
        theirs = record["delisting_date"]
        ours = row.get("delisting_date") or ""
        if not ours:
            row["delisting_date"] = theirs
            row["delisting_basis"] = "official-exchange-list"
            row["delisting_reason"] = record["reason"]
            stats["filled"] += 1
        elif ours == theirs:
            row["delisting_basis"] = "official-exchange-list"
            row["delisting_reason"] = record["reason"]
            stats["agreed"] += 1
        else:
            stats["conflicts"].append(
                {"market": key[0], "symbol": key[1], "vendor": ours, "official": theirs}
            )
    for row in intervals:
        row.setdefault("delisting_basis", "licensed-vendor-snapshot" if row.get("delisting_date") else "")
        row.setdefault("delisting_reason", "")
    if stats["conflicts"]:
        raise SystemExit(
            "the exchange and the vendor disagree on a delisting date, which "
            "is a fact the exchange owns; resolve it rather than choosing:\n"
            + json.dumps(stats["conflicts"], ensure_ascii=False, indent=2)
        )
    return intervals, stats


def load_company_master() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not TEJ_MASTER_LANE.is_dir():
        return out
    for manifest_path in TEJ_MASTER_LANE.rglob("import_manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("module") != "company-master":
            continue
        table = manifest_path.parent / "normalized" / "rows.parquet"
        if not table.is_file():
            continue
        for row in pq.read_table(table).to_pylist():
            if row.get("symbol"):
                out.append({**row, "source_locator": manifest_path.parent.name})
    return out


def build_board_intervals(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Which board a security sat on, when -- including boards out of scope.

    The scope decision needs this and cannot get it from the daily quotation
    tables. The exchange suffixes 創 to most innovation-board short names but
    not all of them: 6902 GOGOLOOK and 6794 向榮生技 were quoted under plain
    names for the 85 and 190 sessions before they moved to the main board, so
    a name-based rule silently let 275 out-of-scope sessions through.
    """

    rows: list[dict[str, Any]] = []
    for record in records:
        for leg in board_legs(record):
            rows.append(
                {
                    "symbol": record["symbol"],
                    "security_name": record.get("security_name") or "",
                    "board": leg["board"],
                    "market": BOARD_MARKETS.get(leg["board"], ""),
                    "effective_from": leg["start"],
                    "effective_to": leg["end"],
                    "in_m0_universe": "true" if leg["board"] in BOARD_MARKETS else "false",
                    "evidence_state": "licensed-vendor-snapshot",
                    "snapshot_id": record.get("snapshot_id") or "",
                }
            )
    rows.sort(key=lambda r: (r["symbol"], r["effective_from"], r["board"]))
    return rows


# TEJ's board codes. TSE and OTC are the M0 universe; the rest are boards a
# security can pass through, and knowing when it was on one is what keeps an
# out-of-scope session out of scope.
BOARD_MARKETS = {"TSE": "TWSE", "OTC": "TPEX"}
BOARD_COLUMNS = (
    ("listing_date_tse", "TSE"),
    ("listing_date_otc", "OTC"),
    ("listing_date_reg", "REG"),
    ("listing_date_tib", "TIB"),
)
NULL = {"", ".", "-", "none", "null"}


def board_legs(row: dict[str, Any]) -> list[dict[str, str]]:
    """Every board this security sat on, with the dates it moved.

    Built only from dated columns. TEJ's 上市別 is today's board, so reading
    a market from it would make every historical answer depend on where the
    security eventually ended up -- 3202 reads PUB today and was on OTC for
    the twenty years that matter.

    The board listing dates and the 前N次變更市場 history usually agree and
    are merged rather than ranked, because either can be the one that carries
    a move: the listing columns hold one date per board, so a security that
    returns to a board it already left is only visible in the change history.
    """

    points: dict[tuple[str, str], None] = {}
    for field, board in BOARD_COLUMNS:
        when = _iso(row.get(field))
        if when:
            points[(board, when)] = None
    for index in (1, 2, 3):
        board = str(row.get(f"market_change_{index}") or "").strip().upper()
        when = _iso(row.get(f"market_change_{index}_date"))
        if board and board.lower() not in NULL and when:
            points[(board, when)] = None

    ordered = sorted(points, key=lambda item: (item[1], item[0]))
    delisting = _iso(row.get("delisting_date"))
    legs: list[dict[str, str]] = []
    for position, (board, start) in enumerate(ordered):
        end = ordered[position + 1][1] if position + 1 < len(ordered) else delisting
        if end and end <= start:
            # Two names for one move on one day -- REG and ROTC are both the
            # emerging board -- so the first leg covers no session at all.
            continue
        legs.append({"board": board, "start": start, "end": end})
    return legs


def _iso(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in NULL else text


def overlaps_window(start: str, end: str) -> bool:
    """Does [start, end) touch the warehouse window at all?

    An open end means still current, which always reaches the window end.
    """

    if start and start > WINDOW_END.isoformat():
        return False
    if end and end <= WINDOW_START.isoformat():
        return False
    return True


def _load_lane(lane: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not lane.is_dir():
        return out
    for manifest_path in lane.rglob("import_manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("module") != "security-listing":
            continue
        table = manifest_path.parent / "normalized" / "rows.parquet"
        if not table.is_file():
            continue
        for row in pq.read_table(table).to_pylist():
            out.append(
                {
                    "market": row.get("market"),
                    "symbol": row.get("symbol"),
                    "security_name": row.get("security_name"),
                    "listing_date": row.get("listing_date"),
                    "delisting_date": row.get("delisting_date"),
                    "evidence_state": "licensed-vendor-snapshot",
                    "snapshot_id": row.get("snapshot_id"),
                    "source_locator": str(manifest_path.parent.name),
                }
            )
    return out


def build_lifecycle(records: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    events: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    for record in records:
        market, symbol = record.get("market"), record.get("symbol")
        if not market or not symbol:
            continue
        listing = record.get("listing_date")
        delisting = record.get("delisting_date")
        instance = sha(
            {"market": market, "symbol": symbol, "listing_date": listing or "unknown"}
        )
        for kind, when in (("listing", listing), ("delisting", delisting)):
            if not when:
                continue
            events.append(
                {
                    "security_instance_id": instance,
                    "market": market,
                    "symbol": symbol,
                    "event_kind": kind,
                    "effective_date": when,
                    "evidence_state": record["evidence_state"],
                    "snapshot_id": record.get("snapshot_id") or "",
                }
            )
        intervals.append(
            {
                "security_instance_id": instance,
                "market": market,
                "symbol": symbol,
                "security_name": record.get("security_name") or "",
                "listing_date": listing or "",
                "delisting_date": delisting or "",
                # A security with no listing date can never be proved to have
                # been in the market on a past date, so it stays unknown.
                "membership_basis": "listed-interval" if listing else "missing-at-source",
                "default_membership_state": "resolvable" if listing else "unknown",
                "evidence_state": record["evidence_state"],
            }
        )
    events.sort(key=lambda r: (r["market"], r["symbol"], r["event_kind"], r["effective_date"]))
    intervals.sort(key=lambda r: (r["market"], r["symbol"], r["listing_date"]))
    return events, intervals


def membership_on(intervals: list[dict[str, Any]], as_of: date) -> dict[str, str]:
    """Membership state per security_instance_id at a historical session."""

    states: dict[str, str] = {}
    for row in intervals:
        if row["default_membership_state"] == "unknown":
            states[row["security_instance_id"]] = "unknown"
            continue
        listed = date.fromisoformat(row["listing_date"])
        if as_of < listed:
            states[row["security_instance_id"]] = "not-yet-listed"
            continue
        if row["delisting_date"]:
            if as_of >= date.fromisoformat(row["delisting_date"]):
                states[row["security_instance_id"]] = "delisted"
                continue
        states[row["security_instance_id"]] = "listed"
    return states


def write_csv(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(staging_root: Path, out_root: Path) -> dict[str, Any]:
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")
    index = load_index(staging_root)
    calendar = build_calendar(staging_root, index)
    events, intervals = build_lifecycle(load_tej_lifecycle())
    intervals, delisting_stats = apply_official_delistings(intervals)

    boards = build_board_intervals(load_company_master())

    calendar_sha = write_csv(out_root / "trading_calendar_pit.csv", calendar)
    events_sha = write_csv(out_root / "security_events.csv", events)
    intervals_sha = write_csv(out_root / "security_intervals.csv", intervals)
    boards_sha = write_csv(out_root / "security_board_intervals.csv", boards)

    by_state: dict[str, int] = {}
    for row in calendar:
        by_state[row["session_state"]] = by_state.get(row["session_state"], 0) + 1

    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "staging_root": str(staging_root),
        "staging_dataset_id": json.loads(
            (staging_root / "dataset_manifest.json").read_bytes()
        )["dataset_id"],
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "trading_calendar_pit": {
            "rows": len(calendar),
            "sha256": calendar_sha,
            "session_state_counts": dict(sorted(by_state.items())),
        },
        "security_events": {"rows": len(events), "sha256": events_sha},
        "security_board_intervals": {
            "rows": len(boards),
            "sha256": boards_sha,
            "distinct_symbols": len({r["symbol"] for r in boards}),
            "board_counts": {
                board: sum(1 for r in boards if r["board"] == board)
                for board in sorted({r["board"] for r in boards})
            },
        },
        "security_intervals": {
            "rows": len(intervals),
            "sha256": intervals_sha,
            "with_listing_date": sum(1 for r in intervals if r["listing_date"]),
            "missing_at_source": sum(
                1 for r in intervals if r["membership_basis"] == "missing-at-source"
            ),
            "delisted": sum(1 for r in intervals if r["delisting_date"]),
            "distinct_instances": len({r["security_instance_id"] for r in intervals}),
            "distinct_symbols": len({(r["market"], r["symbol"]) for r in intervals}),
            "delisting_confirmed_by_exchange": delisting_stats["agreed"],
            "delisting_filled_from_exchange": delisting_stats["filled"],
        },
        "notes": [
            "Lifecycle currently rests on TEJ licensed-vendor evidence, "
            "permitted for `supported` by G0 v2.0.0 D9 with its six conditions.",
            "A security without a listing date is `unknown`, never eligible.",
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
    manifest = build(args.staging_root, args.out_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
