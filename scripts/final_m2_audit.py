from __future__ import annotations

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


ROOTS = (
    Path(r"C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03"),
    Path(r"E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03"),
)
PRODUCER = {
    "name": "tw-sepa-screener",
    "commit": "fb87f62f8c2c68e2b85982cd102a35fd935bc0a4",
    "dirty_fingerprint": (
        "d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9"
    ),
}
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


def main() -> None:
    output = {}
    expected = [source.source_id for source in P0_FORMAL_SOURCES]
    for root in ROOTS:
        raw = RawCaptureStore(root, build_p0_formal_registry(), producer=PRODUCER)
        parsed = ParseReplayStore(
            root,
            raw,
            build_formal_p0_parser_registry(),
            producer=PRODUCER,
        )
        quality = QualityStore(root, parsed, producer=PRODUCER)
        audit = audit_m2_archive(
            raw,
            parsed,
            quality,
            expected_source_ids=expected,
        )
        output[str(root)] = {key: audit[key] for key in SUMMARY_KEYS}
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
