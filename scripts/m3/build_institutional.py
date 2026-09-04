"""Institutional net-buy, one row per security per session.

Turns the captured T86 and dailyTrade responses into a point-in-time table a
strategy can rank on: 投信買超前幾名 and its siblings.

THE TWO MARKETS ARE NOT THE SAME SHAPE, AND ARE NOT MADE TO BE

TWSE names its columns and the names are unique, so they are read by name.
Three layouts exist inside the six-year window -- 12 fields in 2012, 16 by
2015, 19 from 2018 -- and reading by name survives all three, where reading
by position would silently take the wrong column at every boundary.

TPEx names seven groups of three columns **identically**: 買進股數,
賣出股數, 買賣超股數, over and over. The JSON flattens away the header row
that says which group is which, so the names carry no information at all.

HOW THE TPEx GROUPS WERE IDENTIFIED, SINCE THE RESPONSE DOES NOT SAY

Not by assuming the conventional order. By arithmetic that the data either
satisfies or does not:

    g0 + g1 == g2        foreign excluding dealers, plus foreign dealers,
                         equals the foreign subtotal
    g4 + g5 == g6        proprietary own-account plus hedging equals the
                         proprietary subtotal
    g2 + g3 + g6 == T    the three subtotals equal the published total

All three hold on **every row of every session tested, with zero exceptions**,
while two competing orderings fail on 690 and 689 of 741 rows. Derived on
2022-03-16 and confirmed on 2022-03-14 and 2022-03-15 -- sessions not used to
derive it, because data used to form a hypothesis cannot also be its evidence.

`verify_tpex_identities` keeps checking them on every build. A layout change
that reorders the groups would break the arithmetic before it corrupted a
signal, which is the whole reason to derive structure this way rather than
hardcode a remembered order.

A SCOPE NOTE THAT MATTERS AND IS NOT A DEFECT

TPEx's own subtitle says the figures include 普通股、鉅額、零股、綜合帳戶.
The TPEx **price** table excludes odd lots and the after-hours session (PIT
contract section 6.4.1). So institutional volume and traded volume are drawn
on different scopes in the same market, exactly as the two markets' volume
columns already are. Recorded on the row rather than reconciled away.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_index_benchmarks import blob_for, observations  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-institutional/1.0.0"

TWSE_SOURCE = "TWSE-INSTITUTIONAL-DAILY"
TPEX_SOURCE = "TPEX-INSTITUTIONAL-DAILY"

# TWSE, read by name. Each measure lists the field names that have carried it
# across the three layouts; the first one present wins, and a measure with no
# match is null rather than guessed.
TWSE_FIELDS: dict[str, tuple[str, ...]] = {
    "foreign_net": (
        "外陸資買賣超股數(不含外資自營商)",
        "外資買賣超股數",
    ),
    "foreign_dealer_net": ("外資自營商買賣超股數",),
    "investment_trust_net": ("投信買賣超股數",),
    "dealer_net": ("自營商買賣超股數",),
    "dealer_own_net": ("自營商買賣超股數(自行買賣)",),
    "dealer_hedge_net": ("自營商買賣超股數(避險)",),
    "total_net": ("三大法人買賣超股數",),
}

# TPEx, read by position, with the identities above as the check.
TPEX_POSITIONS: dict[str, int] = {
    "foreign_net": 4,          # 外資及陸資（不含外資自營商）
    "foreign_dealer_net": 7,   # 外資自營商
    "foreign_total_net": 10,   # 外資及陸資合計
    "investment_trust_net": 13,
    "dealer_own_net": 16,
    "dealer_hedge_net": 19,
    "dealer_net": 22,          # 自營商合計
    "total_net": 23,
}

SCHEMA = pa.schema(
    [
        pa.field("market", pa.string(), nullable=False),
        pa.field("session_date", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("security_name", pa.string(), nullable=True),
        pa.field("foreign_net", pa.int64(), nullable=True),
        pa.field("foreign_dealer_net", pa.int64(), nullable=True),
        pa.field("foreign_total_net", pa.int64(), nullable=True),
        pa.field("investment_trust_net", pa.int64(), nullable=True),
        pa.field("dealer_own_net", pa.int64(), nullable=True),
        pa.field("dealer_hedge_net", pa.int64(), nullable=True),
        pa.field("dealer_net", pa.int64(), nullable=True),
        pa.field("total_net", pa.int64(), nullable=True),
        pa.field("layout_fields", pa.int32(), nullable=False),
        pa.field("scope_note", pa.string(), nullable=False),
        pa.field("source_id", pa.string(), nullable=False),
        pa.field("snapshot_id", pa.string(), nullable=False),
        pa.field("evidence_state", pa.string(), nullable=False),
    ]
)

TWSE_SCOPE = "twse-t86-as-published"
TPEX_SCOPE = "tpex-includes-block-odd-lot-omnibus"


def number(text: Any) -> int | None:
    cleaned = str(text).replace(",", "").strip()
    if cleaned in {"", "-", "--", "N/A"}:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def verify_tpex_identities(rows: list[list[Any]], session: str) -> dict[str, int]:
    """The three sums the group order rests on. Checked, never assumed."""

    checks = {"foreign_subtotal": 0, "dealer_subtotal": 0, "grand_total": 0, "rows": 0}
    for row in rows:
        values = [number(row[i]) if i < len(row) else None for i in range(24)]
        if any(v is None for v in values[2:24]):
            continue
        checks["rows"] += 1
        if values[4] + values[7] != values[10]:
            checks["foreign_subtotal"] += 1
        if values[16] + values[19] != values[22]:
            checks["dealer_subtotal"] += 1
        if values[10] + values[13] + values[22] != values[23]:
            checks["grand_total"] += 1
    broken = [k for k in ("foreign_subtotal", "dealer_subtotal", "grand_total") if checks[k]]
    if broken and checks["rows"]:
        raise SystemExit(
            f"{session}: the TPEx column groups no longer satisfy {broken} "
            f"({checks}). The layout has changed, and reading it by position "
            f"would now take the wrong column. Re-derive the order before "
            f"building"
        )
    return checks


def verify_twse_identities(rows: list[dict[str, Any]], session: str) -> dict[str, int]:
    """TWSE's own sums, checked where they hold and not where they do not.

    Two identities were tested against the data rather than assumed:

        自營商(自行) + 自營商(避險) == 自營商合計       holds on every row
        外陸資 + 外資自營商 + 投信 + 自營商 == 三大法人  holds on ordinary
                                                        shares only

    The second fails on **1.82% of rows, every one of them a warrant, ETF or
    ETN** -- 733 of 40,175 measured on 2022-03-14 to 03-16. The pattern is
    exact: for those the foreign-dealer figure equals the dealer figure, so a
    foreign dealer's hedge appears in both columns while the published total
    counts it once. Adding the four columns double-counts it.

    So the check is scoped to four-digit ordinary shares, where it held on all
    2,806 rows. **Scoping it is not weakening it**: asserting an identity on
    rows where the publisher's own columns overlap would fail the build on
    correct data, and a check that cries wolf gets switched off.

    Securities outside that scope are out of M0 scope anyway (Owner decisions
    D1 and D3), and they are still written -- refused later by
    `tradability_state`, not dropped here.
    """

    checks = {"dealer_subtotal": 0, "grand_total": 0, "ordinary_rows": 0, "rows": len(rows)}
    for row in rows:
        own, hedge, dealer = row["dealer_own_net"], row["dealer_hedge_net"], row["dealer_net"]
        if None not in (own, hedge, dealer) and own + hedge != dealer:
            checks["dealer_subtotal"] += 1
        symbol = row["symbol"]
        if not (len(symbol) == 4 and symbol.isdigit()):
            continue
        parts = (
            row["foreign_net"],
            row["foreign_dealer_net"],
            row["investment_trust_net"],
            row["dealer_net"],
        )
        if None in parts or row["total_net"] is None:
            continue
        checks["ordinary_rows"] += 1
        if sum(parts) != row["total_net"]:
            checks["grand_total"] += 1

    broken = [k for k in ("dealer_subtotal", "grand_total") if checks[k]]
    if broken:
        raise SystemExit(
            f"{session}: TWSE's published columns no longer satisfy {broken} "
            f"({checks}). Either the layout changed or a column now means "
            f"something else; read it before building on it"
        )
    return checks


def twse_rows(document: dict, session: str, record: dict) -> list[dict[str, Any]]:
    fields = document.get("fields") or []
    index = {str(name).strip(): i for i, name in enumerate(fields)}
    data = document.get("data") or []
    out = []
    for row in data:
        symbol = str(row[0]).strip() if row else ""
        if not symbol:
            continue
        entry: dict[str, Any] = {
            "market": "TWSE",
            "session_date": session,
            "symbol": symbol,
            "security_name": str(row[1]).strip() if len(row) > 1 else None,
            "foreign_total_net": None,
            "layout_fields": len(fields),
            "scope_note": TWSE_SCOPE,
            "source_id": TWSE_SOURCE,
            "snapshot_id": str(record.get("snapshot_id") or ""),
            "evidence_state": str(record.get("evidence_state") or ""),
        }
        for measure, names in TWSE_FIELDS.items():
            position = next((index[n] for n in names if n in index), None)
            entry[measure] = (
                number(row[position]) if position is not None and position < len(row) else None
            )
        out.append(entry)
    verify_twse_identities(out, session)
    return out


def tpex_rows(table: dict, session: str, record: dict) -> list[dict[str, Any]]:
    data = table.get("data") or []
    verify_tpex_identities(data, session)
    fields = table.get("fields") or []
    out = []
    for row in data:
        symbol = str(row[0]).strip() if row else ""
        if not symbol:
            continue
        entry: dict[str, Any] = {
            "market": "TPEX",
            "session_date": session,
            "symbol": symbol,
            "security_name": str(row[1]).strip() if len(row) > 1 else None,
            "layout_fields": len(fields),
            "scope_note": TPEX_SCOPE,
            "source_id": TPEX_SOURCE,
            "snapshot_id": str(record.get("snapshot_id") or ""),
            "evidence_state": str(record.get("evidence_state") or ""),
        }
        for measure, position in TPEX_POSITIONS.items():
            entry[measure] = number(row[position]) if position < len(row) else None
        out.append(entry)
    return out


def build(archives: list[Path], out_root: Path) -> dict[str, Any]:
    if out_root.exists() and any(out_root.iterdir()):
        raise SystemExit(f"output root must be empty: {out_root}")

    rows: list[dict[str, Any]] = []
    stats = {"observations": 0, "sessions_with_rows": 0, "no_rows": 0}
    layouts: dict[str, int] = {}

    for archive in archives:
        if not archive.is_dir():
            raise SystemExit(f"not an archive root: {archive}")
        for _, record in observations(archive, sources=(TWSE_SOURCE, TPEX_SOURCE)):
            stats["observations"] += 1
            period = str(record.get("logical_period") or "")
            if not period.startswith("session:"):
                continue
            session = period.split(":", 1)[1]
            try:
                document = json.loads(blob_for(archive, record).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                # A non-trading reply. Preserved as evidence by the capture and
                # correctly carrying no rows here.
                stats["no_rows"] += 1
                continue
            if record["source_id"] == TWSE_SOURCE:
                produced = twse_rows(document, session, record)
            else:
                tables = document.get("tables") or []
                produced = (
                    tpex_rows(tables[0], session, record) if tables else []
                )
            if not produced:
                stats["no_rows"] += 1
                continue
            stats["sessions_with_rows"] += 1
            key = f"{record['source_id']}:{produced[0]['layout_fields']}"
            layouts[key] = layouts.get(key, 0) + 1
            rows.extend(produced)

    if not rows:
        raise SystemExit(
            f"no institutional rows from {[str(a) for a in archives]}. An empty "
            f"table would let a signal read as present and be silent"
        )

    rows.sort(key=lambda r: (r["session_date"], r["market"], r["symbol"]))
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / "institutional_pit.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path)

    sessions = sorted({r["session_date"] for r in rows})
    manifest = {
        "schema_id": SCHEMA_ID,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "archives": [str(a) for a in archives],
        "rows": len(rows),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "sessions": {"count": len(sessions), "first": sessions[0], "last": sessions[-1]},
        "layouts_seen": dict(sorted(layouts.items())),
        **stats,
        "notes": [
            "TWSE columns are read by name and survive all three layouts; TPEx "
            "columns are read by position because its seven groups share three "
            "names, and the order is checked by three arithmetic identities on "
            "every build rather than remembered.",
            "The two markets are not aligned. TPEx's own subtitle says its "
            "figures include block trades, odd lots and omnibus accounts, while "
            "its price table excludes odd lots and the after-hours session. "
            "`scope_note` carries which is which.",
            "Ranking on these is only point-in-time if the rank is taken after "
            "the close and acted on the next session: the report is published "
            "after trading ends.",
        ],
    }
    (out_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, action="append", required=True, dest="archives"
    )
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.archives, args.out_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
