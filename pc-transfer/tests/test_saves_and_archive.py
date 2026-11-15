from __future__ import annotations

import time
from pathlib import Path

from pc_transfer.archive import unzip_to, zip_folder
from pc_transfer.models import FreshnessAction
from pc_transfer.saves import plan_save_sync, sync_saves


def test_zip_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "game"
    src.mkdir()
    (src / "bin").mkdir()
    (src / "bin" / "run.exe").write_bytes(b"abc")
    (src / "data.txt").write_text("hello", encoding="utf-8")

    zpath = tmp_path / "game.zip"
    zip_folder(src, zpath)
    assert zpath.exists() and zpath.stat().st_size > 0

    out = tmp_path / "out"
    unzip_to(zpath, out)
    assert (out / "bin" / "run.exe").read_bytes() == b"abc"
    assert (out / "data.txt").read_text(encoding="utf-8") == "hello"


def test_freshness_newer_wins(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()

    (remote / "a.sav").write_text("new", encoding="utf-8")
    (local / "a.sav").write_text("old", encoding="utf-8")
    older = time.time() - 100
    newer = time.time()
    import os

    os.utime(local / "a.sav", (older, older))
    os.utime(remote / "a.sav", (newer, newer))

    (remote / "b.sav").write_text("only-remote", encoding="utf-8")
    (local / "c.sav").write_text("only-local", encoding="utf-8")

    decisions = plan_save_sync(remote, local, policy="newer_wins")
    by_path = {d.relative_path: d for d in decisions}
    assert by_path["a.sav"].action == FreshnessAction.OVERWRITE
    assert by_path["b.sav"].action == FreshnessAction.OVERWRITE
    assert "c.sav" not in by_path  # plan only considers incoming files

    resolved, copied = sync_saves(remote, local, policy="newer_wins")
    assert copied == 2
    assert (local / "a.sav").read_text(encoding="utf-8") == "new"
    assert (local / "b.sav").read_text(encoding="utf-8") == "only-remote"
    assert (local / "c.sav").read_text(encoding="utf-8") == "only-local"


def test_keep_local_when_local_newer(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    (remote / "slot.sav").write_text("remote", encoding="utf-8")
    (local / "slot.sav").write_text("local-newer", encoding="utf-8")
    import os

    older = time.time() - 50
    newer = time.time()
    os.utime(remote / "slot.sav", (older, older))
    os.utime(local / "slot.sav", (newer, newer))

    decisions = plan_save_sync(remote, local, policy="newer_wins")
    assert decisions[0].action == FreshnessAction.KEEP_LOCAL
    _, copied = sync_saves(remote, local, policy="newer_wins")
    assert copied == 0
    assert (local / "slot.sav").read_text(encoding="utf-8") == "local-newer"
