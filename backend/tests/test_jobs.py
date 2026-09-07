import json
import sys
import time
from pathlib import Path

from app.config import Settings
from app.models import ProcessingRun, RunCreate
from app.services.catalog import CatalogService
from app.services.jobs import JobService


def settings_for(capture_root: Path, tmp_path: Path) -> Settings:
    return Settings(
        capture_roots=(capture_root,), lerobot_repo=tmp_path,
        lerobot_python=Path(sys.executable), state_dir=tmp_path / "state",
        export_root=tmp_path / "exports",
    )


def wait_for_terminal(service: JobService, run_id: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = service.get(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.005)
    raise AssertionError("run did not reach terminal state")


def test_real_source_integrity_hashes_files_and_persists_report(capture_root: Path, tmp_path: Path) -> None:
    bundle_path = capture_root / "capture_test_001/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["status"] = "building"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    catalog = CatalogService((capture_root,))
    service = JobService(catalog, settings_for(capture_root, tmp_path))

    run = service.create(RunCreate(capture_id="capture_test_001", root_id="root-1", pipeline="integrity"))
    final = wait_for_terminal(service, run.run_id)

    assert final.executor == "local"
    assert final.status == "completed"
    report = json.loads((capture_root / "capture_test_001/reports/capture_integrity_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["source_checksummed_files"] >= 3
    assert (tmp_path / "state/runs.json").is_file()


def test_integrity_detects_checksum_drift(capture_root: Path, tmp_path: Path) -> None:
    capture = capture_root / "capture_test_001"
    bundle_path = capture / "bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8")); bundle["status"] = "building"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    (capture / "source/recording.bin").write_bytes(b"changed-after-checksum")
    catalog = CatalogService((capture_root,))
    service = JobService(catalog, settings_for(capture_root, tmp_path))

    run = service.create(RunCreate(capture_id="capture_test_001", root_id="root-1", pipeline="integrity"))
    final = wait_for_terminal(service, run.run_id)

    assert final.status == "failed"
    report = json.loads((capture / "reports/capture_integrity_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "不一致" in report["reason"]


def test_fixed_pipeline_runs_serial_stages_and_skips_existing_ego(capture_root: Path, tmp_path: Path) -> None:
    catalog = CatalogService((capture_root,))
    service = JobService(catalog, settings_for(capture_root, tmp_path))
    executed = []
    service._run_stage = lambda run_id, key, root: executed.append(key) or []  # type: ignore[method-assign]

    run = service.create(RunCreate(capture_id="capture_test_001", root_id="root-1", pipeline="full"))
    final = wait_for_terminal(service, run.run_id)

    assert final.status == "completed"
    assert final.progress == 100
    assert [stage.status for stage in final.stages] == ["completed", "skipped", "completed", "completed", "completed"]
    assert executed == ["integrity", "retarget", "quality", "export"]


def test_local_run_can_be_cancelled(capture_root: Path, tmp_path: Path) -> None:
    catalog = CatalogService((capture_root,))
    service = JobService(catalog, settings_for(capture_root, tmp_path))

    def slow(run_id, key, root):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and run_id not in service._cancelled:
            time.sleep(0.005)
        raise RuntimeError("cancelled")

    service._run_stage = slow  # type: ignore[method-assign]
    run = service.create(RunCreate(capture_id="capture_test_001", root_id="root-1", pipeline="integrity"))
    service.cancel(run.run_id)
    final = wait_for_terminal(service, run.run_id)

    assert final.status == "cancelled"
    assert final.finished_at is not None


def test_export_uses_versioned_destination_and_manifest(capture_root: Path, tmp_path: Path) -> None:
    catalog = CatalogService((capture_root,))
    service = JobService(catalog, settings_for(capture_root, tmp_path))
    model = ProcessingRun(
        run_id="run-export-test", capture_id="capture_test_001", root_id="root-1",
        pipeline="export", executor="local", status="running", progress=0,
        created_at="2026-09-07T00:00:00Z", export_scope="ego",
    )
    destination = service._export(model, capture_root / "capture_test_001")

    manifest = json.loads((destination / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["capture_id"] == "capture_test_001"
    assert manifest["datasets"] == ["ego"]
    assert not destination.with_name(destination.name + ".partial").exists()
