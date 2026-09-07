from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import Settings
from ..models import ProcessingRun, RunCreate, RunStage
from .catalog import CatalogService

STAGE_LABELS = {
    "integrity": "完整性检查", "ego": "EGO 构建", "retarget": "机器人重定向",
    "quality": "质量检查", "export": "数据导出",
}
PIPELINES = {
    "integrity": ["integrity"], "ego": ["integrity", "ego", "quality"],
    "retarget": ["integrity", "retarget", "quality"], "quality": ["quality"],
    "export": ["integrity", "export"],
    "full": ["integrity", "ego", "retarget", "quality", "export"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class JobService:
    """Serial local runner around the repository's versioned Capture tools."""

    def __init__(self, catalog: CatalogService, settings: Settings):
        self._catalog = catalog
        self._settings = settings
        self._runs: dict[str, ProcessingRun] = {}
        self._cancelled: set[str] = set()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._store = settings.state_dir / "runs.json"
        self._load()

    def _load(self) -> None:
        if not self._store.is_file():
            return
        try:
            raw = json.loads(self._store.read_text(encoding="utf-8"))
            for item in raw if isinstance(raw, list) else []:
                run = ProcessingRun.model_validate(item)
                if run.status in {"queued", "running"}:
                    run.status = "failed"
                    run.failure_reason = "平台服务在运行期间退出"
                    run.finished_at = _now()
                self._runs[run.run_id] = run
        except (OSError, json.JSONDecodeError, ValueError):
            self._runs = {}

    def _save(self) -> None:
        _atomic_json(self._store, [run.model_dump(mode="json") for run in self._runs.values()])

    def list(self) -> list[ProcessingRun]:
        with self._lock:
            values = [run.model_copy(deep=True) for run in self._runs.values()]
        return sorted(values, key=lambda run: run.created_at, reverse=True)

    def create(self, request: RunCreate) -> ProcessingRun:
        detail = self._catalog.get_capture(request.capture_id, request.root_id)
        capabilities = {item.key: item for item in detail.capabilities}
        keys = PIPELINES[request.pipeline]
        for key in keys:
            if key == "ego" and detail.ego_available:
                continue
            if key in {"retarget", "quality", "export"} and "ego" in keys:
                continue
            capability = capabilities[key]
            if not capability.enabled:
                raise ValueError(f"{STAGE_LABELS[key]}不可用：{capability.reason}")
        revision = request.retarget_revision or f"retarget_web_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        run = ProcessingRun(
            run_id=f"run-{uuid4().hex[:12]}", capture_id=request.capture_id, root_id=request.root_id,
            pipeline=request.pipeline, executor="local", status="queued", progress=0,
            stages=[RunStage(key=key, label=STAGE_LABELS[key], status="pending", progress=0) for key in keys],
            created_at=_now(), logs=["本地执行器已接收运行。"], robot_target=request.robot_target,
            target_revision=request.target_revision, retarget_revision=revision, export_scope=request.export_scope,
        )
        run.logs.append(f"固定 Pipeline={request.pipeline}; robot={request.robot_target}; revision={revision}")
        run.logs.append(f"export_scope={request.export_scope}")
        with self._lock:
            self._runs[run.run_id] = run
            self._save()
            self._queue.put(run.run_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, daemon=True, name="zdataset-runner")
                self._worker.start()
        return run.model_copy(deep=True)

    def get(self, run_id: str) -> ProcessingRun:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError("run not found")
            return run.model_copy(deep=True)

    def cancel(self, run_id: str) -> ProcessingRun:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError("run not found")
            if run.status in {"completed", "failed", "cancelled"}:
                return run.model_copy(deep=True)
            self._cancelled.add(run_id)
            run.logs.append("已请求取消，正在停止当前进程。")
            process = self._processes.get(run_id)
            if process is not None and process.poll() is None:
                process.terminate()
            self._save()
            return run.model_copy(deep=True)

    def _work(self) -> None:
        while True:
            try:
                run_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                with self._lock:
                    if self._queue.empty():
                        self._worker = None
                        return
                continue
            try:
                self._execute(run_id)
            finally:
                self._queue.task_done()

    def _execute(self, run_id: str) -> None:
        with self._lock:
            if self._finish_if_cancelled(run_id):
                return
            run = self._runs[run_id]
            run.status, run.started_at = "running", _now()
            self._save()
        capture_root = self._catalog.resolve_capture_path(run.capture_id, run.root_id)
        try:
            for index, stage in enumerate(run.stages):
                with self._lock:
                    if self._finish_if_cancelled(run_id):
                        return
                    if stage.key == "ego" and (capture_root / "ego/meta/info.json").is_file():
                        stage.status, stage.progress = "skipped", 100
                        run.logs.append("跳过 EGO 构建：已有 EGO 数据集。")
                        self._update_progress(run, index, 100)
                        self._save()
                        continue
                    stage.status, stage.progress = "running", 2
                    run.current_stage = stage.label
                    run.logs.append(f"开始：{stage.label}")
                    self._update_progress(run, index, 2)
                    self._save()
                artifact = self._run_stage(run_id, stage.key, capture_root)
                with self._lock:
                    if self._finish_if_cancelled(run_id):
                        return
                    run = self._runs[run_id]
                    stage = run.stages[index]
                    stage.status, stage.progress = "completed", 100
                    if artifact:
                        run.artifacts.extend(artifact)
                    run.logs.append(f"完成：{stage.label}")
                    self._update_progress(run, index, 100)
                    self._save()
            with self._lock:
                run = self._runs[run_id]
                run.status, run.progress, run.current_stage, run.finished_at = "completed", 100, None, _now()
                run.logs.append("本地处理运行完成。")
                self._save()
        except Exception as exc:
            with self._lock:
                run = self._runs[run_id]
                if run_id in self._cancelled:
                    self._finish_if_cancelled(run_id)
                    return
                run.status, run.failure_reason, run.current_stage, run.finished_at = "failed", str(exc), None, _now()
                for stage in run.stages:
                    if stage.status == "running":
                        stage.status = "failed"
                run.logs.append(f"失败：{exc}")
                self._save()
        finally:
            with self._lock:
                self._processes.pop(run_id, None)

    def _update_progress(self, run: ProcessingRun, index: int, stage_progress: int) -> None:
        run.stages[index].progress = stage_progress
        run.progress = round(((index + stage_progress / 100) / len(run.stages)) * 100)

    def _run_stage(self, run_id: str, key: str, capture_root: Path) -> list[str]:
        run = self._runs[run_id]
        if key == "integrity":
            return self._integrity(run_id, capture_root)
        if key == "ego":
            source = next(iter(sorted((capture_root / "source/rgb_original").glob("recording_000000.*"))), None)
            if source is None:
                raise RuntimeError("Capture 内没有可用的 RGB 原视频")
            self._command(run_id, [str(self._settings.lerobot_python), "src/lerobot_v3/build_canonical.py", "--video", str(source), "--capture-root", str(capture_root)])
            return [str(capture_root / "ego")]
        if key == "retarget":
            self._command(run_id, [str(self._settings.lerobot_python), "src/lerobot_v3/derive_embodiment.py", "--emit-traj", "--robot", run.robot_target or "nero_inspire_rgbd", "--capture-root", str(capture_root), "--target-revision", run.target_revision or "target_revision_v001", "--retarget-revision", run.retarget_revision or "retarget_v001"])
            return [str(capture_root / "robot_datasets" / (run.robot_target or "nero_inspire_rgbd") / (run.target_revision or "target_revision_v001") / (run.retarget_revision or "retarget_v001"))]
        if key == "quality":
            report = capture_root / "reports/retargeting" / (run.robot_target or "nero_inspire_rgbd") / (run.target_revision or "target_revision_v001") / f"{run.retarget_revision or 'retarget_v001'}_summary.json"
            self._command(run_id, [str(self._settings.lerobot_python), "src/lerobot_v3/measure_acceptance.py", "--robot", run.robot_target or "nero_inspire_rgbd", "--capture-root", str(capture_root), "--target-revision", run.target_revision or "target_revision_v001", "--retarget-revision", run.retarget_revision or "retarget_v001", "--json", str(report)])
            return [str(report)]
        if key == "export":
            self._command(run_id, [str(self._settings.lerobot_python), "src/lerobot_v3/verify_dataset.py", "--capture-bundle", "--capture-root", str(capture_root)])
            return [str(self._export(run, capture_root))]
        raise RuntimeError(f"unknown stage: {key}")

    def _command(self, run_id: str, command: list[str]) -> None:
        if not self._settings.lerobot_repo.is_dir() or not self._settings.lerobot_python.is_file():
            raise RuntimeError("LeRobot 仓库或 Python 3.12 运行时不可用")
        with self._lock:
            run = self._runs[run_id]
            run.logs.append("$ " + " ".join(command))
            self._save()
        environment = {**os.environ, "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
        process = subprocess.Popen(command, cwd=self._settings.lerobot_repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=environment)
        with self._lock:
            self._processes[run_id] = process
        assert process.stdout is not None
        for line in process.stdout:
            with self._lock:
                self._runs[run_id].logs.append(line.rstrip())
                self._runs[run_id].logs = self._runs[run_id].logs[-400:]
        return_code = process.wait()
        with self._lock:
            self._processes.pop(run_id, None)
        if return_code != 0:
            raise RuntimeError(f"处理命令退出码 {return_code}")

    def _integrity(self, run_id: str, capture_root: Path) -> list[str]:
        report_path = capture_root / "reports/capture_integrity_report.json"
        checked = 0
        try:
            bundle = json.loads((capture_root / "bundle.json").read_text(encoding="utf-8"))
            if bundle.get("capture_id") != capture_root.name:
                raise ValueError("bundle.json capture_id 与目录名不一致")
            for required in ("source/acquisition.json", "source/quality_profile.json", "source/checksums_original.json"):
                if not (capture_root / required).is_file():
                    raise ValueError(f"缺少必需文件：{required}")
            manifest = json.loads((capture_root / "source/checksums_original.json").read_text(encoding="utf-8"))
            if manifest.get("algorithm") != "sha256" or not isinstance(manifest.get("files"), list):
                raise ValueError("无效的 Source checksum 清单")
            source_root = (capture_root / "source").resolve()
            for item in manifest["files"]:
                if run_id in self._cancelled:
                    raise RuntimeError("运行已取消")
                relative = Path(item.get("path", ""))
                path = (source_root / relative).resolve()
                if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(source_root) or not path.is_file():
                    raise ValueError(f"不安全或缺失的 Source 文件：{relative}")
                if path.stat().st_size != item.get("size"):
                    raise ValueError(f"文件大小不一致：{relative}")
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != item.get("sha256"):
                    raise ValueError(f"SHA-256 不一致：{relative}")
                checked += 1
                with self._lock:
                    self._runs[run_id].logs.append(f"SHA-256 OK：{relative}")
            listed = {Path(item["path"]).as_posix() for item in manifest["files"] if isinstance(item, dict) and isinstance(item.get("path"), str)}
            actual = {path.relative_to(source_root).as_posix() for path in source_root.rglob("*") if path.is_file() and path.name != "checksums_original.json"}
            omitted = sorted(actual - listed)
            if omitted:
                raise ValueError(f"checksum 清单遗漏文件：{', '.join(omitted)}")
            strict_checked = False
            if bundle.get("status") == "ready" and (capture_root / "ego/meta/info.json").is_file():
                self._command(run_id, [str(self._settings.lerobot_python), "src/lerobot_v3/verify_dataset.py", "--capture-bundle", "--capture-root", str(capture_root)])
                strict_checked = True
            _atomic_json(report_path, {"schema_version": "1.0", "capture_id": capture_root.name, "status": "passed", "checked_at": _now(), "source_checksummed_files": checked, "strict_capture_bundle": strict_checked})
        except Exception as exc:
            _atomic_json(report_path, {"schema_version": "1.0", "capture_id": capture_root.name, "status": "failed", "checked_at": _now(), "source_checksummed_files": checked, "reason": str(exc)})
            raise
        return [str(report_path)]

    def _export(self, run: ProcessingRun, capture_root: Path) -> Path:
        identity = self._catalog.get_capture(run.capture_id, run.root_id)
        destination = self._settings.export_root / identity.semantic_id / run.run_id
        partial = destination.with_name(destination.name + ".partial")
        if partial.exists() or destination.exists():
            raise RuntimeError("导出目标已存在")
        partial.mkdir(parents=True)

        def link_or_copy(source: str, target: str) -> str:
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
            return target

        selected: list[tuple[Path, str]] = []
        if run.export_scope in {"ego", "all"} and (capture_root / "ego/meta/info.json").is_file():
            selected.append((capture_root / "ego", "ego"))
        robot_root = capture_root / "robot_datasets" / (run.robot_target or "") / (run.target_revision or "") / (run.retarget_revision or "")
        if run.export_scope in {"robot", "all"} and robot_root.is_dir():
            selected.append((robot_root, f"robot_datasets/{run.robot_target}/{run.target_revision}/{run.retarget_revision}"))
        if not selected:
            raise RuntimeError("没有符合本次运行版本的可导出数据集")
        for source, relative in selected:
            shutil.copytree(source, partial / relative, copy_function=link_or_copy)
        if (capture_root / "reports").is_dir():
            shutil.copytree(capture_root / "reports", partial / "reports", copy_function=link_or_copy)
        _atomic_json(partial / "export_manifest.json", {
            "schema_version": "1.0", "export_id": run.run_id, "created_at": _now(),
            "capture_id": run.capture_id, "semantic_id": identity.semantic_id,
            "robot_target": run.robot_target, "target_revision": run.target_revision,
            "retarget_revision": run.retarget_revision,
            "datasets": [relative for _, relative in selected], "copy_policy": "hardlink_same_filesystem_copy_fallback",
        })
        partial.replace(destination)
        return destination

    def _finish_if_cancelled(self, run_id: str) -> bool:
        if run_id not in self._cancelled:
            return False
        run = self._runs[run_id]
        run.status, run.finished_at, run.current_stage = "cancelled", _now(), None
        for stage in run.stages:
            if stage.status in {"pending", "running"}:
                stage.status = "cancelled"
        run.logs.append("本地运行已取消。")
        self._cancelled.discard(run_id)
        self._save()
        return True
