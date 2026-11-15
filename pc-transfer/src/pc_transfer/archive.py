"""ZIP archive helpers for game folder payloads."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Callable, Optional


ProgressCb = Optional[Callable[[float, str], None]]


def zip_folder(source: Path, dest_zip: Path, progress: ProgressCb = None) -> Path:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Game folder not found: {source}")

    files: list[Path] = []
    for root, _dirs, names in __import__("os").walk(source):
        for name in names:
            files.append(Path(root) / name)

    total = max(len(files), 1)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, file_path in enumerate(files):
            arcname = file_path.relative_to(source).as_posix()
            zf.write(file_path, arcname)
            if progress:
                progress((idx + 1) / total * 100.0, f"Packing {arcname}")
    if progress:
        progress(100.0, f"Created {dest_zip.name}")
    return dest_zip


def unzip_to(zip_path: Path, dest_dir: Path, progress: ProgressCb = None) -> Path:
    zip_path = zip_path.expanduser().resolve()
    dest_dir = dest_dir.expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total = max(len(members), 1)
        for idx, info in enumerate(members):
            # Prevent zip-slip
            target = (dest_dir / info.filename).resolve()
            if not str(target).startswith(str(dest_dir)):
                raise ValueError(f"Unsafe zip entry: {info.filename}")
            zf.extract(info, dest_dir)
            if progress:
                progress((idx + 1) / total * 100.0, f"Extracting {info.filename}")
    if progress:
        progress(100.0, f"Extracted to {dest_dir}")
    return dest_dir
