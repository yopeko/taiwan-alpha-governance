"""M3.2: build the append-only point-in-time staging layer.

Reads the durable M2/M3 archives read-only, replays each observation through
its offline parser, evaluates quality where a policy exists, and emits staging
rows carrying the lineage the PIT contract requires.

Three invariants this builder is built around:

* **Append-only.** It publishes into a new empty root and refuses any target
  that is, or contains, a protected production store or an M2 archive.
* **Deterministic.** The dataset_id is content-addressed over the frozen
  inputs, policy versions and builder config, so the same inputs reproduce
  the same id and the same table hashes.
* **Honest tiers.** Rows are labelled with the evidence they actually have.
  A source without a quality policy is not silently promoted to the same tier
  as one that passed a gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_window import protected_fingerprints  # noqa: E402
from tw_sepa_screener.m2_quality_profiles import (  # noqa: E402
    build_daily_price_quality_policy,
)
from tw_sepa_screener.parse_replay import ParseReplayStore  # noqa: E402
from market_status_parsers import build_m3_parser_registry  # noqa: E402
from market_status_sources import build_m3_registry  # noqa: E402
from tw_sepa_screener.quality_events import QualityStore  # noqa: E402
from tw_sepa_screener.raw_capture import RawCaptureStore  # noqa: E402
# source registry composed via market_status_sources
from tw_sepa_screener.sources.raw_registry import (  # noqa: E402
    build_p0_formal_registry,
)

SCHEMA_ID = "tw-alpha-m3-staging/1.0.0"
SOURCE_MAP_VERSION = "tw-alpha-m3-source-map/1.1.0"
AVAILABILITY_POLICY_VERSION = "tw-alpha-m3-availability/1.0.0"
CONFLICT_POLICY_VERSION = "tw-alpha-m3-conflict/1.0.0"

RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")
ARCHIVES = (
    RAW / "m2_2026-08-03",
    RAW / "m2_dailyprice96_2026-08-03",
    RAW / "m3_window_2025-01-01_2026-08-03",
    RAW / "m3_market_status_2025-01-01_2026-08-03",
    RAW / "m3_actions_2025-01-01_2026-08-03",
    RAW / "m3_tpex_actions_2024-2026",
)

# Publishing anywhere at or inside these is forbidden.
PROTECTED_PATHS = (
    Path(r"C:\project\tw-sepa-screener\data\tw_sepa.duckdb"),
    Path(r"C:\project\tw-sepa-screener\data\raw"),
    Path(r"C:\project\tw-sepa-screener\data\stock_master.csv"),
    *ARCHIVES,
    Path(r"E:\tw-sepa-screener-backup"),
)

PRODUCER = {
    "name": "tw-sepa-screener",
    "commit": "fb87f62f8c2c68e2b85982cd102a35fd935bc0a4",
    "dirty_fingerprint": (
        "d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9"
    ),
}


class StagingError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        lines.append(f"{path.relative_to(root).as_posix()}|{file_sha256(path)}")
    return sha256_bytes("".join(f"{line}\n" for line in lines).encode("utf-8"))


def assert_publishable(target: Path) -> Path:
    """Refuse to publish onto production, an archive, or a non-empty directory."""

    resolved = target.resolve()
    for protected in PROTECTED_PATHS:
        try:
            protected_resolved = protected.resolve()
        except OSError:
            continue
        if resolved == protected_resolved or protected_resolved in resolved.parents:
            raise StagingError(f"refusing to publish into protected path: {resolved}")
        if resolved in protected_resolved.parents:
            raise StagingError(
                f"refusing to publish to a parent of a protected path: {resolved}"
            )
    if resolved.exists() and any(resolved.iterdir()):
        raise StagingError(f"staging root must be empty: {resolved}")
    return resolved


def build(
    staging_root: Path,
    *,
    limit_per_source: int = 0,
    freeze_clock: bool = True,
) -> dict[str, Any]:
    root = assert_publishable(staging_root)
    root.mkdir(parents=True, exist_ok=True)

    before = protected_fingerprints()
    source_registry = build_m3_registry()
    parser_registry = build_m3_parser_registry()
    price_policy = build_daily_price_quality_policy()
    quality_sources = set(price_policy.source_ids)

    # A frozen clock keeps the parse and quality manifests byte-identical
    # across rebuilds, which is what makes the determinism test meaningful.
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = (lambda: fixed) if freeze_clock else None

    rows: list[dict[str, Any]] = []
    per_source: dict[str, dict[str, Any]] = {}
    archive_fingerprints: dict[str, str] = {}
    # Two different things that must never be conflated: a source with no
    # offline parser at all, versus an observation whose parser ran and
    # correctly reported that the payload carries no parseable rows (a
    # non-trading day). The first is a coverage gap; the second is evidence.
    no_parser: dict[str, int] = {}
    non_parsed: dict[str, dict[str, int]] = {}

    for archive in ARCHIVES:
        if not archive.is_dir():
            raise StagingError(f"missing archive: {archive}")
        archive_fingerprints[archive.name] = tree_sha256(archive)

        raw_store = RawCaptureStore(archive, source_registry, producer=PRODUCER)
        parse_store = ParseReplayStore(
            root, raw_store, parser_registry, producer=PRODUCER, clock=clock
        )
        quality_store = QualityStore(
            root, parse_store, producer=PRODUCER, clock=clock
        )

        seen_per_source: dict[str, int] = {}
        for manifest_path in sorted(
            (archive / "raw_observations").rglob("manifest.json")
        ):
            manifest = json.loads(manifest_path.read_bytes())
            if str(manifest.get("capture_status")) != "hash-verified":
                continue
            source_id = str(manifest["source_id"])
            if limit_per_source:
                seen_per_source[source_id] = seen_per_source.get(source_id, 0) + 1
                if seen_per_source[source_id] > limit_per_source:
                    continue

            parser_ids = parser_registry.compatible_parser_ids(manifest)
            if not parser_ids:
                # No offline parser: the observation stays raw-only evidence
                # and is not admitted to the staging lane.
                no_parser[source_id] = no_parser.get(source_id, 0) + 1
                continue

            parsed = parse_store.replay(manifest_path, parser_ids[0])
            if parsed.parse_status != "parsed":
                bucket = non_parsed.setdefault(source_id, {})
                bucket[parsed.parse_status] = bucket.get(parsed.parse_status, 0) + 1
                continue

            quality_run_id = None
            quality_decision = None
            if source_id in quality_sources:
                observation = quality_store.evaluate(
                    parsed.manifest_path, price_policy
                )
                quality_run_id = observation.quality_run_id
                quality_decision = observation.decision

            tier = (
                "gated-full"
                if quality_run_id
                else "gated-parse-only-no-quality-policy"
            )
            record = {
                "archive": archive.name,
                "source_id": source_id,
                "endpoint_id": str(manifest["endpoint_id"]),
                "logical_period": str(manifest["logical_period"]),
                "snapshot_id": str(manifest["snapshot_id"]),
                "parse_run_id": parsed.parse_run_id,
                "quality_run_id": quality_run_id,
                "quality_decision": quality_decision,
                "row_count": int(
                    json.loads(parsed.manifest_path.read_bytes())["row_count"]
                ),
                "evidence_tier": tier,
                "evidence_state": "verified-snapshot",
                "source_locator": manifest_path.relative_to(archive).as_posix(),
            }
            record["record_id"] = sha256_bytes(canonical(record).encode("utf-8"))
            rows.append(record)

            summary = per_source.setdefault(
                source_id,
                {"observations": 0, "rows": 0, "tier": tier, "decisions": {}},
            )
            summary["observations"] += 1
            summary["rows"] += record["row_count"]
            if quality_decision:
                summary["decisions"][quality_decision] = (
                    summary["decisions"].get(quality_decision, 0) + 1
                )

    rows.sort(key=lambda r: (r["source_id"], r["logical_period"], r["snapshot_id"]))
    index_path = root / "staging_index.jsonl"
    index_path.write_text(
        "".join(canonical(r) + "\n" for r in rows), encoding="utf-8"
    )

    dataset_inputs = {
        "schema_id": SCHEMA_ID,
        "source_map_version": SOURCE_MAP_VERSION,
        "availability_policy_version": AVAILABILITY_POLICY_VERSION,
        "conflict_policy_version": CONFLICT_POLICY_VERSION,
        "quality_policy_code_hash": price_policy.code_hash,
        "producer": PRODUCER,
        "archive_fingerprints": archive_fingerprints,
        "builder_source_sha256": file_sha256(Path(__file__)),
        "adopted_records": [r["record_id"] for r in rows],
    }
    dataset_id = sha256_bytes(canonical(dataset_inputs).encode("utf-8"))

    after = protected_fingerprints()
    manifest = {
        "schema_id": SCHEMA_ID,
        "dataset_id": dataset_id,
        "predecessor_dataset_id": None,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "staging_root": str(root),
        "source_map_version": SOURCE_MAP_VERSION,
        "availability_policy_version": AVAILABILITY_POLICY_VERSION,
        "conflict_policy_version": CONFLICT_POLICY_VERSION,
        "quality_policy_code_hash": price_policy.code_hash,
        "builder_source_sha256": dataset_inputs["builder_source_sha256"],
        "archive_fingerprints": archive_fingerprints,
        "adopted_observations": len(rows),
        "adopted_rows": sum(r["row_count"] for r in rows),
        "per_source": per_source,
        "sources_without_parser": dict(sorted(no_parser.items())),
        "observations_not_parsed": {
            k: dict(sorted(v.items())) for k, v in sorted(non_parsed.items())
        },
        "not_parsed_note": (
            "A non-parsed status is the parser correctly reporting that the "
            "payload has no parseable rows, which on a daily-price source "
            "means a non-trading day. These are official-no-data evidence, "
            "not defects, and must be carried into M3.3 as such."
        ),
        "staging_index_sha256": file_sha256(index_path),
        "protected_before": before,
        "protected_after": after,
        "production_unchanged": before == after,
        "output_policy": "append-only-shadow; never writes production or archives",
        "evidence_tier_note": (
            "gated-full = raw hash-verified + parse verified + quality "
            "evaluated. gated-parse-only-no-quality-policy = parse verified "
            "but no quality policy exists for that source yet; such rows must "
            "not be treated as having passed a quality gate."
        ),
    }
    (root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--limit-per-source", type=int, default=0)
    args = parser.parse_args(argv)

    manifest = build(
        args.staging_root, limit_per_source=args.limit_per_source
    )
    summary = {
        k: manifest[k]
        for k in (
            "dataset_id",
            "adopted_observations",
            "adopted_rows",
            "production_unchanged",
            "staging_index_sha256",
            "sources_without_parser",
            "observations_not_parsed",
        )
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if manifest["production_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())
