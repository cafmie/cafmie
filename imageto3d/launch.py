"""Start the local server and open it as one application window."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .paths import REPO_DIR, WEB_DIR

APP_NAME = "画像から3D"
_BROWSERS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
)


def profile_dir() -> Path:
    override = os.environ.get("IMAGETO3D_PROFILE")
    if override:
        path = Path(override).expanduser()
    else:
        path = Path.home() / ".local" / "share" / "imageto3d" / "chrome-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_browser() -> str | None:
    for name in _BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def app_command(browser: str, url: str, profile: Path) -> list[str]:
    """Chrome in application mode: one window, no tab strip or address bar."""

    return [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--class=imageto3d",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1180,780",
    ]


def is_ready(url: str, timeout: float = 0.4) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:
            if response.status != 200:
                return False
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return False
    return body.get("ok") is True


def wait_until_ready(url: str, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_ready(url):
            return True
        time.sleep(0.15)
    return False


def desktop_file_text(launcher: Path, icon: Path) -> str:
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={APP_NAME}",
            "Comment=写真をこのPCの中で立体モデルにします",
            f"Exec={launcher}",
            f"Icon={icon}",
            "Terminal=false",
            "Categories=Graphics;3DGraphics;",
            "StartupWMClass=imageto3d",
            "",
        ]
    )


def install_desktop_entry() -> Path:
    data = Path.home() / ".local" / "share" / "applications"
    data.mkdir(parents=True, exist_ok=True)
    destination = data / "imageto3d.desktop"
    launcher = REPO_DIR / "imageto3d.sh"
    icon = WEB_DIR / "favicon.svg"
    destination.write_text(desktop_file_text(launcher, icon), encoding="utf-8")
    destination.chmod(0o644)
    return destination


def has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_app_window(url: str) -> subprocess.Popen[bytes] | None:
    browser = find_browser()
    if browser is None or not has_display():
        return None
    return subprocess.Popen(app_command(browser, url, profile_dir()))


def run_server(host: str, port: int):
    """Run uvicorn on a background thread and return the server plus that thread."""

    import uvicorn

    config = uvicorn.Config("imageto3d.server:app", host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, name="imageto3d-http", daemon=True)
    thread.start()
    return server, thread


def stop_server(server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=8)
