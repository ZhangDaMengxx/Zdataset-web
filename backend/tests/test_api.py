from pathlib import Path

from types import SimpleNamespace

from fastapi import HTTPException

from app.config import Settings
from app.main import create_app
from app.models import CaptureMetadataUpdate, RunCreate


def test_catalog_and_run_api(capture_root: Path, tmp_path: Path) -> None:
    settings = Settings(capture_roots=(capture_root,), lerobot_repo=tmp_path, lerobot_python=Path(__file__), state_dir=tmp_path / "state", export_root=tmp_path / "exports")
    app = create_app(settings)
    app.state.jobs._run_stage = lambda run_id, key, root: []
    request = SimpleNamespace(app=app)
    health = next(route.endpoint for route in app.routes if route.path == "/api/v1/health")
    roots = next(route.endpoint for route in app.routes if route.path == "/api/v1/roots")
    captures = next(route.endpoint for route in app.routes if route.path == "/api/v1/captures")
    detail = next(route.endpoint for route in app.routes if route.path == "/api/v1/captures/{capture_id}")
    create_run = [route.endpoint for route in app.routes if route.path == "/api/v1/runs"][1]
    list_runs = [route.endpoint for route in app.routes if route.path == "/api/v1/runs"][0]

    assert health(request)["mode"] == "local"
    assert roots(request)[0].id == "root-1"
    listing = captures(request, root_id="root-1", query="", status=None)
    assert listing[0].capture_id == "capture_test_001"
    assert next(metric for metric in listing[0].quality if metric.key == "integrity").state == "not_evaluated"
    assert detail("capture_test_001", request, "root-1").path.endswith("capture_test_001")
    created = create_run(RunCreate(capture_id="capture_test_001", root_id="root-1", pipeline="integrity"), request)
    assert created.executor == "local"
    assert list_runs(request)

    metadata = next(route.endpoint for route in app.routes if route.path == "/api/v1/captures/{capture_id}/metadata")
    renamed = metadata("capture_test_001", CaptureMetadataUpdate(semantic_id="place-cup-001", display_name="放置水杯"), request, "root-1")
    assert renamed.semantic_id == "place-cup-001"


def test_api_rejects_unknown_capture_and_arbitrary_pipeline(capture_root: Path, tmp_path: Path) -> None:
    app = create_app(Settings(capture_roots=(capture_root,), state_dir=tmp_path / "state", export_root=tmp_path / "exports"))
    request = SimpleNamespace(app=app)
    create_run = [route.endpoint for route in app.routes if route.path == "/api/v1/runs"][1]
    try:
        create_run(RunCreate(capture_id="missing", root_id="root-1", pipeline="full"), request)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("missing Capture must be rejected")

    from pydantic import ValidationError
    try:
        RunCreate(capture_id="capture_test_001", root_id="root-1", pipeline="rm -rf")
    except ValidationError:
        pass
    else:
        raise AssertionError("arbitrary pipeline must be rejected")
