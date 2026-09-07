from pathlib import Path

from app.config import Settings


def test_primary_server_environment(monkeypatch, tmp_path: Path) -> None:
    capture_a = tmp_path / "captures-a"
    capture_b = tmp_path / "captures-b"
    repo = tmp_path / "VLA-HandArm"
    python = tmp_path / "lerobot-python"
    for path in (capture_a, capture_b, repo):
        path.mkdir()
    python.touch()
    monkeypatch.setenv("ZDATASET_CAPTURE_ROOTS", f"{capture_a}:{capture_b}")
    monkeypatch.setenv("ZDATASET_LEROBOT_REPO", str(repo))
    monkeypatch.setenv("ZDATASET_LEROBOT_PYTHON", str(python))
    monkeypatch.setenv("ZDATASET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ZDATASET_EXPORT_ROOT", str(tmp_path / "exports"))

    settings = Settings.from_env()

    assert settings.capture_roots == (capture_a.resolve(), capture_b.resolve())
    assert settings.lerobot_repo == repo.resolve()
    assert settings.lerobot_python == python.resolve()
    assert settings.state_dir == (tmp_path / "state").resolve()
    assert settings.export_root == (tmp_path / "exports").resolve()


def test_legacy_environment_remains_compatible(monkeypatch, tmp_path: Path) -> None:
    capture = tmp_path / "captures"
    capture.mkdir()
    monkeypatch.setenv("NERO_CAPTURE_ROOTS", str(capture))
    monkeypatch.delenv("ZDATASET_CAPTURE_ROOTS", raising=False)

    assert Settings.from_env().capture_roots == (capture.resolve(),)
