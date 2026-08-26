"""Properties the archives and staging layer must hold at all times.

These were previously demonstrated once, by hand, at the moment each archive
was created. A property that is only checked once is a claim, not a guarantee.
"""

from __future__ import annotations


import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RAW = Path(r"C:\project\tw-sepa-screener\data\raw_v2")

sys.path.insert(0, str(REPO / "scripts" / "m3"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

ARCHIVES = (
    "m2_2026-08-03",
    "m2_dailyprice96_2026-08-03",
    "m3_window_2025-01-01_2026-08-03",
    "m3_market_status_2025-01-01_2026-08-03",
    "m3_actions_2025-01-01_2026-08-03",
    "m3_tpex_actions_2024-2026",
)

# A bare mention of "password" is prose — the M2 evidence documents the
# redaction policy by naming the fields it redacts. What matters is a
# credential with a *value* attached, or a token with a recognisable shape.
SECRET_PATTERNS = (
    r"(?:api[_-]?key|secret[_-]?key|password|passwd|pwd|access[_-]?token)"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+]{8,}",
    r"authorization\s*:\s*bearer\s+[A-Za-z0-9_\-.]{8,}",
    r"sk-[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"mongodb(?:\+srv)?://[^\s:]+:[^\s@]+@",
    r"postgres(?:ql)?://[^\s:]+:[^\s@]+@",
)
# Placeholders that are documentation, not credentials.
SECRET_ALLOWLIST = ("[REDACTED]", "you@example.com", "<your", "xxxxxxxx")


def sample_manifests(archive: Path, limit: int) -> list[Path]:
    """A deterministic sample: the first N by sorted path."""

    return sorted((archive / "raw_observations").rglob("manifest.json"))[:limit]


@pytest.mark.parametrize("name", ARCHIVES)
class TestContentAddressedBijection:
    """A blob's stored bytes must hash back to the id that addresses it."""

    def test_blob_id_equals_hash_of_stored_payload(self, name):
        archive = RAW / name
        if not archive.is_dir():
            pytest.skip(f"{name} not present on this machine")
        checked = 0
        for manifest_path in sample_manifests(archive, 40):
            manifest = json.loads(manifest_path.read_bytes())
            if str(manifest.get("capture_status")) != "hash-verified":
                continue
            blob_id = str(manifest["blob_id"])
            blob = (
                archive / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
            )
            assert blob.is_file(), f"missing payload for {blob_id}"
            digest = hashlib.sha256(blob.read_bytes()).hexdigest()
            assert digest == blob_id
            assert digest == str(manifest["payload_sha256"])
            assert blob.stat().st_size == int(manifest["payload_bytes"])
            checked += 1
        assert checked, f"no hash-verified observation sampled from {name}"

    def test_stored_payload_is_the_decoded_application_body(self, name):
        """`content_encoding` describes the transport, not the stored bytes.

        The capture contract stores exact application-visible bytes, so a
        response served with `Content-Encoding: gzip` is archived already
        decoded. Asserting this stops a future reader from "helpfully" adding
        a gunzip step that would corrupt every payload it touched.
        """

        archive = RAW / name
        if not archive.is_dir():
            pytest.skip(f"{name} not present on this machine")
        checked = 0
        for manifest_path in sample_manifests(archive, 10):
            manifest = json.loads(manifest_path.read_bytes())
            if str(manifest.get("capture_status")) != "hash-verified":
                continue
            blob_id = str(manifest["blob_id"])
            blob = (
                archive / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
            )
            raw = blob.read_bytes()
            assert raw, "stored payload is empty"
            assert raw[:2] != b"\x1f\x8b", (
                "payload is still gzip-framed; the archive should hold the "
                "decoded application body"
            )
            content_type = str(manifest.get("content_type") or "").lower()
            if "json" in content_type:
                json.loads(raw.decode("utf-8-sig"))
            assert hashlib.sha256(raw).hexdigest() == blob_id
            checked += 1
        assert checked, f"no hash-verified observation sampled from {name}"


class TestObservationsWithoutPayloadAreDeclaredNotMissing:
    """A recorded failed attempt is evidence; it must not look like data loss."""

    def test_only_non_hash_verified_observations_lack_a_payload(self):
        archive = RAW / "m3_tpex_actions_2024-2026"
        if not archive.is_dir():
            pytest.skip("TPEx action archive not present")
        missing_but_verified = []
        for manifest_path in (archive / "raw_observations").rglob("manifest.json"):
            manifest = json.loads(manifest_path.read_bytes())
            blob_id = str(manifest.get("blob_id") or "")
            if not blob_id:
                continue
            blob = (
                archive / "raw_blobs" / "sha256" / blob_id[:2] / blob_id / "payload.bin"
            )
            if blob.is_file():
                continue
            if str(manifest.get("capture_status")) == "hash-verified":
                missing_but_verified.append(str(manifest.get("logical_period")))
        assert not missing_but_verified, (
            f"hash-verified observations with no payload: {missing_but_verified}"
        )


class TestNoPlaintextSecrets:
    """Nothing committed or archived may carry a credential in the clear."""

    def test_no_committed_file_contains_a_secret_pattern(self):
        import re

        pattern = re.compile("|".join(SECRET_PATTERNS), re.IGNORECASE)
        offenders: list[str] = []
        for path in REPO.rglob("*"):
            if not path.is_file():
                continue
            parts = set(path.parts)
            if parts & {".git", ".venv", "__pycache__", ".codex_tmp", "data"}:
                continue
            if path.suffix.lower() not in {".py", ".md", ".json", ".txt", ".csv", ".yml", ".yaml"}:
                continue
            if path.name == "test_archive_properties.py":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in pattern.finditer(text):
                hit = match.group(0)
                if any(token.lower() in hit.lower() for token in SECRET_ALLOWLIST):
                    continue
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO)}:{line}:{hit[:32]}")
        assert not offenders, f"possible plaintext secret: {offenders[:10]}"

    def test_tej_snapshots_carry_no_connection_string(self):
        lane = RAW / "m3_tej_licensed_2026-08-16"
        if not lane.is_dir():
            pytest.skip("TEJ lane not present")
        for manifest in lane.rglob("import_manifest.json"):
            text = manifest.read_text(encoding="utf-8").lower()
            for marker in ("password", "api_key", "apikey", "token=", "pwd="):
                assert marker not in text, f"{manifest.name} contains {marker}"


class TestStagingDeterminism:
    """Same frozen inputs must reproduce the same dataset id and index."""

    def test_two_builds_agree(self, tmp_path):
        if not all((RAW / name).is_dir() for name in ARCHIVES):
            pytest.skip("archives not present on this machine")
        pytest.importorskip('tw_sepa_screener', reason='needs Taiwan Core checkout')
        from build_staging import build

        first = build(tmp_path / "a", limit_per_source=1)
        second = build(tmp_path / "b", limit_per_source=1)
        assert first["dataset_id"] == second["dataset_id"]
        assert first["staging_index_sha256"] == second["staging_index_sha256"]
        assert first["adopted_observations"] == second["adopted_observations"]

    def test_a_build_cannot_write_to_a_protected_store(self, tmp_path):
        """Structurally, and not by watching fingerprints afterwards.

        This used to assert `production_unchanged is True` on both builds, and
        it went red on 2026-08-26 at 16:02 because the legacy daily pipeline
        had written its own stores between 15:40 and 16:01. Nothing about the
        staging build was wrong; the assertion was watching a shared resource
        that a different system updates on a schedule.

        A test that goes red for a reason unrelated to what it names is one
        people learn to ignore, which is the same lesson the pre-commit hook
        already records about being slow enough to bypass.

        What the build actually guarantees is checked instead:
        `assert_publishable` refuses a staging root that is, contains, or sits
        inside a protected path, before a byte is written. Concurrent external
        writes are reported in `protected_changed` and are not this build's
        failure.
        """

        if not all((RAW / name).is_dir() for name in ARCHIVES):
            pytest.skip("archives not present on this machine")
        pytest.importorskip("tw_sepa_screener", reason="needs Taiwan Core checkout")
        from build_staging import (
            PROTECTED_PATHS,
            StagingError,
            assert_publishable,
            build,
        )

        assert PROTECTED_PATHS, "no protected paths declared; the guard guards nothing"
        for protected in PROTECTED_PATHS:
            with pytest.raises(StagingError):
                assert_publishable(protected)
            with pytest.raises(StagingError):
                assert_publishable(protected / "nested")

        manifest = build(tmp_path / "c", limit_per_source=1)
        assert "protected_changed" in manifest, (
            "the build no longer reports which protected stores moved, so an "
            "external writer would go unnoticed"
        )

    def test_dataset_id_changes_when_the_builder_changes(self, tmp_path):
        """A different builder must not masquerade as the same dataset."""

        if not all((RAW / name).is_dir() for name in ARCHIVES):
            pytest.skip("archives not present on this machine")
        pytest.importorskip('tw_sepa_screener', reason='needs Taiwan Core checkout')
        import build_staging

        original = build_staging.SOURCE_MAP_VERSION
        first = build_staging.build(tmp_path / "a", limit_per_source=1)
        try:
            build_staging.SOURCE_MAP_VERSION = original + "-probe"
            second = build_staging.build(tmp_path / "b", limit_per_source=1)
        finally:
            build_staging.SOURCE_MAP_VERSION = original
        assert first["dataset_id"] != second["dataset_id"]
