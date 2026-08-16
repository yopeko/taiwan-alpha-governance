from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tw_sepa_screener.archive_audit import audit_m2_archive
from tw_sepa_screener.parse_replay import ParseReplayStore
from tw_sepa_screener.parsers.formal import build_formal_p0_parser_registry
from tw_sepa_screener.quality_events import QualityStore
from tw_sepa_screener.raw_capture import RawCaptureStore
from tw_sepa_screener.sources.raw_registry import (
    P0_FORMAL_SOURCES,
    build_p0_formal_registry,
)


ROOT = Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03")
QUALITY_RELATIVE = Path(
    "quality_events/formal-p0-cross-source/1/2026/08/03/"
    "6fcb5b423045245c67cde1af46a86dfb31488851df95874e85bd79d80fe65e2b/"
    "quality_manifest.json"
)
EXPECTED_MANIFEST_SHA256 = (
    "4dce384e265a6e8246c75063fcfc17c962833bd774e7df12f43d17589ed47179"
)
EXPECTED_INITIAL_EVENT_SHA256 = (
    "5e74c62f933995b7c3c912c068fabde2717a6b7f8e26a9bdce3ec7e033b2d008"
)
PRODUCER = {
    "name": "tw-sepa-screener",
    "commit": "fb87f62f8c2c68e2b85982cd102a35fd935bc0a4",
    "dirty_fingerprint": (
        "20e6e5b1cd57c17d82651d4bf985e3d82365a55a1b86850a2f8ec01e85f34f8e"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    quality_manifest = ROOT / QUALITY_RELATIVE
    initial_event = quality_manifest.parent / "decision_event.json"
    if sha256(quality_manifest) != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError("quality manifest SHA-256 preflight mismatch")
    if sha256(initial_event) != EXPECTED_INITIAL_EVENT_SHA256:
        raise RuntimeError("initial event SHA-256 preflight mismatch")
    existing_releases = list((ROOT / "quality_releases").glob("**/event.json"))
    if existing_releases:
        raise RuntimeError("release already exists; refusing a duplicate")

    raw_store = RawCaptureStore(
        ROOT,
        build_p0_formal_registry(),
        producer=PRODUCER,
    )
    parse_store = ParseReplayStore(
        ROOT,
        raw_store,
        build_formal_p0_parser_registry(),
        producer=PRODUCER,
    )
    quality_store = QualityStore(ROOT, parse_store, producer=PRODUCER)
    quality = quality_store.verify_quality_run(quality_manifest)
    manifest = json.loads(quality_manifest.read_bytes())
    expected_identity = {
        "quality_run_id": (
            "6fcb5b423045245c67cde1af46a86dfb31488851df95874e85bd79d80fe65e2b"
        ),
        "source_id": "TWSE-ACTIONS-HIST",
        "endpoint_id": "exright-historical",
        "logical_period": "range:2026-07-31:2026-07-31",
        "decision": "quarantined",
    }
    for key, expected in expected_identity.items():
        if manifest.get(key) != expected:
            raise RuntimeError(f"quality identity preflight mismatch: {key}")
    if quality.decision != "quarantined":
        raise RuntimeError("quality run is no longer quarantined")

    expected_source_ids = [source.source_id for source in P0_FORMAL_SOURCES]
    before = audit_m2_archive(
        raw_store,
        parse_store,
        quality_store,
        expected_source_ids=expected_source_ids,
    )
    expected_blocker = [
        {
            "code": "quality-quarantined",
            "path": "quality_events",
            "error_type": "1",
        }
    ]
    if (
        before["raw_observations"] != 56
        or before["parse_runs"] != 56
        or before["quality_runs"] != 56
        or before["quality_release_events"] != 0
        or before["unresolved_quarantined_quality_runs"] != 1
        or before["blocking_issues"] != expected_blocker
    ):
        raise RuntimeError("archive pre-release audit is not the approved state")

    release = quality_store.release(
        quality_manifest,
        actor="Workspace user / human Project Owner",
        reason=(
            "Project Owner explicitly approved TWT49U internal retention and M3 "
            "research/validation use on 2026-08-03; external TWSE terms remain binding."
        ),
        evidence_refs=(
            "approval:M2-OWNER-APPROVAL-20260803-01",
            "approval-doc:docs/evidence/m2-owner-approval-decision-2026-08-03.md@"
            "sha256:7fea2089a944b55b544d265a86daa4473bbd1123582d97bcb7b8310db40eecbf",
            "codex-task-current:user-message:2026-08-03:3項全部批批准",
        ),
    )
    quality_store.verify_event(release.event_path)
    if sha256(quality_manifest) != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError("quality manifest changed during release")
    if sha256(initial_event) != EXPECTED_INITIAL_EVENT_SHA256:
        raise RuntimeError("initial event changed during release")

    after = audit_m2_archive(
        raw_store,
        parse_store,
        quality_store,
        expected_source_ids=expected_source_ids,
    )
    if (
        after["state"] != "passed"
        or after["quality_release_events"] != 1
        or after["released_quality_runs"] != 1
        or after["unresolved_quarantined_quality_runs"] != 0
        or after["blocking_issues"]
    ):
        raise RuntimeError("archive did not pass after the one approved release")

    event = json.loads(release.event_path.read_bytes())
    result = {
        "state": "passed",
        "decision_id": "M2-OWNER-APPROVAL-20260803-01",
        "release_event_id": release.event_id,
        "release_event_path": release.event_path.relative_to(ROOT).as_posix(),
        "release_event_sha256": sha256(release.event_path),
        "release_detected_at": event["detected_at"],
        "quality_manifest_sha256_before_after": EXPECTED_MANIFEST_SHA256,
        "initial_event_sha256_before_after": EXPECTED_INITIAL_EVENT_SHA256,
        "archive_audit": {
            key: after[key]
            for key in (
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
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
