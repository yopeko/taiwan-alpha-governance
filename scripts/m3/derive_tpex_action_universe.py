"""Derive the TPEx symbol universe for a corporate-action backfill window.

MOPS is queried one symbol-year at a time, so the backfill needs a list of
symbols before it can start. Where that list comes from decides what the
backfill can ever find.

The 2024-2026 lane used 899 symbols derived from the 2025-2026 price
captures. Reusing that file for 2019-2023 would ask today's TPEx membership
about six years ago, and every company that left the board before 2024 would
be absent -- silently, with no reason code, exactly the survivorship shape
this project has now found twice (the quarterly-financials lifecycle lane,
and the securities dropped by the M6 export).

So the universe is re-derived from the sessions themselves: a symbol belongs
in it because the exchange printed a quote for it inside the window. That
keeps the selection mechanism uncorrelated with the failure mode it must not
hide -- delisting.

Reads the price archives read-only and replays each observation through the
same offline parser the staging build uses, so the common-stock filter and
the symbol field are the registry's, not this script's.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_state import producer  # noqa: E402

from capture_window import protected_fingerprints  # noqa: E402
from market_status_parsers import build_m3_parser_registry  # noqa: E402
from market_status_sources import build_m3_registry  # noqa: E402
from tw_sepa_screener.parse_replay import ParseReplayStore  # noqa: E402
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402

SCHEMA_ID = "tw-alpha-m3-tpex-action-universe/1.0.0"
RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
PRICE_SOURCE = "TPEX-PRICE-HIST"
PRODUCER = producer()


class UniverseError(RuntimeError):
    """Raised when the derivation cannot be trusted."""


def assert_shadow(root: Path) -> Path:
    """Replay output is scratch, but it still must not land in a store."""

    resolved = root.resolve()
    scratch_base = Path("C:/tmp").resolve()
    data_tree = RAW.resolve().parent
    if not resolved.is_relative_to(scratch_base):
        raise UniverseError(f"replay root must be under C:/tmp: {resolved}")
    if resolved.is_relative_to(data_tree):
        raise UniverseError(f"replay root must not be inside the data tree: {resolved}")
    return resolved


def parsed_rows(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_bytes())
    rows_path = manifest.get("rows_path")
    if not rows_path:
        return []
    return pq.read_table(manifest_path.parent / str(rows_path)).to_pylist()


def first_present(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def derive(
    archives: tuple[Path, ...],
    *,
    replay_root: Path,
    window: tuple[date, date],
) -> dict[str, Any]:
    root = assert_shadow(replay_root)
    root.mkdir(parents=True, exist_ok=True)

    before = protected_fingerprints()
    source_registry = build_m3_registry()
    parser_registry = build_m3_parser_registry()
    # Frozen clock for the same reason the staging build freezes one: the
    # replay manifests must be byte-identical across reruns.
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)

    lo, hi = window
    symbols: dict[str, dict[str, str]] = {}
    sessions_seen = 0
    observations_replayed = 0
    empty_parses = 0
    not_parsed: dict[str, int] = {}

    for archive in archives:
        if not archive.is_dir():
            raise UniverseError(f"missing archive: {archive}")
        raw_store = RawCaptureStore(archive, source_registry, producer=PRODUCER)
        parse_store = ParseReplayStore(
            root, raw_store, parser_registry, producer=PRODUCER, clock=lambda: fixed
        )
        for manifest_path in sorted((archive / "raw_observations").rglob("manifest.json")):
            manifest = json.loads(manifest_path.read_bytes())
            if str(manifest.get("capture_status")) != "hash-verified":
                continue
            if str(manifest.get("source_id")) != PRICE_SOURCE:
                continue
            period = str(manifest.get("logical_period") or "")
            if not period.startswith("session:"):
                continue
            session = date.fromisoformat(period.split(":", 1)[1])
            if not (lo <= session <= hi):
                continue

            parser_ids = parser_registry.compatible_parser_ids(manifest)
            if not parser_ids:
                raise UniverseError(f"no parser for {PRICE_SOURCE} at {session}")
            parsed = parse_store.replay(manifest_path, parser_ids[0])
            observations_replayed += 1
            if parsed.parse_status != "parsed":
                # A closed session parses to nothing. That is evidence, not a
                # gap, and it simply contributes no symbols.
                not_parsed[parsed.parse_status] = not_parsed.get(parsed.parse_status, 0) + 1
                continue

            rows = parsed_rows(parsed.manifest_path)
            if not rows:
                # TPEx answers a closed date with zero rows rather than a
                # parse failure, so `parsed` alone does not mean a session
                # happened. Counting those as sessions would overstate the
                # window by every weekend in it.
                empty_parses += 1
                continue

            sessions_seen += 1
            for source_row in rows:
                symbol = str(
                    first_present(source_row, "symbol", "security_id", "code") or ""
                ).strip()
                if not symbol:
                    continue
                name = str(first_present(source_row, "name", "security_name") or "").strip()
                iso = session.isoformat()
                entry = symbols.get(symbol)
                if entry is None:
                    symbols[symbol] = {
                        "first_session": iso,
                        "last_session": iso,
                        "last_name": name,
                    }
                else:
                    if iso < entry["first_session"]:
                        entry["first_session"] = iso
                    if iso > entry["last_session"]:
                        entry["last_session"] = iso
                        entry["last_name"] = name or entry["last_name"]

    after = protected_fingerprints()
    if before != after:
        raise UniverseError("a protected store changed during a read-only derivation")

    return {
        "schema_id": SCHEMA_ID,
        "archives": [str(a) for a in archives],
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()},
        "source_id": PRICE_SOURCE,
        "sessions_with_rows": sessions_seen,
        "parsed_but_zero_rows": empty_parses,
        "observations_replayed": observations_replayed,
        "observations_not_parsed": dict(sorted(not_parsed.items())),
        "symbol_count": len(symbols),
        "symbols": symbols,
        "producer": PRODUCER,
        "protected_unchanged": before == after,
        "derivation_note": (
            "Symbols are those the exchange actually quoted inside the window, "
            "never today's membership list, so securities that left the board "
            "before the list was drawn are included."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="symbols JSON list")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2023-12-31")
    parser.add_argument(
        "--archive",
        action="append",
        default=None,
        help="price archive directory; repeatable",
    )
    parser.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="existing symbols JSON, to report what it would have missed",
    )
    args = parser.parse_args(argv)

    archives = tuple(
        Path(a) for a in (args.archive or [str(RAW / "m3_window_2019-01-01_2024-12-31")])
    )
    result = derive(
        archives,
        replay_root=args.replay_root,
        window=(date.fromisoformat(args.start), date.fromisoformat(args.end)),
    )

    ordered = sorted(result["symbols"])
    if args.compare_to and args.compare_to.exists():
        prior = set(json.loads(args.compare_to.read_text(encoding="utf-8")))
        # The symbols the old list would have missed are precisely the
        # securities that stopped trading before it was drawn. Recording the
        # number is the point: it is the survivorship exposure this step closes.
        missed = sorted(set(ordered) - prior)
        result["comparison"] = {
            "prior_list": str(args.compare_to),
            "prior_count": len(prior),
            "missing_from_prior": len(missed),
            "missing_symbols": missed,
            "in_prior_but_not_in_window": len(prior - set(ordered)),
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(ordered, ensure_ascii=False), encoding="utf-8")
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"symbols={len(ordered)} sessions={result['sessions_with_rows']}")
    if "comparison" in result:
        c = result["comparison"]
        print(
            f"prior={c['prior_count']} "
            f"missing_from_prior={c['missing_from_prior']} "
            f"in_prior_only={c['in_prior_but_not_in_window']}"
        )
    print("protected_unchanged:", result["protected_unchanged"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
