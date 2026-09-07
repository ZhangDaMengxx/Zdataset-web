from pathlib import Path

import pytest

from app.models import CatalogStatus
from app.services.catalog import CatalogService


def test_catalog_reads_manifest_without_walking_media(capture_root: Path) -> None:
    catalog = CatalogService((capture_root,))
    captures = catalog.list_captures()

    assert len(captures) == 1
    item = captures[0]
    assert item.capture_id == "capture_test_001"
    assert item.status == CatalogStatus.COMPLETED
    assert item.device == "Orbbec Test"
    assert item.frame_count == 120
    assert item.indexed_bytes and item.indexed_bytes > 0
    assert item.ego_available is True
    assert item.robot_datasets == ["nero-hand-v1"]


def test_quality_distinguishes_manifest_presence_from_verification(capture_root: Path) -> None:
    detail = CatalogService((capture_root,)).get_capture("capture_test_001", "root-1")
    metrics = {metric.key: metric for metric in detail.quality}

    assert metrics["source_rgb_fps"].state == "pass"
    assert metrics["source_rgb_depth_sync"].state == "pass"
    assert metrics["integrity"].state == "not_evaluated"
    assert metrics["integrity"].value == "已有清单，尚未复核"
    assert metrics["camera_reprojection_error_px"].state == "not_evaluated"


def test_catalog_metadata_uses_semantic_id_without_changing_capture_id(capture_root: Path) -> None:
    from app.models import CaptureMetadataUpdate

    catalog = CatalogService((capture_root,))
    updated = catalog.update_metadata("capture_test_001", "root-1", CaptureMetadataUpdate(
        semantic_id="pick-red-cube-001", display_name="拿取红色方块", task_description="拿起红色方块并放入托盘", operator="operator-01",
    ))

    assert updated.capture_id == "capture_test_001"
    assert updated.semantic_id == "pick-red-cube-001"
    assert updated.display_name == "拿取红色方块"
    assert (capture_root / "capture_test_001/metadata/catalog.json").is_file()


def test_catalog_filters_and_blocks_path_traversal(capture_root: Path) -> None:
    catalog = CatalogService((capture_root,))
    assert len(catalog.list_captures(query="orbbec", status=CatalogStatus.COMPLETED)) == 1
    assert catalog.list_captures(status=CatalogStatus.FAILED) == []

    with pytest.raises(KeyError):
        catalog.get_capture("../capture_test_001", "root-1")
    with pytest.raises(KeyError):
        catalog.get_capture("capture_test_001", "root-99")


def test_broken_bundle_is_visible_with_warning(capture_root: Path) -> None:
    broken = capture_root / "capture_broken"
    broken.mkdir()
    (broken / "bundle.json").write_text("{broken", encoding="utf-8")

    detail = CatalogService((capture_root,)).get_capture("capture_broken", "root-1")
    assert detail.status == CatalogStatus.PENDING
    assert detail.manifest_warnings


def test_native_rgbd_without_ego_is_explicitly_blocked(capture_root: Path) -> None:
    capture = capture_root / "capture_test_001"
    (capture / "ego/meta/info.json").unlink()
    acquisition_path = capture / "source/acquisition.json"
    acquisition = __import__("json").loads(acquisition_path.read_text(encoding="utf-8"))
    acquisition["kind"] = "native_rgbd"
    acquisition_path.write_text(__import__("json").dumps(acquisition), encoding="utf-8")

    detail = CatalogService((capture_root,)).get_capture("capture_test_001", "root-1")
    ego = next(item for item in detail.capabilities if item.key == "ego")
    assert ego.enabled is False
    assert "尚未闭环" in ego.reason
