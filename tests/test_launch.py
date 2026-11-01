import json
import os
import subprocess
import sys
from pathlib import Path

from imageto3d.__main__ import ensure_stdio, main
from imageto3d.launch import (
    app_command,
    choose_listen_port,
    command_line_contains,
    desktop_file_text,
    find_browser,
    has_display,
    is_ready,
    wait_for_window,
)


def test_windows_edge_is_found_without_a_display_variable(monkeypatch, tmp_path):
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"")
    monkeypatch.setattr("imageto3d.launch._is_windows", lambda: True)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "missing"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr("imageto3d.launch.shutil.which", lambda name: None)
    assert find_browser() == str(edge)
    assert has_display() is True


def test_busy_port_moves_to_the_next_free_one(monkeypatch):
    monkeypatch.setattr("imageto3d.launch.can_bind", lambda host, port: port != 7860)
    monkeypatch.setattr("imageto3d.launch.wait_until_ready", lambda url, timeout=8: False)
    port, note = choose_listen_port("127.0.0.1", 7860)
    assert port == 7861
    assert note == "7860 は使用中のため、7861 で開きます。"


def test_existing_app_keeps_its_port(monkeypatch):
    monkeypatch.setattr("imageto3d.launch.can_bind", lambda host, port: False)
    monkeypatch.setattr("imageto3d.launch.wait_until_ready", lambda url, timeout=8: True)
    port, note = choose_listen_port("127.0.0.1", 7860)
    assert port == 7860
    assert note is None


def test_app_command_opens_one_window():
    command = app_command("/usr/bin/google-chrome", "http://127.0.0.1:7860", Path("/tmp/profile"))
    assert command[0] == "/usr/bin/google-chrome"
    assert "--app=http://127.0.0.1:7860" in command
    assert "--user-data-dir=/tmp/profile" in command
    assert "--class=imageto3d" in command


def test_is_ready_accepts_the_health_payload(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode()

    monkeypatch.setattr("imageto3d.launch.urllib.request.urlopen", lambda *args, **kwargs: Response())
    assert is_ready("http://127.0.0.1:9") is True


def test_is_ready_is_false_when_nothing_is_listening(monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("refused")

    monkeypatch.setattr("imageto3d.launch.urllib.request.urlopen", explode)
    assert is_ready("http://127.0.0.1:9") is False


def test_default_invocation_launches_the_app(monkeypatch):
    seen = {}

    def fake_launch(host, port):
        seen["host"] = host
        seen["port"] = port
        return 0

    monkeypatch.setattr("imageto3d.__main__._launch_app", fake_launch)
    assert main([]) == 0
    assert seen == {"host": "127.0.0.1", "port": 7860}


def test_command_line_contains_sees_a_live_process():
    marker = "imageto3d-window-marker"
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", marker])
    try:
        assert command_line_contains(marker) is True
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_window_wait_follows_the_browser_child_after_the_launcher_exits(monkeypatch):
    clock = {"t": 0.0}

    class Proc:
        def poll(self):
            return 0

    monkeypatch.setattr("imageto3d.launch.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr("imageto3d.launch.time.sleep", lambda seconds: clock.__setitem__("t", clock["t"] + seconds))
    seen = {"n": 0}

    def contains(needle):
        seen["n"] += 1
        return seen["n"] < 3

    monkeypatch.setattr("imageto3d.launch.command_line_contains", contains)
    assert wait_for_window(Proc(), Path("/tmp/imageto3d-profile")) is True


def test_window_wait_keeps_a_durable_browser_until_it_closes(monkeypatch):
    clock = {"t": 0.0}

    class Proc:
        def poll(self):
            return None if clock["t"] < 3 else 0

    monkeypatch.setattr("imageto3d.launch.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr("imageto3d.launch.time.sleep", lambda seconds: clock.__setitem__("t", clock["t"] + seconds))
    monkeypatch.setattr("imageto3d.launch.command_line_contains", lambda needle: False)
    assert wait_for_window(Proc(), Path("/tmp/imageto3d-profile"), stub_limit=1.5) is True


def test_window_wait_reports_when_nothing_stays_open(monkeypatch):
    clock = {"t": 0.0}

    class Proc:
        def poll(self):
            return 0

    monkeypatch.setattr("imageto3d.launch.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr("imageto3d.launch.time.sleep", lambda seconds: clock.__setitem__("t", clock["t"] + seconds))
    monkeypatch.setattr("imageto3d.launch.command_line_contains", lambda needle: False)
    assert wait_for_window(Proc(), Path("/tmp/imageto3d-profile"), grace=1.0) is False


def test_pythonw_without_stdio_still_tries_to_open_a_window(monkeypatch, tmp_path):
    from imageto3d.__main__ import _launch_app

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("imageto3d.launch.is_ready", lambda url, timeout=0.4: False)
    monkeypatch.setattr("imageto3d.launch.choose_listen_port", lambda host, port: (port, None))
    monkeypatch.setattr("imageto3d.launch.wait_until_ready", lambda url, timeout=20.0: True)
    monkeypatch.setattr("imageto3d.launch.run_server", lambda host, port: (object(), object()))
    stopped = {}
    monkeypatch.setattr("imageto3d.launch.stop_server", lambda server, thread: stopped.setdefault("stopped", True))
    opened = {}

    class Proc:
        def poll(self):
            return 0

    def fake_open(url):
        opened["url"] = url
        return Proc()

    monkeypatch.setattr("imageto3d.launch.open_app_window", fake_open)
    monkeypatch.setattr("imageto3d.launch.command_line_contains", lambda needle: False)
    clock = {"t": 0.0}
    monkeypatch.setattr("imageto3d.launch.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr("imageto3d.launch.time.sleep", lambda seconds: clock.__setitem__("t", clock["t"] + seconds))

    assert _launch_app("127.0.0.1", 7860) == 1
    assert opened["url"] == "http://127.0.0.1:7860"
    assert stopped["stopped"] is True
    log = (tmp_path / ".local" / "share" / "imageto3d" / "app.log").read_text(encoding="utf-8")
    assert "img to 3Dを起動しています" in log
    assert "画面を開けませんでした" in log


def test_ensure_stdio_leaves_a_normal_console_alone(monkeypatch):
    original = sys.stdout
    ensure_stdio()
    assert sys.stdout is original


def test_install_registers_the_menu_and_command(monkeypatch, tmp_path):
    from imageto3d.installer import install, status
    from imageto3d.paths import REPO_DIR, WEB_DIR

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr("imageto3d.installer.shutil.which", lambda name: None)
    before = status()
    assert before["installed"] is False
    result = install()
    desktop = tmp_path / ".local" / "share" / "applications" / "imageto3d.desktop"
    command = tmp_path / ".local" / "bin" / "imageto3d"
    assert result["installed"] is True
    assert desktop.read_text(encoding="utf-8") == desktop_file_text(
        (REPO_DIR / "imageto3d.sh").resolve(),
        (WEB_DIR / "favicon.svg").resolve(),
    )
    assert command.is_symlink()
    assert command.resolve() == (REPO_DIR / "imageto3d.sh").resolve()
    bashrc = (tmp_path / ".bashrc").read_text(encoding="utf-8")
    assert "# >>> imageto3d >>>" in bashrc
    again = install()
    assert again["installed"] is True
    assert bashrc.count("# >>> imageto3d >>>") == (tmp_path / ".bashrc").read_text(encoding="utf-8").count(
        "# >>> imageto3d >>>"
    )


def test_install_uses_the_console_script_outside_a_checkout(monkeypatch, tmp_path):
    import sys

    from imageto3d.installer import install

    script = tmp_path / "bin" / "imageto3d"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr("imageto3d.paths.REPO_DIR", tmp_path / "site-packages")
    monkeypatch.setattr(sys, "argv", [str(script)])
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr("imageto3d.installer.shutil.which", lambda name: None)

    result = install()

    text = (home / ".local" / "share" / "applications" / "imageto3d.desktop").read_text(encoding="utf-8")
    assert f"Exec={script.resolve()}" in text
    assert result["installed"] is True


def test_install_skips_toolchain_directories(monkeypatch, tmp_path):
    from imageto3d.installer import install

    home = tmp_path / "home"
    cargo = tmp_path / "cargo" / "bin"
    cargo.mkdir(parents=True)
    user_bin = home / "bin"
    user_bin.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("PATH", f"{cargo}{os.pathsep}{user_bin}")
    monkeypatch.setattr("imageto3d.installer.shutil.which", lambda name: None)

    install()

    assert not (cargo / "imageto3d").exists()
    assert (user_bin / "imageto3d").is_symlink()
    assert (home / ".local" / "bin" / "imageto3d").is_symlink()


def test_second_install_overwrites_and_raises_the_version(monkeypatch, tmp_path):
    from imageto3d.installer import install, status

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr("imageto3d.installer.shutil.which", lambda name: None)

    first = install()
    version_file = tmp_path / ".local" / "share" / "imageto3d" / "version"
    assert first["version"] == "0.1.1"
    assert first["upgraded"] is False
    assert "このPCにインストールしました。バージョンは 0.1.1 です。" in first["message"]
    assert "img to 3D" in first["message"]
    assert version_file.read_text(encoding="utf-8").strip() == "0.1.1"

    second = install()
    desktop = (tmp_path / ".local" / "share" / "applications" / "imageto3d.desktop").read_text(encoding="utf-8")
    assert second["version"] == "0.1.2"
    assert second["upgraded"] is True
    assert "上書きしました。バージョンは 0.1.2 です。" in second["message"]
    assert version_file.read_text(encoding="utf-8").strip() == "0.1.2"
    assert "Name=img to 3D" in desktop
    state = status()
    assert state["installed"] is True
    assert state["version"] == "0.1.2"
    assert "インストール済みです（バージョン 0.1.2）" in state["message"]


def test_legacy_menu_name_is_overwritten_and_raised_to_the_package_version(monkeypatch, tmp_path):
    from imageto3d.installer import install, status

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr("imageto3d.installer.shutil.which", lambda name: None)
    desktop = tmp_path / ".local" / "share" / "applications" / "imageto3d.desktop"
    desktop.parent.mkdir(parents=True)
    desktop.write_text("[Desktop Entry]\nName=画像から3D\nStartupWMClass=imageto3d\n", encoding="utf-8")

    state = status()
    assert state["installed"] is True
    assert state["version"] == "0.1.0"
    result = install()
    assert result["upgraded"] is True
    assert result["version"] == "0.1.1"
    assert "上書きしました。バージョンは 0.1.1 です。" in result["message"]
    assert "Name=img to 3D" in desktop.read_text(encoding="utf-8")
    assert "Name=画像から3D" not in desktop.read_text(encoding="utf-8")
