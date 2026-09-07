from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .models import (
    CaptureMetadataUpdate, CatalogStatus, ProcessingRun, RootInfo, RunCreate, ScanResult,
)
from .services.catalog import CatalogService
from .services.jobs import JobService


def create_app(settings: Settings | None = None, job_service: JobService | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    app = FastAPI(title="ZDataset Web", version="0.1.0")
    app.state.catalog = CatalogService(resolved.capture_roots)
    app.state.jobs = job_service or JobService(app.state.catalog, resolved)

    @app.get("/api/v1/health")
    def health(request: Request) -> dict[str, object]:
        return {
            "status": "ok",
            "mode": "local",
            "executor": "local",
            "capture_roots": len(request.app.state.catalog.roots()),
            "lerobot_runtime": resolved.lerobot_python.is_file(),
        }

    @app.get("/api/v1/roots", response_model=list[RootInfo])
    def roots(request: Request) -> list[RootInfo]:
        return request.app.state.catalog.roots()

    @app.get("/api/v1/captures")
    def captures(
        request: Request,
        root_id: str | None = None,
        query: str = "",
        status: CatalogStatus | None = Query(default=None),
    ):
        try:
            return request.app.state.catalog.list_captures(root_id, query, status)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/captures/{capture_id}")
    def capture_detail(capture_id: str, request: Request, root_id: str = Query(...)):
        try:
            return request.app.state.catalog.get_capture(capture_id, root_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/v1/captures/{capture_id}/metadata")
    def update_capture_metadata(
        capture_id: str, payload: CaptureMetadataUpdate, request: Request, root_id: str = Query(...)
    ):
        try:
            return request.app.state.catalog.update_metadata(capture_id, root_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/catalog/scan", response_model=ScanResult)
    def scan(request: Request) -> ScanResult:
        return request.app.state.catalog.scan()

    @app.get("/api/v1/runs", response_model=list[ProcessingRun])
    def runs(request: Request) -> list[ProcessingRun]:
        return request.app.state.jobs.list()

    @app.get("/api/v1/runs/{run_id}", response_model=ProcessingRun)
    def run_detail(run_id: str, request: Request) -> ProcessingRun:
        try:
            return request.app.state.jobs.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.post("/api/v1/runs", response_model=ProcessingRun, status_code=201)
    def create_run(payload: RunCreate, request: Request) -> ProcessingRun:
        try:
            request.app.state.catalog.get_capture(payload.capture_id, payload.root_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="capture not found") from exc
        try:
            return request.app.state.jobs.create(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/cancel", response_model=ProcessingRun)
    def cancel_run(run_id: str, request: Request) -> ProcessingRun:
        try:
            return request.app.state.jobs.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    app.mount("/assets", StaticFiles(directory=frontend), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(frontend / "index.html")

    return app


app = create_app()
