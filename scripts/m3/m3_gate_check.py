"""M3 concurrent-change gate: re-verify protected fingerprints and M2 archives.

Read-only. Compares against the fingerprints frozen in
docs/evidence/m3-entry-baseline-2026-08-03.md.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_state import producer  # noqa: E402

from tw_sepa_screener.archive_audit import audit_m2_archive
from tw_sepa_screener.parse_replay import ParseReplayStore
from tw_sepa_screener.parsers.formal import build_formal_p0_parser_registry
from tw_sepa_screener.quality_events import QualityStore
from tw_sepa_screener.raw_capture import RawCaptureStore
from tw_sepa_screener.sources.raw_registry import (
    P0_FORMAL_SOURCES,
    build_p0_formal_registry,
)

PRODUCER = producer()

BASELINE = {
    "duckdb": {
        "path": r"C:\project\tw-sepa-screener\data\tw_sepa.duckdb",
        "bytes": 426258432,
        "sha256": (
            "b35ee8e6e76e6e6e12a14a241d03dcf8d8252a4d9756c56972ef28d05fcd26f1"
        ),
    },
    "legacy_raw": {
        "path": r"C:\project\tw-sepa-screener\data\raw",
        "files": 4991,
        "bytes": 188514234,
        "sha256": (
            "6c69763e244bf4bf6b096ccd052ebafc4b05dfccc23441dc1999506f6a7d2e03"
        ),
    },
    "stock_master": {
        "path": r"C:\project\tw-sepa-screener\data\stock_master.csv",
        "bytes": 174314,
        "sha256": (
            "f179c40e945bfc1e80a2f46922f26605d92b68043ca07841aed89ac7fa8e166c"
        ),
    },
}

ARCHIVES = {
    "primary": Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03"),
    "backup": Path(r"E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03"),
}
ARCHIVE_TREE_SHA256 = (
    "31f31094f772c3c9a4f78e6234497a74fdf40e28560e6f88dd9415d43e1934a0"
)
SUMMARY_KEYS = (
    "state",
    "raw_observations",
    "parse_runs",
    "quality_runs",
    "quality_decisions",
    "quality_release_events",
    "released_quality_runs",
    "unresolved_quarantined_quality_runs",
    "missing_sources",
    "unusable_sources",
    "blocking_issues",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_fingerprint(root: Path) -> dict[str, object]:
    """Manifest SHA-256 over sorted `relative_path|file_sha256` lines."""

    lines: list[str] = []
    total_bytes = 0
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix()
        lines.append(f"{relative}|{file_sha256(path)}")
        total_bytes += path.stat().st_size
    payload = "".join(f"{line}\n" for line in sorted(lines)).encode("utf-8")
    return {
        "files": len(files),
        "bytes": total_bytes,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def audit(root: Path) -> dict[str, object]:
    raw = RawCaptureStore(root, build_p0_formal_registry(), producer=PRODUCER)
    parsed = ParseReplayStore(
        root, raw, build_formal_p0_parser_registry(), producer=PRODUCER
    )
    quality = QualityStore(root, parsed, producer=PRODUCER)
    result = audit_m2_archive(
        raw,
        parsed,
        quality,
        expected_source_ids=[s.source_id for s in P0_FORMAL_SOURCES],
    )
    return {key: result[key] for key in SUMMARY_KEYS}


def main() -> None:
    report: dict[str, object] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "protected": {},
        "archives": {},
        "verdict": "unknown",
    }
    drift: list[str] = []

    duck = Path(BASELINE["duckdb"]["path"])
    observed = {"bytes": duck.stat().st_size, "sha256": file_sha256(duck)}
    matches = (
        observed["bytes"] == BASELINE["duckdb"]["bytes"]
        and observed["sha256"] == BASELINE["duckdb"]["sha256"]
    )
    report["protected"]["duckdb"] = {"observed": observed, "matches_baseline": matches}
    if not matches:
        drift.append("duckdb")

    legacy = tree_fingerprint(Path(BASELINE["legacy_raw"]["path"]))
    matches = (
        legacy["files"] == BASELINE["legacy_raw"]["files"]
        and legacy["bytes"] == BASELINE["legacy_raw"]["bytes"]
        and legacy["sha256"] == BASELINE["legacy_raw"]["sha256"]
    )
    report["protected"]["legacy_raw"] = {
        "observed": legacy,
        "matches_baseline": matches,
    }
    if not matches:
        drift.append("legacy_raw")

    master = Path(BASELINE["stock_master"]["path"])
    observed = {"bytes": master.stat().st_size, "sha256": file_sha256(master)}
    matches = (
        observed["bytes"] == BASELINE["stock_master"]["bytes"]
        and observed["sha256"] == BASELINE["stock_master"]["sha256"]
    )
    report["protected"]["stock_master"] = {
        "observed": observed,
        "matches_baseline": matches,
    }
    if not matches:
        drift.append("stock_master")

    for name, root in ARCHIVES.items():
        tree = tree_fingerprint(root)
        report["archives"][name] = {
            "path": str(root),
            "tree": tree,
            "tree_matches_baseline": tree["sha256"] == ARCHIVE_TREE_SHA256,
            "audit": audit(root),
        }

    archives_ok = all(
        item["tree_matches_baseline"] and item["audit"]["state"] == "passed"
        for item in report["archives"].values()
    )
    report["protected_drift"] = drift
    report["verdict"] = (
        "clean" if not drift and archives_ok else "concurrent-change-detected"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
