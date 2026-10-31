"""Install the app onto this computer: menu entry, command, and PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .launch import desktop_file_text
from .paths import REPO_DIR, WEB_DIR

MARKER_BEGIN = "# >>> imageto3d >>>"
MARKER_END = "# <<< imageto3d <<<"
PATH_BLOCK = f"{MARKER_BEGIN}\nexport PATH=\"$HOME/.local/bin:$PATH\"\n{MARKER_END}\n"


def launcher_path() -> Path:
    return REPO_DIR / "imageto3d.sh"


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
    home_bin = (Path.home() / ".local" / "bin").resolve()
    for folder in _path_dirs():
        try:
            if folder.is_dir() and os.access(folder, os.W_OK) and folder.resolve() != home_bin:
                return folder
        except OSError:
            continue
    return None


def status() -> dict:
    desktop = desktop_path()
    installed = False
    if desktop.is_file():
        text = desktop.read_text(encoding="utf-8")
        installed = "Name=画像から3D" in text and "imageto3d.sh" in text
    if installed:
        message = "このPCにインストール済みです。アプリメニューの「画像から3D」から開けます。"
    else:
        message = "アプリメニューに追加すると、あとから「画像から3D」で開けます。"
    command = shutil.which("imageto3d")
    return {
        "installed": installed,
        "desktop": str(desktop) if desktop.is_file() else None,
        "command": command,
        "message": message,
    }


def install() -> dict:
    launcher = launcher_path()
    if not launcher.is_file():
        raise RuntimeError("起動スクリプト imageto3d.sh が見つかりません。")
    launcher.chmod(launcher.stat().st_mode | 0o111)

    desktop = desktop_path()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    icon = WEB_DIR / "favicon.svg"
    desktop.write_text(desktop_file_text(launcher.resolve(), icon.resolve()), encoding="utf-8")
    desktop.chmod(0o644)

    command = _place_link(launcher.resolve(), user_command_path())
    notes = [
        f"アプリメニュー: {desktop}",
        f"コマンド: {command}",
    ]
    path_dir = _writable_path_dir()
    if path_dir is not None:
        linked = _place_link(launcher.resolve(), path_dir / "imageto3d")
        notes.append(f"PATH 上のコマンド: {linked}")
    snippet = _ensure_path_snippet()
    if snippet:
        notes.append(snippet)
    _refresh_menu()
    result = status()
    result["notes"] = notes
    result["message"] = "このPCにインストールしました。アプリメニューの「画像から3D」から開けます。"
    return result
