"""Durably archive the 96-session TWSE daily-price repair shadow.

Additive only. Verifies the temporary shadow against its recorded fingerprint,
copies it to a new primary archive path and a separate-volume backup, then
re-verifies every blob hash and the embedded archive audit. Existing immutable
files are never rewritten; the archival record is written as a new sibling file.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(r"C:\tmp\tw-alpha-m2-shadow-20260803-02")
PRIMARY = Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_dailyprice96_2026-08-03")
BACKUP = Path(r"E:\tw-sepa-screener-backup\raw_v2\m2_dailyprice96_2026-08-03")

EXPECTED = {
    "files": 673,
    "bytes": 26537610,
    "tree_sha256": (
        "e1d103ec147462705cf8ee03c032f622bc75f328cc6e0a28d10a2490e32683c3"
    ),
    "run_id": (
        "3ca7b2d4d3b7e8a2711466bb584f6fbe54f6ccedfea34c5677015552435e81d7"
    ),
    "target_sha256": (
        "5ecf26e039b4d7fb9f6a2ff6bcc6aa2563d0c058f44f88102fce77c83eb7ab10"
    ),
}
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


def verify_blobs(root: Path) -> dict[str, object]:
    """Re-derive every raw payload hash from the stored blob bytes."""

    checked = 0
    mismatches: list[str] = []
    missing: list[str] = []
    for manifest_path in sorted((root / "raw_observations").rglob("manifest.json")):
        manifest = json.loads(manifest_path.read_bytes())
        blob_id = str(manifest["blob_id"])
        declared = str(manifest["payload_sha256"])
        candidates = list((root / "raw_blobs").rglob(f"{blob_id}*"))
        blobs = [p for p in candidates if p.is_file()]
        if not blobs:
            missing.append(blob_id)
            continue
        actual = file_sha256(blobs[0])
        checked += 1
        if actual != declared or actual != blob_id:
            mismatches.append(blob_id)
    return {
        "blobs_checked": checked,
        "hash_mismatches": mismatches,
        "missing_blobs": missing,
    }


def run_summary(root: Path) -> dict[str, object]:
    path = root / "shadow_runs" / EXPECTED["run_id"] / "run_manifest.json"
    manifest = json.loads(path.read_bytes())
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
        "archive_audit_state": audit.get("state"),
        "archive_audit_issues": audit.get("issues"),
        "archive_audit_blobs": audit.get("actual_blobs"),
    }


def main() -> int:
    report: dict[str, object] = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "schema_id": "tw-alpha-m3-durable-archival/1.0.0",
        "source": str(SOURCE),
        "copies": {},
    }

    source_tree = tree_manifest(SOURCE)
    source_ok = (
        source_tree["files"] == EXPECTED["files"]
        and source_tree["bytes"] == EXPECTED["bytes"]
        and source_tree["sha256"] == EXPECTED["tree_sha256"]
    )
    report["source_tree"] = {
        k: v for k, v in source_tree.items() if k != "entries"
    }
    report["source_matches_recorded_fingerprint"] = source_ok
    if not source_ok:
        report["verdict"] = "blocked-source-fingerprint-mismatch"
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    report["source_run"] = run_summary(SOURCE)
    report["source_blob_verification"] = verify_blobs(SOURCE)

    for name, destination in (("primary", PRIMARY), ("backup", BACKUP)):
        if destination.exists():
            report["copies"][name] = {
                "path": str(destination),
                "state": "blocked-destination-exists",
            }
            report["verdict"] = "blocked-destination-exists"
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SOURCE, destination)
        tree = tree_manifest(destination)
        identical = tree["entries"] == source_tree["entries"]
        report["copies"][name] = {
            "path": str(destination),
            "files": tree["files"],
            "bytes": tree["bytes"],
            "tree_sha256": tree["sha256"],
            "per_file_identical_to_source": identical,
            "tree_matches_recorded_fingerprint": (
                tree["sha256"] == EXPECTED["tree_sha256"]
            ),
            "blob_verification": verify_blobs(destination),
            "run": run_summary(destination),
        }

    ok = all(
        copy["per_file_identical_to_source"]
        and copy["tree_matches_recorded_fingerprint"]
        and copy["blob_verification"]["hash_mismatches"] == []
        and copy["blob_verification"]["missing_blobs"] == []
        and copy["run"]["state"] == "passed"
        for copy in report["copies"].values()
    )
    report["verdict"] = "archived" if ok else "failed-verification"
    report["retention"] = "indefinite; automatic_deletion=disabled"
    report["note"] = (
        "Copies are byte-identical to the temporary shadow. The immutable "
        "run manifest still records output_policy="
        "temporary-shadow-only-no-production-writer and was not rewritten; "
        "durability is asserted by this separate archival record."
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if ok:
        payload = json.dumps(
            report, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        for destination in (PRIMARY, BACKUP):
            (destination / RECORD_NAME).write_bytes(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
