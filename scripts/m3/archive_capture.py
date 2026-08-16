"""Durably archive a window capture shadow to primary and separate-volume backup.

Additive only: refuses to write if either destination already exists, verifies
every copy file by file, and re-derives every blob hash from stored bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RECORD_NAME = "archival_record.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict:
    entries: dict[str, str] = {}
    total = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == RECORD_NAME:
            continue
        entries[relative] = file_sha256(path)
        total += path.stat().st_size
    payload = "".join(f"{k}|{v}\n" for k, v in sorted(entries.items())).encode("utf-8")
    return {
        "files": len(entries),
        "bytes": total,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "entries": entries,
    }


def verify_blobs(root: Path) -> dict:
    checked = 0
    mismatches: list[str] = []
    missing: list[str] = []
    for manifest_path in sorted((root / "raw_observations").rglob("manifest.json")):
        manifest = json.loads(manifest_path.read_bytes())
        blob_id = str(manifest["blob_id"])
        blob = root / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
        if not blob.is_file():
            missing.append(blob_id)
            continue
        actual = file_sha256(blob)
        checked += 1
        if actual != blob_id or actual != str(manifest["payload_sha256"]):
            mismatches.append(blob_id)
    return {
        "blobs_verified": checked,
        "hash_mismatches": mismatches,
        "missing_blobs": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--record-id", required=True)
    args = parser.parse_args(argv)

    report: dict = {
        "schema_id": "tw-alpha-m3-durable-archival/1.0.0",
        "record_id": args.record_id,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "temporary_source": str(args.source),
        "copies": {},
        "retention": "indefinite; automatic_deletion=disabled",
    }

    source_tree = tree_manifest(args.source)
    report["source_tree"] = {k: v for k, v in source_tree.items() if k != "entries"}
    report["source_blob_verification"] = verify_blobs(args.source)

    for name, destination in (("primary", args.primary), ("backup", args.backup)):
        if destination.exists():
            report["verdict"] = f"blocked-{name}-exists"
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(args.source, destination)
        tree = tree_manifest(destination)
        report["copies"][name] = {
            "path": str(destination),
            "files": tree["files"],
            "bytes": tree["bytes"],
            "tree_sha256": tree["sha256"],
            "per_file_identical_to_source": tree["entries"] == source_tree["entries"],
            "blob_verification": verify_blobs(destination),
        }

    ok = all(
        copy["per_file_identical_to_source"]
        and copy["blob_verification"]["hash_mismatches"] == []
        and copy["blob_verification"]["missing_blobs"] == []
        for copy in report["copies"].values()
    )
    report["verdict"] = "archived-and-verified" if ok else "failed-verification"
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if ok:
        payload = json.dumps(
            report, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        for destination in (args.primary, args.backup):
            (destination / RECORD_NAME).write_bytes(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
