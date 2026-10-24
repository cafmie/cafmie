"""Filesystem locations for models, the web UI, and generated files."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
WEB_DIR = PACKAGE_DIR / "web"


def model_dir() -> Path:
    override = os.environ.get("IMAGETO3D_MODELS")
    if override:
        path = Path(override).expanduser()
    else:
        path = REPO_DIR / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir() -> Path:
    override = os.environ.get("IMAGETO3D_OUTPUTS")
    if override:
        path = Path(override).expanduser()
    else:
        path = REPO_DIR / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path
