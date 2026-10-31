import json
import os
from pathlib import Path

from imageto3d.__main__ import main
from imageto3d.launch import app_command, desktop_file_text, is_ready


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
