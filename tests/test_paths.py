from pathlib import Path

from imageto3d.paths import REPO_DIR, model_dir, output_dir


def test_checkout_keeps_models_next_to_the_repository():
    assert model_dir() == REPO_DIR / "models"


def test_installed_copy_uses_the_home_data_dir(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr("imageto3d.paths.REPO_DIR", tmp_path / "site-packages")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("IMAGETO3D_MODELS", raising=False)
    monkeypatch.delenv("IMAGETO3D_DATA", raising=False)
    monkeypatch.delenv("IMAGETO3D_OUTPUTS", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert model_dir() == home / ".local" / "share" / "imageto3d" / "models"
    assert output_dir() == home / ".local" / "share" / "imageto3d" / "outputs"


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGETO3D_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("IMAGETO3D_OUTPUTS", str(tmp_path / "outputs"))
    assert model_dir() == tmp_path / "models"
    assert output_dir() == tmp_path / "outputs"
