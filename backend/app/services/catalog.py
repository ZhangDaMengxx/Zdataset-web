from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import (
    CaptureDetail, CaptureMetadataUpdate, CaptureSummary, CatalogStatus,
    EvidenceFile, PipelineCapability, QualityMetric, QualityState, RootInfo, ScanResult,
)

CATALOG_SCHEMA = "1.0"


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"{path.name}: {exc}"
    if not isinstance(payload, dict):
        return {}, f"{path.name}: root must be an object"
    return payload, None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _root_id(index: int) -> str:
    return f"root-{index + 1}"


def _catalog_status(native: str) -> CatalogStatus:
    return {
        "ready": CatalogStatus.COMPLETED, "complete": CatalogStatus.COMPLETED,
        "completed": CatalogStatus.COMPLETED, "building": CatalogStatus.PROCESSING,
        "processing": CatalogStatus.PROCESSING, "running": CatalogStatus.PROCESSING,
        "failed": CatalogStatus.FAILED,
    }.get(native.lower(), CatalogStatus.PENDING)


def _default_identity(capture_id: str) -> tuple[str, str]:
    match = re.match(r"capture_(\d{4})(\d{2})(\d{2})_(\d{6})_", capture_id)
    if not match:
        return capture_id[:64].lower().replace("_", "-"), "未命名 Capture"
    year, month, day, sequence = match.groups()
    return f"capture-{year}{month}{day}-{sequence}", f"未命名采集 {year}-{month}-{day} #{int(sequence)}"


def _evidence(capture_root: Path, relative: str, role: str) -> EvidenceFile:
    path = capture_root / relative
    return EvidenceFile(path=relative, exists=path.is_file() or path.is_dir(), role=role)


def _state(value: Any) -> QualityState:
    return QualityState.PASS if value is True else QualityState.FAIL if value is False else QualityState.NOT_EVALUATED


def _display_value(value: Any, unit: str = "") -> str:
    if value is None:
        return "未评估"
    if isinstance(value, bool):
        return "是" if value else "否"
    return f"{value} {unit}".strip()


def _indexed_bytes(capture_root: Path, bundle: dict[str, Any]) -> int | None:
    manifests = [capture_root / "source/checksums_original.json"]
    datasets = bundle.get("datasets") if isinstance(bundle.get("datasets"), dict) else {}
    if isinstance(datasets.get("ego"), str):
        manifests.append(capture_root / datasets["ego"] / "checksums.json")
    robots = datasets.get("robots") if isinstance(datasets.get("robots"), dict) else {}
    manifests.extend(capture_root / path / "checksums.json" for path in robots.values() if isinstance(path, str))
    total, found = 0, False
    for manifest in manifests:
        payload, error = _read_json(manifest)
        if error or not isinstance(payload.get("files"), list):
            continue
        for row in payload["files"]:
            if isinstance(row, dict) and isinstance(row.get("size"), int):
                total += row["size"]
                found = True
    return total if found else None


class CatalogService:
    def __init__(self, roots: tuple[Path, ...]):
        self._roots = tuple(root.resolve() for root in roots)

    def roots(self) -> list[RootInfo]:
        return [RootInfo(id=_root_id(index), path=str(root), available=root.is_dir()) for index, root in enumerate(self._roots)]

    def _resolve_root(self, root_id: str | None) -> list[tuple[str, Path]]:
        indexed = [(_root_id(index), root) for index, root in enumerate(self._roots)]
        if root_id is None or root_id == "all":
            return indexed
        matches = [item for item in indexed if item[0] == root_id]
        if not matches:
            raise KeyError("unknown capture root")
        return matches

    def resolve_capture_path(self, capture_id: str, root_id: str) -> Path:
        if not capture_id or "/" in capture_id or "\\" in capture_id or capture_id in {".", ".."}:
            raise KeyError("invalid capture id")
        for _, root in self._resolve_root(root_id):
            candidate = (root / capture_id).resolve()
            if candidate.parent == root and (candidate / "bundle.json").is_file():
                return candidate
        raise KeyError("capture not found")

    def _capture_dirs(self, root_id: str | None = None):
        for resolved_id, root in self._resolve_root(root_id):
            if not root.is_dir():
                continue
            try:
                children = sorted(root.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_dir() and (child / "bundle.json").is_file():
                    yield resolved_id, child

    def _identity(self, capture_root: Path) -> dict[str, Any]:
        semantic_id, display_name = _default_identity(capture_root.name)
        metadata, error = _read_json(capture_root / "metadata/catalog.json")
        if error:
            metadata = {}
        return {
            "semantic_id": metadata.get("semantic_id") or semantic_id,
            "display_name": metadata.get("display_name") or display_name,
            "task_description": metadata.get("task_description"),
            "operator": metadata.get("operator"),
        }

    def update_metadata(self, capture_id: str, root_id: str, update: CaptureMetadataUpdate) -> CaptureDetail:
        capture_root = self.resolve_capture_path(capture_id, root_id)
        duplicate = [item for item in self.list_captures() if item.semantic_id == update.semantic_id and item.capture_id != capture_id]
        if duplicate:
            raise ValueError("semantic_id already exists")
        _write_json_atomic(capture_root / "metadata/catalog.json", {
            "schema_version": CATALOG_SCHEMA, "capture_id": capture_id,
            **update.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return self._parse(root_id, capture_root)

    def _parse(self, root_id: str, capture_root: Path) -> CaptureDetail:
        bundle, bundle_error = _read_json(capture_root / "bundle.json")
        acquisition, acquisition_error = _read_json(capture_root / "source/acquisition.json")
        warnings = [error for error in (bundle_error, acquisition_error) if error]
        config = acquisition.get("config") if isinstance(acquisition.get("config"), dict) else {}
        rgb = config.get("rgb") if isinstance(config.get("rgb"), dict) else {}
        native_status = str(bundle.get("status") or "unknown")
        capture_id = str(bundle.get("capture_id") or capture_root.name)
        if capture_id != capture_root.name:
            warnings.append("bundle capture_id does not match directory name")
        datasets = bundle.get("datasets") if isinstance(bundle.get("datasets"), dict) else {}
        robots = datasets.get("robots") if isinstance(datasets.get("robots"), dict) else {}
        failure = bundle.get("failure") if isinstance(bundle.get("failure"), dict) else {}
        ego_relative = datasets.get("ego")
        ego_available = isinstance(ego_relative, str) and (capture_root / ego_relative / "meta/info.json").is_file()
        return CaptureDetail(
            capture_id=capture_id, root_id=root_id, **self._identity(capture_root),
            status=_catalog_status(native_status), native_status=native_status,
            created_at=bundle.get("created_at"), updated_at=bundle.get("updated_at"), device=config.get("camera"),
            fps=config.get("fps") if isinstance(config.get("fps"), (int, float)) else None,
            frame_count=config.get("frame_count") if isinstance(config.get("frame_count"), int) else None,
            source_format=rgb.get("format") or config.get("format"), ego_available=ego_available,
            robot_datasets=sorted(str(name) for name in robots), indexed_bytes=_indexed_bytes(capture_root, bundle),
            failure_reason=failure.get("reason"), quality=self._quality(capture_root, acquisition),
            capabilities=self._capabilities(capture_root, acquisition, ego_available, robots), path=str(capture_root),
            stages=bundle.get("stages") if isinstance(bundle.get("stages"), dict) else {}, datasets=datasets,
            manifest_warnings=warnings,
        )

    @staticmethod
    def _capabilities(capture_root: Path, acquisition: dict[str, Any], ego_available: bool, robots: dict[str, Any]) -> list[PipelineCapability]:
        source_kind = acquisition.get("kind")
        rgb_source = next(iter(sorted((capture_root / "source/rgb_original").glob("recording_000000.*"))), None)
        ego_reason = "已有 EGO，无需重复构建" if ego_available else (
            "可从 Capture 内 RGB 视频构建" if source_kind == "rgb_video" and rgb_source else
            "native_rgbd Source -> EGO 消费器尚未闭环" if source_kind == "native_rgbd" else "缺少平台支持的 Source 输入"
        )
        return [
            PipelineCapability(key="integrity", enabled=True, reason="复核 Source 清单；完整 Capture 追加 strict-v3 校验"),
            PipelineCapability(key="ego", enabled=bool(ego_available or (source_kind == "rgb_video" and rgb_source)), reason=ego_reason),
            PipelineCapability(key="retarget", enabled=ego_available, reason="EGO 已就绪" if ego_available else "需要先生成 EGO"),
            PipelineCapability(key="quality", enabled=ego_available, reason="EGO 已就绪" if ego_available else "采集侧可查看；EGO 指标需先生成 EGO"),
            PipelineCapability(key="export", enabled=ego_available or bool(robots), reason="存在可导出的派生数据" if ego_available or robots else "没有 EGO 或机器人数据集"),
        ]

    @staticmethod
    def _quality(capture_root: Path, acquisition: dict[str, Any]) -> list[QualityMetric]:
        config = acquisition.get("config") if isinstance(acquisition.get("config"), dict) else {}
        rgb = config.get("rgb") if isinstance(config.get("rgb"), dict) else {}
        depth = config.get("depth") if isinstance(config.get("depth"), dict) else {}
        persisted = config.get("persisted_cadence") if isinstance(config.get("persisted_cadence"), dict) else {}
        color_cadence = persisted.get("color") if isinstance(persisted.get("color"), dict) else {}
        depth_cadence = persisted.get("depth") if isinstance(persisted.get("depth"), dict) else {}
        profile, _ = _read_json(capture_root / "source/quality_profile.json")
        standard = profile.get("acquisition") if isinstance(profile.get("acquisition"), dict) else {}
        rgb_standard = standard.get("rgb") if isinstance(standard.get("rgb"), dict) else {}
        depth_standard = standard.get("depth") if isinstance(standard.get("depth"), dict) else {}
        metrics: list[QualityMetric] = []

        def add(key: str, label: str, passed: Any, value: Any, threshold: str, evidence: list[tuple[str, str]], **extra: Any) -> None:
            metrics.append(QualityMetric(key=key, label=label, state=_state(passed), value=_display_value(value), threshold=threshold,
                evidence=[_evidence(capture_root, path, role) for path, role in evidence], **extra))

        rw, rh = rgb.get("width", config.get("width")), rgb.get("height", config.get("height"))
        rgb_pass = None if None in (rw, rh) else int(rw) >= int(rgb_standard.get("min_width", rw)) and int(rh) >= int(rgb_standard.get("min_height", rh))
        add("source_rgb_resolution", "彩色分辨率", rgb_pass, f"{rw} x {rh}" if rw and rh else None,
            f">= {rgb_standard.get('min_width', 1280)} x {rgb_standard.get('min_height', 800)}",
            [("source/acquisition.json", "采集声明"), ("source/stream_index.parquet", "原生录制索引")])
        dw, dh = depth.get("width", config.get("depth_width")), depth.get("height", config.get("depth_height"))
        depth_required = depth_standard.get("required") is True
        depth_pass = None if not depth_required and dw is None else (None if None in (dw, dh) else int(dw) >= int(depth_standard.get("min_width", dw)) and int(dh) >= int(depth_standard.get("min_height", dh)))
        add("source_depth_resolution", "深度分辨率", depth_pass, f"{dw} x {dh}" if dw and dh else None,
            f">= {depth_standard.get('min_width', 848)} x {depth_standard.get('min_height', 480)}" if depth_required else "当前 profile 不要求 Depth",
            [("source/acquisition.json", "采集声明"), ("source/calibration", "标定"), ("source/depth/aligned_to_rgb", "对齐深度")])
        aligned_root = capture_root / "source/depth/aligned_to_rgb"
        aligned_available = aligned_root.is_dir() and any(path.is_file() for path in aligned_root.iterdir())
        add("depth_aligned_to_rgb", "深度对齐到彩色", True if aligned_available else False if depth_required else None,
            "已有对齐深度" if aligned_available else "缺少对齐深度", "必须对齐到彩色视角",
            [("source/calibration", "RGB-Depth 外参"), ("source/depth/aligned_to_rgb", "对齐深度产物")])
        actual_rgb = color_cadence.get("actual_hz", config.get("fps") if not persisted else None)
        add("source_rgb_fps", "彩色帧率", persisted.get("passed") if color_cadence else None,
            f"{actual_rgb:.2f} fps" if isinstance(actual_rgb, (int, float)) else None,
            f">= {rgb_standard.get('min_measured_fps', rgb_standard.get('min_fps', 60))} fps",
            [("source/acquisition.json", "采集统计"), ("source/stream_index.parquet", "硬件时间戳")])
        if depth_required:
            actual_depth = depth_cadence.get("actual_hz")
            add("source_depth_fps", "深度帧率", persisted.get("passed") if actual_depth is not None else None,
                f"{actual_depth:.2f} fps" if isinstance(actual_depth, (int, float)) else None,
                f">= {depth_standard.get('min_measured_fps', depth_standard.get('min_fps', 60))} fps",
                [("source/acquisition.json", "采集统计"), ("source/stream_index.parquet", "硬件时间戳")])
        add("multi_device_sync", "双机同步", None, None, "硬件触发，主从角色正确", [("source/session.json", "主从角色与触发配置")], note="缺少 session.json 时不推断双机同步")
        sync_ms = config.get("max_sync_error_ms")
        add("source_rgb_depth_sync", "同源 RGB-深度同步误差", None if sync_ms is None else sync_ms < 10,
            f"{sync_ms:.3f} ms" if isinstance(sync_ms, (int, float)) else None, "< 10 ms",
            [("source/stream_index.parquet", "成对时间戳"), ("source/acquisition.json", "最大同步残差")])
        reproj_report, _ = _read_json(capture_root / "source/calibration/calibration_report.json")
        reproj = reproj_report.get("reprojection_error_px")
        add("camera_reprojection_error_px", "内参重投影误差", None if reproj is None else float(reproj) < 0.5,
            f"{reproj} px" if reproj is not None else None, "< 0.5 px", [("source/calibration/calibration_report.json", "标定角点重投影报告")],
            ground_truth_required=True, ground_truth_available=reproj is not None)
        add("hand_depth_valid_rate", "深度有效率（手部区域）", None, None, "逐帧记录，异常批次单独审核", [("reports/retargeting", "EGO 质检报告")])
        add("detect", "手部检出率", None, None, ">= 90%", [("reports/retargeting", "EGO 验收报告")], category="canonical")
        add("three_d_scale_error_cm", "三维尺度误差", None, None, "< 1 cm", [("reports/scale_validation.json", "已知尺寸标准件测量")], category="precision", ground_truth_required=True)
        add("wrist_absolute_position", "手腕位置误差", None, None, "< 1 cm", [("reports/wrist_6dof_validation.json", "手腕 6DoF 评估")], category="precision", ground_truth_required=True)
        add("retarget", "指尖重定向误差", None, None, "< 1 cm", [("reports/retargeting", "RobotDataset 质检与仿真叠加")], category="embodiment")
        add("joint_limit", "关节限位", None, None, "无越限", [("robot_datasets", "轨迹统计")], category="embodiment")
        add("joint_jump", "关节跳变", None, None, "相邻帧步长受限", [("robot_datasets", "轨迹统计")], category="embodiment")
        integrity, _ = _read_json(capture_root / "reports/capture_integrity_report.json")
        integrity_status = integrity.get("status")
        add("integrity", "SHA-256 完整性", True if integrity_status == "passed" else False if integrity_status == "failed" else None,
            "已复核" if integrity_status == "passed" else "复核失败" if integrity_status == "failed" else "已有清单，尚未复核" if (capture_root / "source/checksums_original.json").is_file() else "缺少清单",
            "全部文件大小和 SHA-256 一致", [("source/checksums_original.json", "原始文件校验清单"), ("reports/capture_integrity_report.json", "平台复核报告")], category="integrity")

        reports = sorted((capture_root / "reports/retargeting").glob("**/*_summary.json")) if (capture_root / "reports/retargeting").is_dir() else []
        if reports:
            report = reports[-1]
            payload, error = _read_json(report)
            if not error and isinstance(payload.get("metrics"), list):
                positions = {metric.key: index for index, metric in enumerate(metrics)}
                for raw in payload["metrics"]:
                    if not isinstance(raw, dict):
                        continue
                    key = str(raw.get("key") or "unknown")
                    metric = QualityMetric(key=key, label=str(raw.get("label") or key), state=_state(raw.get("pass")),
                        value=_display_value(raw.get("value"), str(raw.get("unit") or "")), threshold=str(raw.get("threshold") or "--"),
                        category=str(raw.get("category") or "precision"), evidence=[_evidence(capture_root, report.relative_to(capture_root).as_posix(), "验收报告")],
                        note=raw.get("note"), measurement_class=raw.get("measurement_class"), measurement_basis=raw.get("measurement_basis"),
                        ground_truth_required=bool(raw.get("ground_truth_required")), ground_truth_available=bool(raw.get("ground_truth_available")))
                    if key in positions:
                        metrics[positions[key]] = metric
                    else:
                        metrics.append(metric)
        return metrics

    def list_captures(self, root_id: str | None = None, query: str = "", status: CatalogStatus | None = None) -> list[CaptureSummary]:
        needle = query.strip().lower()
        results: list[CaptureSummary] = []
        for resolved_id, capture_root in self._capture_dirs(root_id):
            detail = self._parse(resolved_id, capture_root)
            haystack = " ".join(filter(None, [detail.capture_id, detail.semantic_id, detail.display_name, detail.task_description, detail.device])).lower()
            if needle and needle not in haystack:
                continue
            if status and detail.status != status:
                continue
            results.append(CaptureSummary(**detail.model_dump()))
        return sorted(results, key=lambda item: item.created_at or "", reverse=True)

    def get_capture(self, capture_id: str, root_id: str) -> CaptureDetail:
        return self._parse(root_id, self.resolve_capture_path(capture_id, root_id))

    def scan(self) -> ScanResult:
        captures = self.list_captures()
        return ScanResult(scanned_at=datetime.now(timezone.utc).isoformat(), roots=len(self._roots), captures=len(captures))
