from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEROBOT_REPO = PROJECT_ROOT.parent / "lerobotTest"


def _env(primary: str, legacy: str, default: str) -> str:
    return os.getenv(primary) or os.getenv(legacy) or default


@dataclass(frozen=True)
class Settings:
    capture_roots: tuple[Path, ...]
    lerobot_repo: Path = DEFAULT_LEROBOT_REPO
    lerobot_python: Path = DEFAULT_LEROBOT_REPO / ".venv/bin/python"
    state_dir: Path = PROJECT_ROOT / "data/state"
    export_root: Path = PROJECT_ROOT / "data/exports"

    @classmethod
    def from_env(cls) -> "Settings":
        project_root = Path(__file__).resolve().parents[2]
        lerobot_repo = Path(
            _env("ZDATASET_LEROBOT_REPO", "NERO_LEROBOT_REPO", str(project_root.parent / "lerobotTest"))
        ).expanduser().resolve()
        raw = _env("ZDATASET_CAPTURE_ROOTS", "NERO_CAPTURE_ROOTS", "")
        candidates = [Path(item).expanduser() for item in raw.split(os.pathsep) if item]
        if not candidates:
            candidates = [lerobot_repo / "datasets/captures"]
        roots = tuple(path.resolve() for path in candidates if path.is_dir())
        return cls(
            capture_roots=roots,
            lerobot_repo=lerobot_repo,
            lerobot_python=Path(_env("ZDATASET_LEROBOT_PYTHON", "NERO_LEROBOT_PYTHON", str(lerobot_repo / ".venv/bin/python"))).expanduser().resolve(),
            state_dir=Path(_env("ZDATASET_STATE_DIR", "NERO_STATE_DIR", str(project_root / "data/state"))).expanduser().resolve(),
            export_root=Path(_env("ZDATASET_EXPORT_ROOT", "NERO_EXPORT_ROOT", str(project_root / "data/exports"))).expanduser().resolve(),
        )
