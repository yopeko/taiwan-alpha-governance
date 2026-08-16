"""Verify the durably archived 96-session shadow copies.

Read-mostly: recomputes every blob hash, compares the three trees file by file,
and writes the archival record into the two durable copies.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(r"C:\tmp\tw-alpha-m2-shadow-20260803-02")
PRIMARY = Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_dailyprice96_2026-08-03")
BACKUP = Path(r"E:\tw-sepa-screener-backup\raw_v2\m2_dailyprice96_2026-08-03")

EXPECTED_TREE = "e1d103ec147462705cf8ee03c032f622bc75f328cc6e0a28d10a2490e32683c3"
RUN_ID = "3ca7b2d4d3b7e8a2711466bb584f6fbe54f6ccedfea34c5677015552435e81d7"
RECORD_NAME = "archival_record_2026-08-16.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict[str, object]:
    entries: dict[str, str] = {}
    total = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == RECORD_NAME:
            continue
        entries[relative] = file_sha256(path)
        total += path.stat().st_size
    payload = "".join(
        f"{name}|{digest}\n" for name, digest in sorted(entries.items())
    ).encode("utf-8")
    return {
        "files": len(entries),
        "bytes": total,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "entries": entries,
    }


def blob_path(root: Path, blob_id: str) -> Path:
    return root / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"


def verify_content(root: Path) -> dict[str, object]:
    checked = 0
    mismatches: list[str] = []
    missing: list[str] = []
    declared_bytes = 0
    sessions: list[str] = []
    for manifest_path in sorted((root / "raw_observations").rglob("manifest.json")):
        manifest = json.loads(manifest_path.read_bytes())
        blob_id = str(manifest["blob_id"])
        path = blob_path(root, blob_id)
        sessions.append(str(manifest["logical_period"]))
        if not path.is_file():
            missing.append(blob_id)
            continue
        actual = file_sha256(path)
        checked += 1
        declared_bytes += int(manifest["payload_bytes"])
        if actual != blob_id or actual != str(manifest["payload_sha256"]):
            mismatches.append(blob_id)
        if path.stat().st_size != int(manifest["payload_bytes"]):
            mismatches.append(f"{blob_id}:size")
    parsed = len(list((root / "parsed_observations").rglob("parse_manifest.json")))
    quality = len(list((root / "quality_events").rglob("*.json")))
    unique_sessions = sorted(set(sessions))
    return {
        "raw_observations": len(sessions),
        "blobs_verified": checked,
        "blob_hash_mismatches": mismatches,
        "missing_blobs": missing,
        "declared_payload_bytes": declared_bytes,
        "parse_manifests": parsed,
        "quality_event_files": quality,
        "unique_logical_periods": len(unique_sessions),
        "session_range": [unique_sessions[0], unique_sessions[-1]]
        if unique_sessions
        else [],
    }


def run_summary(root: Path) -> dict[str, object]:
    manifest = json.loads(
        (root / "shadow_runs" / RUN_ID / "run_manifest.json").read_bytes()
    )
    audit = manifest["archive_audit"]
    return {
        "run_id": manifest["run_id"],
        "state": manifest["state"],
        "target_count": manifest["target_count"],
        "accepted_sessions": manifest["accepted_sessions"],
        "failed_sessions": manifest["failed_sessions"],
        "target_sha256": manifest["target_sha256"],
        "output_policy": manifest["output_policy"],
        "production_unchanged": manifest["production_unchanged"],
        "embedded_audit_issues": audit.get("issues"),
        "embedded_audit_blobs": audit.get("actual_blobs"),
        "embedded_audit_capture_status": audit.get("capture_status_counts"),
    }


def main() -> int:
    report: dict[str, object] = {
        "schema_id": "tw-alpha-m3-durable-archival/1.0.0",
        "record_id": "tw-alpha-m3-dailyprice96-archival-20260816-01",
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "temporary_source": str(SOURCE),
        "purpose": (
            "Promote the 96-session TWSE daily-price repair shadow from a "
            "temporary C:\\tmp location to durable, auditable storage so it "
            "can serve as an M3.2 staging input."
        ),
        "copies": {},
    }

    trees: dict[str, dict[str, object]] = {}
    for name, root in (("source", SOURCE), ("primary", PRIMARY), ("backup", BACKUP)):
        if not root.exists():
            report["verdict"] = f"blocked-missing-{name}"
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        trees[name] = tree_manifest(root)
        report["copies"][name] = {
            "path": str(root),
            "files": trees[name]["files"],
            "bytes": trees[name]["bytes"],
            "tree_sha256": trees[name]["sha256"],
            "tree_matches_recorded_fingerprint": (
                trees[name]["sha256"] == EXPECTED_TREE
            ),
            "content": verify_content(root),
            "run": run_summary(root),
        }

    identical = (
        trees["source"]["entries"] == trees["primary"]["entries"]
        and trees["source"]["entries"] == trees["backup"]["entries"]
    )
    report["all_copies_byte_identical"] = identical
    ok = identical and all(
        copy["tree_matches_recorded_fingerprint"]
        and copy["content"]["blob_hash_mismatches"] == []
        and copy["content"]["missing_blobs"] == []
        and copy["content"]["blobs_verified"] == 96
        and copy["run"]["state"] == "passed"
        for copy in report["copies"].values()
    )
    report["verdict"] = "archived-and-verified" if ok else "failed-verification"
    report["retention"] = "indefinite; automatic_deletion=disabled"
    report["scope_limits"] = [
        "TWSE only; contains no TPEx observations.",
        "96 non-contiguous sessions; not a continuous history.",
        "Does not by itself satisfy the G0-A fixed-window coverage requirement.",
        "The immutable run manifest still records output_policy="
        "temporary-shadow-only-no-production-writer and was not rewritten; "
        "durability is asserted by this separate append-only record.",
    ]
    report["protected_stores_written"] = []
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if ok:
        payload = json.dumps(
            report, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        for root in (PRIMARY, BACKUP):
            (root / RECORD_NAME).write_bytes(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
