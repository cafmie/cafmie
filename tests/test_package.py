import os
import subprocess
import sys
from pathlib import Path

import pytest

from imageto3d.launch import desktop_file_text
from imageto3d.packaging import BIN_PATH, ICON_PATH, stage_debian


def test_debian_stage_contains_the_app_and_offline_wheels(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "imageto3d-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (wheels / "numpy-2.0.0-py3-none-manylinux.whl").write_bytes(b"numpy")
    stage = tmp_path / "stage"

    stage_debian(stage, wheels, version="0.1.0", arch="amd64", python_version="3.12")

    control = (stage / "DEBIAN" / "control").read_text(encoding="utf-8")
    assert "Package: imageto3d" in control
    assert "Version: 0.1.0-1" in control
    assert "Architecture: amd64" in control
    assert "python3 (>= 3.12)" in control
    assert (stage / "usr" / "share" / "imageto3d" / "python-version").read_text(encoding="utf-8") == "3.12\n"
    assert (stage / "usr" / "share" / "imageto3d" / "wheels" / "imageto3d-0.1.0-py3-none-any.whl").is_file()
    assert (stage / "usr" / "share" / "imageto3d" / "wheels" / "numpy-2.0.0-py3-none-manylinux.whl").is_file()
    desktop = (stage / "usr" / "share" / "applications" / "imageto3d.desktop").read_text(encoding="utf-8")
    assert desktop == desktop_file_text(BIN_PATH, ICON_PATH)
    launcher = stage / "usr" / "bin" / "imageto3d"
    assert launcher.stat().st_mode & 0o111
    assert "/opt/imageto3d/venv/bin/imageto3d" in launcher.read_text(encoding="utf-8")
    assert (stage / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "imageto3d.svg").is_file()


def test_debian_archive_lists_the_launcher(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "imageto3d-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    from imageto3d.packaging import build_debian

    deb = build_debian(tmp_path, wheels, version="0.1.0", arch="amd64", python_version="3.12")
    listing = subprocess.check_output(["dpkg-deb", "-c", str(deb)], text=True)
    assert "./usr/bin/imageto3d" in listing
    assert "imageto3d-0.1.0-py3-none-any.whl" in listing
    info = subprocess.check_output(["dpkg-deb", "-I", str(deb)], text=True)
    assert "imageto3d" in info
    assert "amd64" in info


def test_wheel_contains_the_web_ui(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONSAFEPATH"] = "1"
    probe = subprocess.run(
        [sys.executable, "-m", "build", "--version"],
        capture_output=True,
        text=True,
        env=env,
    )
    if probe.returncode != 0:
        pytest.skip("build が入っていないため wheel の中身は確認しません")
    subprocess.check_call(
        [sys.executable, "-m", "build", str(root), "--wheel", "--outdir", str(tmp_path)],
        env=env,
    )
    wheels = list(tmp_path.glob("imageto3d-*.whl"))
    assert len(wheels) == 1
    import zipfile

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    assert "imageto3d/web/index.html" in names
    assert "imageto3d/web/app.js" in names
    assert "imageto3d/web/favicon.svg" in names
    assert "imageto3d/web/vendor/model-viewer.min.js" in names
