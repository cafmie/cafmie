"""Build a pip wheel, a source archive, and an offline Debian package."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .launch import desktop_file_text
from .paths import REPO_DIR, WEB_DIR

DEB_REVISION = "1"
BIN_PATH = Path("/usr/bin/imageto3d")
ICON_PATH = Path("/usr/share/icons/hicolor/scalable/apps/imageto3d.svg")
WHEELS_PATH = Path("/usr/share/imageto3d/wheels")
VENV_PATH = Path("/opt/imageto3d/venv")


def debian_arch() -> str:
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())


def python_series() -> str:
    return f"{sys.version_info[0]}.{sys.version_info[1]}"


def stage_debian(
    stage: Path,
    wheels: Path,
    *,
    version: str,
    arch: str,
    python_version: str,
) -> None:
    """Lay out a binary Debian package tree. `wheels` must contain imageto3d and its dependencies."""

    if stage.exists():
        shutil.rmtree(stage)
    debian = stage / "DEBIAN"
    debian.mkdir(parents=True)
    wheel_dest = stage / "usr" / "share" / "imageto3d" / "wheels"
    wheel_dest.mkdir(parents=True)
    copied = 0
    for wheel in sorted(wheels.glob("*.whl")):
        shutil.copy2(wheel, wheel_dest / wheel.name)
        copied += 1
    if copied == 0 or not any(wheel_dest.glob("imageto3d-*.whl")):
        raise RuntimeError("Debian パッケージに入れる imageto3d の wheel がありません。")

    share = stage / "usr" / "share" / "imageto3d"
    (share / "python-version").write_text(python_version + "\n", encoding="utf-8")
    icon_dest = stage / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "imageto3d.svg"
    icon_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WEB_DIR / "favicon.svg", icon_dest)
    applications = stage / "usr" / "share" / "applications"
    applications.mkdir(parents=True)
    (applications / "imageto3d.desktop").write_text(
        desktop_file_text(BIN_PATH, ICON_PATH),
        encoding="utf-8",
    )
    binary = stage / "usr" / "bin" / "imageto3d"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/bin/sh\nset -eu\nexec /opt/imageto3d/venv/bin/imageto3d \"$@\"\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)

    (debian / "control").write_text(_control(version, arch), encoding="utf-8")
    (debian / "postinst").write_text(_postinst(), encoding="utf-8")
    (debian / "prerm").write_text(_prerm(), encoding="utf-8")
    (debian / "postrm").write_text(_postrm(), encoding="utf-8")
    for name in ("postinst", "prerm", "postrm"):
        (debian / name).chmod(0o755)


def build_debian(dest: Path, wheels: Path, *, version: str, arch: str, python_version: str) -> Path:
    tool = shutil.which("dpkg-deb")
    if tool is None:
        raise RuntimeError("dpkg-deb が見つかりません。Debian パッケージを作れません。")
    deb = dest / f"imageto3d_{version}-{DEB_REVISION}_{arch}.deb"
    stage = dest / ".deb-root"
    try:
        stage_debian(stage, wheels, version=version, arch=arch, python_version=python_version)
        _run([tool, "--root-owner-group", "--build", str(stage), str(deb)])
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return deb


def build_distribution(output: Path | None = None) -> list[Path]:
    """Create dist/imageto3d-*.whl, the sdist, and an offline .deb for this CPU and Python."""

    dest = (output or (REPO_DIR / "dist")).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in ("imageto3d-*.whl", "imageto3d-*.tar.gz", "imageto3d_*.deb"):
        for path in dest.glob(pattern):
            path.unlink()

    _require_build()
    print("Python パッケージを作っています", flush=True)
    _run([sys.executable, "-m", "build", str(REPO_DIR), "--outdir", str(dest)])
    shutil.rmtree(REPO_DIR / "build", ignore_errors=True)
    app_wheels = sorted(dest.glob("imageto3d-*.whl"))
    archives = sorted(dest.glob("imageto3d-*.tar.gz"))
    if len(app_wheels) != 1 or len(archives) != 1:
        raise RuntimeError("wheel とソースアーカイブを一つずつ作れませんでした。")

    wheelhouse = dest / "wheels"
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir()
    try:
        print("依存ライブラリを集めています", flush=True)
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "-r",
                str(REPO_DIR / "requirements.txt"),
                "-d",
                str(wheelhouse),
                "--only-binary=:all:",
            ]
        )
        shutil.copy2(app_wheels[0], wheelhouse / app_wheels[0].name)
        print("Debian パッケージを作っています", flush=True)
        deb = build_debian(
            dest,
            wheelhouse,
            version=__version__,
            arch=debian_arch(),
            python_version=python_series(),
        )
    finally:
        if wheelhouse.exists():
            shutil.rmtree(wheelhouse)
    return [archives[0], app_wheels[0], deb]


def _control(version: str, arch: str) -> str:
    return "\n".join(
        [
            "Package: imageto3d",
            f"Version: {version}-{DEB_REVISION}",
            "Section: graphics",
            "Priority: optional",
            f"Architecture: {arch}",
            "Depends: python3 (>= 3.12), python3 (<< 3.13), python3-venv, python3-pip",
            "Maintainer: cafmie <cafmie@users.noreply.github.com>",
            "Description: 写真をこのPCの中で立体モデルにします",
            " 画像を外部のAPIに送らず、GLB、STL、OBJ を書き出します。",
            " 同梱の実行環境は CPU です。",
            "",
        ]
    )


def _postinst() -> str:
    return f"""#!/bin/sh
set -eu
need=$(cat /usr/share/imageto3d/python-version)
have=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ "$need" != "$have" ]; then
    echo "このパッケージは Python $need 用です。今の python3 は $have です。" >&2
    exit 1
fi
python3 -m venv {VENV_PATH}
set -- {WHEELS_PATH}/imageto3d-*.whl
if [ ! -f "$1" ]; then
    echo "imageto3d の wheel が見つかりません。" >&2
    exit 1
fi
PIP_DISABLE_PIP_VERSION_CHECK=1 {VENV_PATH}/bin/pip install --no-index --find-links={WHEELS_PATH} "$1"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
"""


def _prerm() -> str:
    return """#!/bin/sh
set -eu
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    rm -rf /opt/imageto3d
fi
"""


def _postrm() -> str:
    return """#!/bin/sh
set -eu
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
"""


def _require_build() -> None:
    env = os.environ.copy()
    env["PYTHONSAFEPATH"] = "1"
    probe = subprocess.run(
        [sys.executable, "-m", "build", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    combined = f"{probe.stderr}\n{probe.stdout}"
    if probe.returncode != 0 and "No module named build" in combined:
        raise RuntimeError("パッケージの作成には build が必要です。pip install build を実行してください。")


def _run(command: list[str], cwd: Path | None = None) -> None:
    env = os.environ.copy()
    # A local directory named build/ would otherwise shadow the build frontend.
    env["PYTHONSAFEPATH"] = "1"
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    tail = detail[-2000:]
    raise RuntimeError(f"{command[0]} が失敗しました。\n{tail}")
