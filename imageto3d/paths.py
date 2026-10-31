"""Filesystem locations for models, the web UI, and generated files."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
WEB_DIR = PACKAGE_DIR / "web"


def running_from_checkout() -> bool:
    """True when this process is the git checkout, not an installed copy."""

    return (REPO_DIR / "pyproject.toml").is_file() and (REPO_DIR / "imageto3d.sh").is_file()


def app_data_dir() -> Path:
    override = os.environ.get("IMAGETO3D_DATA")
    if override:
        path = Path(override).expanduser()
    elif running_from_checkout():
        path = REPO_DIR
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
        path = root / "imageto3d"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_dir() -> Path:
    override = os.environ.get("IMAGETO3D_MODELS")
    path = Path(override).expanduser() if override else app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir() -> Path:
    override = os.environ.get("IMAGETO3D_OUTPUTS")
    path = Path(override).expanduser() if override else app_data_dir() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path
