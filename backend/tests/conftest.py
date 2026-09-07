from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest


@pytest.fixture
def capture_root(tmp_path: Path) -> Path:
    root = tmp_path / "captures"
    capture = root / "capture_test_001"
    source = capture / "source"
    (source / "calibration").mkdir(parents=True)
    (capture / "ego").mkdir()
    (capture / "ego" / "meta").mkdir()
    (capture / "ego" / "meta" / "info.json").write_text("{}\n", encoding="utf-8")
    (capture / "robot_datasets" / "nero-hand-v1").mkdir(parents=True)
    (capture / "bundle.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "1.0",
                "capture_id": capture.name,
                "created_at": "2026-09-07T01:00:00Z",
                "updated_at": "2026-09-07T02:00:00Z",
                "status": "ready",
                "stages": {"source": {"status": "ready"}, "ego": {"status": "ready"}},
                "datasets": {"ego": "ego", "robots": {"nero-hand-v1": "robot_datasets/nero-hand-v1"}},
            }
        ),
        encoding="utf-8",
    )
    (source / "acquisition.json").write_text(
        json.dumps(
            {
                "config": {
                    "camera": "Orbbec Test",
                    "fps": 60,
                    "frame_count": 120,
                    "rgb": {"format": "MJPG"},
                    "max_sync_error_ms": 0.08,
                    "persisted_cadence": {
                        "passed": True,
                        "minimum_hz": 59.4,
                        "color": {"actual_hz": 59.9},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (source / "quality_profile.json").write_text(
        json.dumps({
            "schema_version": "1.1", "profile_id": "test", "revision": 1,
            "acquisition": {
                "rgb": {"required": True, "min_width": 1280, "min_height": 800, "min_fps": 60, "min_measured_fps": 59.4},
                "depth": {"required": True, "min_width": 848, "min_height": 480, "min_fps": 60, "min_measured_fps": 59.4},
            },
        }), encoding="utf-8",
    )
    recording = source / "recording.bin"
    recording.write_bytes(b"capture-test-data")
    checksum_rows = []
    for path in sorted(source.rglob("*")):
        if path.is_file():
            checksum_rows.append({
                "path": path.relative_to(source).as_posix(), "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    (source / "checksums_original.json").write_text(
        json.dumps({"algorithm": "sha256", "files": checksum_rows}),
        encoding="utf-8",
    )
    return root
