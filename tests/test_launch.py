import json
from pathlib import Path

from imageto3d.__main__ import main
from imageto3d.launch import app_command, desktop_file_text, install_desktop_entry, is_ready


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


def test_install_writes_a_desktop_entry(monkeypatch, tmp_path):
    from imageto3d.paths import REPO_DIR, WEB_DIR

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = install_desktop_entry()
    text = path.read_text(encoding="utf-8")
    assert path == tmp_path / ".local" / "share" / "applications" / "imageto3d.desktop"
    assert text == desktop_file_text(REPO_DIR / "imageto3d.sh", WEB_DIR / "favicon.svg")
