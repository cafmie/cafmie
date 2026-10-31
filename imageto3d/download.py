"""Download the local ONNX models used by the reconstructor."""

from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .paths import model_dir

DEPTH_URL = (
    "https://huggingface.co/onnx-community/depth-anything-v2-small"
    "/resolve/main/onnx/model.onnx"
)
DEPTH_SHA256 = "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c"
CUTOUT_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx"
CUTOUT_MD5 = "55e59e0d8062d2f5d013f4725ee84782"

USER_AGENT = "imageto3d/0.1 (local image-to-3d)"


@dataclass(frozen=True)
class ModelFile:
    key: str
    filename: str
    url: str
    sha256: str | None = None
    md5: str | None = None

    def path(self) -> Path:
        return model_dir() / self.filename


MODELS = (
    ModelFile("depth", "depth-anything-v2-small.onnx", DEPTH_URL, sha256=DEPTH_SHA256),
    ModelFile("cutout", "silueta.onnx", CUTOUT_URL, md5=CUTOUT_MD5),
)


def _digest(path: Path, kind: str) -> str:
    hasher = hashlib.sha256() if kind == "sha256" else hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_valid(model: ModelFile) -> bool:
    path = model.path()
    if not path.is_file() or path.stat().st_size < 1024:
        return False
    if model.sha256 and _digest(path, "sha256") != model.sha256:
        return False
    if model.md5 and _digest(path, "md5") != model.md5:
        return False
    return True


def models_present() -> bool:
    return all(is_valid(model) for model in MODELS)


def _download(model: ModelFile, progress=None) -> None:
    destination = model.path()
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(model.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        written = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
            written += len(chunk)
            if progress:
                progress(model, written, total)
    partial.replace(destination)
    if not is_valid(model):
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"{model.filename} の検証に失敗しました。もう一度ダウンロードしてください。")


def ensure_models(progress=None, force: bool = False) -> list[Path]:
    """Download any missing model. Returns the local paths."""

    paths: list[Path] = []
    for model in MODELS:
        if force or not is_valid(model):
            if progress:
                progress(model, 0, 0)
            _download(model, progress=progress)
        paths.append(model.path())
    return paths
