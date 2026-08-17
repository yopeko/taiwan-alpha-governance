"""M3.1b: import TEJ PRO exports into the licensed-vendor lane.

TEJ is a revised current-state database, so a row without an explicit vendor
date is unusable for point-in-time work and is rejected rather than imported.
Nothing here ever enters the official canonical lane.

Spec: docs/contracts/tej-import-spec.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_ID = "tw-alpha-tej-import/1.0.0"
EVIDENCE_STATE = "licensed-vendor-snapshot"
VENDOR = "TEJ"

# Logical field -> candidate column names seen in TEJ exports.
MODULES: dict[str, dict[str, Any]] = {
    "trading-calendar": {
        "required": {
            "date": ["年月日", "交易日期", "交易日", "mdate", "date"],
            "market": ["市場別", "市場", "market", "mkt"],
        },
        "optional": {},
        "date_fields": ["date"],
        "key": ["market", "date"],
    },
    "security-listing": {
        "required": {
            "symbol": ["證券代碼", "股票代號", "公司代碼", "coid", "symbol"],
            "market": ["市場別", "市場", "market", "mkt"],
        },
        "optional": {
            "listing_date": ["上市日", "上市日期", "掛牌日", "listing_date"],
            # TEJ splits the listing date across one column per board.
            "listing_date_tse": ["TSE上市日"],
            "listing_date_otc": ["OTC上市日"],
            "delisting_date": ["下市日", "下市日期", "終止上市日", "delisting_date"],
            "security_name": ["證券名稱", "公司名稱", "name"],
            "security_type": ["證券類別", "證券種類", "security_type"],
            "industry": ["產業別", "industry"],
        },
        "date_fields": ["listing_date", "listing_date_tse", "listing_date_otc"],
        "key": ["market", "symbol", "listing_date"],
        # Board-specific listing columns are folded into listing_date.
        "resolve_listing_date": True,
        "deduplicate": True,
    },
    "financial-announcement": {
        "required": {
            "symbol": ["證券代碼", "股票代號", "公司代碼", "coid", "symbol"],
            "period": ["年季", "年月", "期別", "period", "yearquarter"],
            # Ordered by trust: filing date beats announcement beats compile date.
            "announce_date": [
                "申報日",
                "公告日",
                "公告日期",
                "財報發布日",
                "編制日",
                "announce_date",
                "announcement_date",
            ],
        },
        "optional": {
            "statement_type": ["報表別", "報表種類", "財報類別（1個別2個體3合併）"],
            "period_end": ["財報年月迄日"],
            "market": ["市場別", "市場", "market", "mkt"],
        },
        "date_fields": ["announce_date"],
        "key": ["symbol", "period", "announce_date"],
    },
}

MARKET_ALIASES = {
    "TWSE": "TWSE",
    "TSE": "TWSE",
    "上市": "TWSE",
    "TPEX": "TPEX",
    "OTC": "TPEX",
    "TPE": "TPEX",
    "上櫃": "TPEX",
}
# M0 restricts the universe to TWSE/TPEx common stock. These boards are
# recognised so they can be rejected with a precise reason rather than
# silently falling through as an unmapped market.
EXCLUDED_MARKETS = {"REG": "興櫃", "TIB": "臺灣創新板", "PSB": "公開發行"}
NULL_MARKERS = {"", "nan", "nat", "none", "-", "--", ".", "null"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_table(path: Path) -> pd.DataFrame:
    """Read a vendor export, sniffing encoding and separator.

    TEJ PRO exports UTF-16 tab-separated files with a .csv extension, so
    neither can be assumed from the suffix.
    """

    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str)

    head = path.open("rb").read(65536)
    encodings = ["utf-8-sig", "cp950", "utf-8"]
    if head[:2] in (b"\xff\xfe", b"\xfe\xff") or head[1:2] == b"\x00":
        encodings.insert(0, "utf-16")
    for encoding in encodings:
        try:
            sample = head.decode(encoding, errors="strict")
        except (UnicodeDecodeError, UnicodeError):
            continue
        first = sample.splitlines()[0] if sample.splitlines() else ""
        separator = "\t" if first.count("\t") > first.count(",") else ","
        try:
            return pd.read_csv(path, sep=separator, dtype=str, encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"cannot decode {path.name}; re-export as UTF-8 CSV")


def resolve_columns(
    frame: pd.DataFrame,
    module: dict[str, Any],
    overrides: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Map logical field -> actual column, reporting anything unresolved."""

    available = {str(c).strip(): str(c) for c in frame.columns}
    mapping: dict[str, str] = {}
    missing: list[str] = []
    for group, is_required in (("required", True), ("optional", False)):
        for field, candidates in module[group].items():
            if field in overrides:
                column = overrides[field]
                if column not in frame.columns:
                    missing.append(f"{field} (指定的欄位 '{column}' 不存在)")
                    continue
                mapping[field] = column
                continue
            for candidate in candidates:
                if candidate in available:
                    mapping[field] = available[candidate]
                    break
            else:
                if is_required:
                    missing.append(f"{field} (預期其中之一: {'、'.join(candidates)})")
    return mapping, missing


def normalize_date(value: Any) -> str | None:
    """Accept ISO, slash, ROC and compact forms; return ISO or None."""

    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in NULL_MARKERS:
        return None
    text = text.replace("/", "-").replace(".", "-")
    parts = text.split("-")
    if len(parts) == 3:
        try:
            year, month, day = (int(p) for p in parts)
        except ValueError:
            return None
        if year < 1911:  # ROC year
            year += 1911
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    if len(digits) == 7:  # ROC compact, e.g. 1140102
        try:
            return datetime(
                int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7])
            ).date().isoformat()
        except ValueError:
            return None
    return None


def normalize_market(value: Any) -> tuple[str | None, str | None]:
    """Return (market, reject_reason). Excluded boards get a precise reason."""

    text = str(value).strip().upper()
    if text.lower() in NULL_MARKERS:
        return None, "missing-market"
    if text in MARKET_ALIASES:
        return MARKET_ALIASES[text], None
    if text in EXCLUDED_MARKETS:
        return None, f"out-of-universe-board:{text}"
    for alias, target in MARKET_ALIASES.items():
        if alias in text:
            return target, None
    return None, "unmapped-market"


def normalize_symbol(value: Any) -> str | None:
    """TEJ packs code and name into one field, e.g. '1309 台達化'."""

    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in NULL_MARKERS:
        return None
    return text.split()[0] if text.split() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True, choices=sorted(MODULES))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="FIELD=COLUMN",
        help="覆寫欄位對應，例如 --map date=年月日",
    )
    parser.add_argument("--dry-run", action="store_true", help="只顯示欄位偵測結果")
    args = parser.parse_args(argv)

    if not args.input.is_file():
        raise SystemExit(f"input not found: {args.input}")
    if not args.dry_run and args.output_root is None:
        raise SystemExit("--output-root is required unless --dry-run")

    overrides: dict[str, str] = {}
    for item in args.map:
        if "=" not in item:
            raise SystemExit(f"--map expects FIELD=COLUMN, received {item!r}")
        field, column = item.split("=", 1)
        overrides[field.strip()] = column.strip()

    module = MODULES[args.module]
    frame = read_table(args.input)
    mapping, missing = resolve_columns(frame, module, overrides)

    report: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "module": args.module,
        "input": str(args.input),
        "input_sha256": file_sha256(args.input),
        "input_rows": int(len(frame)),
        "detected_columns": [str(c) for c in frame.columns],
        "resolved_mapping": mapping,
        "missing_required": missing,
    }

    if missing:
        report["verdict"] = "blocked-missing-required-columns"
        report["hint"] = "用 --map FIELD=COLUMN 指定實際欄名，或重新匯出含必要欄位"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    if args.dry_run:
        report["verdict"] = "dry-run-ok"
        report["sample"] = (
            frame[[mapping[f] for f in mapping]].head(3).to_dict(orient="records")
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for ordinal, record in enumerate(frame.to_dict(orient="records")):
        out: dict[str, Any] = {"source_row_ordinal": ordinal}
        reasons: list[str] = []
        for field, column in mapping.items():
            value = record.get(column)
            if field in module["date_fields"] or field.endswith("_date"):
                normalized = normalize_date(value)
                if normalized is None and field in module["required"]:
                    reasons.append(f"unparsable-required-date:{field}")
                out[field] = normalized
            elif field == "market":
                normalized, reason = normalize_market(value)
                if reason:
                    reasons.append(reason)
                out[field] = normalized
            elif field == "symbol":
                normalized = normalize_symbol(value)
                if normalized is None:
                    reasons.append("empty-required:symbol")
                out[field] = normalized
            else:
                text = None if value is None else str(value).strip()
                if text and text.lower() in NULL_MARKERS:
                    text = None
                if not text and field in module["required"]:
                    reasons.append(f"empty-required:{field}")
                out[field] = text

        # Fold TEJ's board-specific listing columns into one listing_date,
        # chosen by the row's own market so the two can never disagree.
        if module.get("resolve_listing_date") and not reasons:
            if not out.get("listing_date"):
                board = {
                    "TWSE": out.pop("listing_date_tse", None),
                    "TPEX": out.pop("listing_date_otc", None),
                }
                out["listing_date"] = board.get(out.get("market"))
                out["listing_date_basis"] = (
                    "board-column" if out["listing_date"] else "missing-at-source"
                )
            else:
                out["listing_date_basis"] = "single-column"
            out.pop("listing_date_tse", None)
            out.pop("listing_date_otc", None)
            if not out["listing_date"]:
                reasons.append("missing-listing-date")

        if reasons:
            rejected.append({**out, "reject_reasons": reasons})
        else:
            rows.append(out)

    # The listing export carries one row per reporting period, so the same
    # security repeats. Collapse to one row per security instance and record
    # any security whose repeated rows disagree instead of picking a winner.
    conflicts: list[dict[str, Any]] = []
    if module.get("deduplicate") and rows:
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        compare = ("listing_date", "delisting_date", "security_name")
        for row in rows:
            grouped.setdefault((row.get("market"), row.get("symbol")), []).append(row)
        deduplicated: list[dict[str, Any]] = []
        for key, group in grouped.items():
            variants = {tuple(row.get(f) for f in compare) for row in group}
            if len(variants) > 1:
                conflicts.append(
                    {
                        "market": key[0],
                        "symbol": key[1],
                        "variant_count": len(variants),
                        "variants": [list(v) for v in sorted(variants, key=str)],
                    }
                )
            keeper = dict(group[0])
            keeper["source_row_count"] = len(group)
            deduplicated.append(keeper)
        rows = deduplicated

    snapshot_id = hashlib.sha256(
        json.dumps(
            {
                "module": args.module,
                "input_sha256": report["input_sha256"],
                "mapping": mapping,
                "schema_id": SCHEMA_ID,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    root = Path(args.output_root) / "tej_snapshots" / snapshot_id
    if root.exists():
        report["verdict"] = "blocked-snapshot-exists"
        report["snapshot_id"] = snapshot_id
        report["snapshot_path"] = str(root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    (root / "source_files").mkdir(parents=True)
    (root / "normalized").mkdir()
    (root / "rejected").mkdir()
    shutil.copy2(args.input, root / "source_files" / args.input.name)

    imported_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        row.update(
            {
                "evidence_state": EVIDENCE_STATE,
                "vendor": VENDOR,
                "snapshot_id": snapshot_id,
                "source_file_sha256": report["input_sha256"],
                "imported_at": imported_at,
                "vendor_date_field": ",".join(
                    mapping[f] for f in module["date_fields"] if f in mapping
                ),
            }
        )

    if rows:
        pd.DataFrame(rows).to_parquet(root / "normalized" / "rows.parquet", index=False)
    if rejected:
        pd.DataFrame(rejected).to_parquet(
            root / "rejected" / "rows.parquet", index=False
        )
    if conflicts:
        (root / "rejected" / "conflicts.json").write_text(
            json.dumps(conflicts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    duplicate_keys = 0
    if rows:
        key_fields = [f for f in module["key"] if f in mapping]
        seen = pd.DataFrame(rows)[key_fields]
        duplicate_keys = int(seen.duplicated().sum())

    report.update(
        {
            "verdict": "imported",
            "snapshot_id": snapshot_id,
            "snapshot_path": str(root),
            "imported_at": imported_at,
            "accepted_rows": len(rows),
            "rejected_rows": len(rejected),
            "duplicate_keys": duplicate_keys,
            "conflicting_securities": len(conflicts),
            "evidence_state": EVIDENCE_STATE,
            "lane": "licensed-vendor",
            "canonical_lane": False,
            "reject_reason_counts": {
                reason: sum(1 for r in rejected if reason in r["reject_reasons"])
                for reason in sorted(
                    {reason for r in rejected for reason in r["reject_reasons"]}
                )
            },
        }
    )
    (root / "import_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
