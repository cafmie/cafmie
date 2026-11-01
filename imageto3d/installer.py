"""Install the app onto this computer: menu entry, command, and PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .launch import APP_NAME, _is_windows, desktop_file_text
from .paths import REPO_DIR, WEB_DIR, running_from_checkout

MARKER_BEGIN = "# >>> imageto3d >>>"
MARKER_END = "# <<< imageto3d <<<"
PATH_BLOCK = f"{MARKER_BEGIN}\nexport PATH=\"$HOME/.local/bin:$PATH\"\n{MARKER_END}\n"
LEGACY_NAME = "画像から3D"
LEGACY_VERSION = "0.1.0"


def launcher_path() -> Path:
    checkout = REPO_DIR / "imageto3d.sh"
    if running_from_checkout() and checkout.is_file():
        return checkout
    argv0 = Path(sys.argv[0])
    try:
        if argv0.name == "imageto3d" and argv0.is_file():
            return argv0.resolve()
    except OSError:
        pass
    found = shutil.which("imageto3d")
    if found:
        return Path(found)
    raise RuntimeError("起動コマンド imageto3d が見つかりません。")


def desktop_path() -> Path:
    return Path.home() / ".local" / "share" / "applications" / "imageto3d.desktop"


def user_command_path() -> Path:
    return Path.home() / ".local" / "bin" / "imageto3d"


def _path_dirs() -> list[Path]:
    return [Path(entry) for entry in os.environ.get("PATH", "").split(":") if entry]


def _home_bin_on_path() -> bool:
    home_bin = Path.home() / ".local" / "bin"
    return any(path == home_bin for path in _path_dirs())


def _place_link(launcher: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() and destination.resolve() == launcher.resolve():
        return destination
    if destination.is_symlink() or destination.exists():
        destination.unlink()
    destination.symlink_to(launcher)
    return destination


def _ensure_path_snippet() -> str | None:
    if _home_bin_on_path():
        return None
    bashrc = Path.home() / ".bashrc"
    text = bashrc.read_text(encoding="utf-8") if bashrc.is_file() else ""
    if MARKER_BEGIN in text:
        return "新しいターミナルから imageto3d コマンドが使えます"
    if text and not text.endswith("\n"):
        text += "\n"
    bashrc.write_text(text + "\n" + PATH_BLOCK, encoding="utf-8")
    return "~/.local/bin を PATH に追加しました。新しいターミナルから imageto3d が使えます"


def _refresh_menu() -> None:
    tool = shutil.which("update-desktop-database")
    if tool is None:
        return
    folder = desktop_path().parent
    subprocess.run([tool, str(folder)], check=False, capture_output=True)


def _writable_path_dir() -> Path | None:
    """A conventional bin directory already on PATH, never a toolchain folder."""
    home = Path.home()
    home_bin = (home / ".local" / "bin").resolve()
    on_path: set[Path] = set()
    for folder in _path_dirs():
        try:
            if folder.is_dir():
                on_path.add(folder.resolve())
        except OSError:
            continue
    for folder in (Path("/usr/local/bin"), home / "bin", Path("/usr/bin")):
        try:
            resolved = folder.resolve()
            if resolved == home_bin or resolved not in on_path:
                continue
            if folder.is_dir() and os.access(folder, os.W_OK):
                return folder
        except OSError:
            continue
    return None


def version_path() -> Path:
    """Recorded install version. Kept under the home directory so tests stay isolated."""

    if _is_windows():
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "imageto3d" / "version"
    return Path.home() / ".local" / "share" / "imageto3d" / "version"


def _windows_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _open_hint() -> str:
    return f"アプリメニューの「{APP_NAME}」から開けます。"


def _parse_version(text: str) -> tuple[int, int, int]:
    numbers: list[int] = []
    for part in text.strip().split(".")[:3]:
        digits = ""
        for character in part:
            if character.isdigit():
                digits += character
            else:
                break
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def _format_version(parts: tuple[int, int, int]) -> str:
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def _read_recorded_version() -> str | None:
    path = version_path()
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _write_version(version: str) -> None:
    path = version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(version + "\n", encoding="utf-8")


def _files_installed() -> bool:
    if _is_windows():
        menu = _windows_menu_dir()
        return (menu / f"{APP_NAME}.lnk").is_file() or (menu / f"{LEGACY_NAME}.lnk").is_file()
    desktop = desktop_path()
    if not desktop.is_file():
        return False
    text = desktop.read_text(encoding="utf-8")
    named = f"Name={APP_NAME}" in text or f"Name={LEGACY_NAME}" in text
    return named and "StartupWMClass=imageto3d" in text


def _next_version(already_installed: bool) -> tuple[str, bool]:
    """Package version on a fresh install. An existing install is overwritten and raised."""

    if not already_installed:
        return __version__, False
    recorded = _parse_version(_read_recorded_version() or LEGACY_VERSION)
    package = _parse_version(__version__)
    if package > recorded:
        return _format_version(package), True
    return _format_version((recorded[0], recorded[1], recorded[2] + 1)), True


def _install_message(version: str, upgraded: bool) -> str:
    if upgraded:
        return f"上書きしました。バージョンは {version} です。{_open_hint()}"
    return f"このPCにインストールしました。バージョンは {version} です。{_open_hint()}"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _install_windows_shortcut() -> str:
    menu = _windows_menu_dir()
    menu.mkdir(parents=True, exist_ok=True)
    old = menu / f"{LEGACY_NAME}.lnk"
    if old.exists():
        old.unlink()
    shortcut = menu / f"{APP_NAME}.lnk"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    target = pythonw if pythonw.is_file() else Path(sys.executable)
    work = Path(sys.executable).resolve().parent
    command = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$link = $shell.CreateShortcut({_ps_quote(str(shortcut))})",
            f"$link.TargetPath = {_ps_quote(str(target))}",
            "$link.Arguments = '-m imageto3d'",
            f"$link.WorkingDirectory = {_ps_quote(str(work))}",
            f"$link.Description = {_ps_quote(APP_NAME)}",
            "$link.Save()",
        ]
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
    )
    return f"スタートメニュー: {shortcut}"


def status() -> dict:
    desktop = desktop_path()
    installed = _files_installed()
    version = None
    if installed:
        version = _read_recorded_version() or LEGACY_VERSION
        message = f"インストール済みです（バージョン {version}）。{_open_hint()}"
    else:
        message = f"アプリメニューに追加すると、あとから「{APP_NAME}」で開けます。"
    command = shutil.which("imageto3d")
    return {
        "installed": installed,
        "version": version,
        "desktop": str(desktop) if desktop.is_file() else None,
        "command": command,
        "message": message,
    }


def install() -> dict:
    already = _files_installed()
    version, upgraded = _next_version(already)
    notes: list[str] = []
    if _is_windows():
        notes.append(_install_windows_shortcut())
    else:
        launcher = launcher_path()
        if not launcher.is_file():
            raise RuntimeError("起動コマンド imageto3d が見つかりません。")
        try:
            launcher.chmod(launcher.stat().st_mode | 0o111)
        except OSError:
            pass

        desktop = desktop_path()
        desktop.parent.mkdir(parents=True, exist_ok=True)
        icon = WEB_DIR / "favicon.svg"
        desktop.write_text(desktop_file_text(launcher.resolve(), icon.resolve()), encoding="utf-8")
        desktop.chmod(0o644)

        command = _place_link(launcher.resolve(), user_command_path())
        notes.extend(
            [
                f"アプリメニュー: {desktop}",
                f"コマンド: {command}",
            ]
        )
        path_dir = _writable_path_dir()
        if path_dir is not None:
            linked = _place_link(launcher.resolve(), path_dir / "imageto3d")
            notes.append(f"PATH 上のコマンド: {linked}")
        snippet = _ensure_path_snippet()
        if snippet:
            notes.append(snippet)
        _refresh_menu()
    _write_version(version)
    result = status()
    result["notes"] = notes
    result["upgraded"] = upgraded
    result["version"] = version
    result["message"] = _install_message(version, upgraded)
    return result
