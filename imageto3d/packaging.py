"""Build a pip wheel, a source archive, and an offline Debian package."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import __version__
from .launch import desktop_file_text
from .paths import REPO_DIR, WEB_DIR

DEB_REVISION = "1"
WINDOWS_PYTHON = "3.12.10"
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
    """Create the wheel, the source archive, the Debian package, and the Windows zip."""

    dest = (output or (REPO_DIR / "dist")).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in ("imageto3d-*.whl", "imageto3d-*.tar.gz", "imageto3d_*.deb", "imageto3d-*-windows-amd64.zip"):
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
    windows = build_windows(dest, app_wheels[0])
    return [archives[0], app_wheels[0], deb, windows]


def stage_windows(stage: Path, embed_zip: Path, site_packages: Path) -> None:
    """Lay out a folder a Windows user can unzip and start by double-click."""

    if stage.exists():
        shutil.rmtree(stage)
    python_dir = stage / "python"
    python_dir.mkdir(parents=True)
    with zipfile.ZipFile(embed_zip) as archive:
        archive.extractall(python_dir)
    pth_files = list(python_dir.glob("python*._pth"))
    if len(pth_files) != 1:
        raise RuntimeError("Windows 向け Python の構成ファイルが見つかりません。")
    pth = pth_files[0]
    zip_name = "python312.zip"
    for line in pth.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.endswith(".zip"):
            zip_name = stripped
            break
    pth.write_text(f"{zip_name}\n.\nLib\\site-packages\nimport site\n", encoding="ascii")
    destination = python_dir / "Lib" / "site-packages"
    shutil.copytree(site_packages, destination)
    launcher = _windows_launcher()
    (stage / "画像から3D.bat").write_bytes(launcher)
    (stage / "imageto3d.bat").write_bytes(launcher)
    (stage / "install.ps1").write_text(_windows_shortcut_script(), encoding="utf-8-sig")
    (stage / "はじめにお読みください.txt").write_text(_windows_readme(), encoding="utf-8-sig")


def archive_windows(stage: Path, dest_zip: Path) -> Path:
    if dest_zip.exists():
        dest_zip.unlink()
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo((Path(stage.name) / path.relative_to(stage)).as_posix())
            info.flag_bits |= 0x800
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return dest_zip


def build_windows(dest: Path, app_wheel: Path) -> Path:
    """Zip embeddable CPython and the Windows wheels so the folder runs offline."""

    print("Windows 向けのパッケージを作っています", flush=True)
    work = dest / ".windows"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        embed = work / f"python-{WINDOWS_PYTHON}-embed-amd64.zip"
        _download(
            f"https://www.python.org/ftp/python/{WINDOWS_PYTHON}/python-{WINDOWS_PYTHON}-embed-amd64.zip",
            embed,
        )
        wheels = work / "wheels"
        wheels.mkdir()
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "-r",
                str(REPO_DIR / "requirements.txt"),
                "-d",
                str(wheels),
                "--only-binary=:all:",
                "--platform",
                "win_amd64",
                "--python-version",
                "3.12",
                "--implementation",
                "cp",
                "--abi",
                "cp312",
            ]
        )
        shutil.copy2(app_wheel, wheels / app_wheel.name)
        site = work / "site-packages"
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheels),
                "--only-binary=:all:",
                "--platform",
                "win_amd64",
                "--python-version",
                "3.12",
                "--implementation",
                "cp",
                "--abi",
                "cp312",
                "--target",
                str(site),
                "imageto3d",
            ]
        )
        folder = work / f"imageto3d-{__version__}-windows-amd64"
        stage_windows(folder, embed, site)
        return archive_windows(folder, dest / f"imageto3d-{__version__}-windows-amd64.zip")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _windows_launcher() -> bytes:
    return (
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0install.ps1\"\r\n"
        "\"%~dp0python\\python.exe\" -m imageto3d\r\n"
        "if errorlevel 1 pause\r\n"
    ).encode("ascii")


def _windows_shortcut_script() -> str:
    return "\n".join(
        [
            "$root = Split-Path -Parent $MyInvocation.MyCommand.Path",
            "$menu = Join-Path $env:APPDATA \"Microsoft\\Windows\\Start Menu\\Programs\"",
            "New-Item -ItemType Directory -Force -Path $menu | Out-Null",
            "$shortcut = Join-Path $menu \"画像から3D.lnk\"",
            "$shell = New-Object -ComObject WScript.Shell",
            "$link = $shell.CreateShortcut($shortcut)",
            "$link.TargetPath = Join-Path $root \"python\\pythonw.exe\"",
            "$link.Arguments = \"-m imageto3d\"",
            "$link.WorkingDirectory = $root",
            "$link.Description = \"写真をこのPCの中で立体モデルにします\"",
            "$link.Save()",
            "",
        ]
    )


def _windows_readme() -> str:
    return (
        "画像から3D（Windows 64bit）\n"
        "\n"
        "1. このフォルダを好きな場所へ展開します。\n"
        "2. 「画像から3D.bat」をダブルクリックします。\n"
        "3. アプリのウィンドウが開きます。初回だけ、モデルを約140MB取得します。\n"
        "\n"
        "スタートメニューにも「画像から3D」が追加されます。\n"
        "展開したフォルダは、ショートカットの先なので消さないでください。\n"
        "このパッケージは CPU で動作します。\n"
    )


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "imageto3d"})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle)


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
