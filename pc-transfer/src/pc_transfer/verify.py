"""Verify registered game and save paths on this machine."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .models import GameProfile, GameVerification, PathCheck


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def inspect_path(path_str: str) -> PathCheck:
    path = Path(path_str).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        return PathCheck(path=path_str, exists=False, error=str(exc))

    if not path.exists():
        return PathCheck(path=str(path), exists=False)

    try:
        st = path.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        if path.is_dir():
            return PathCheck(
                path=str(path),
                exists=True,
                is_dir=True,
                size_bytes=_dir_size(path),
                last_modified=mtime,
            )
        return PathCheck(
            path=str(path),
            exists=True,
            is_dir=False,
            size_bytes=st.st_size,
            last_modified=mtime,
        )
    except OSError as exc:
        return PathCheck(path=str(path), exists=True, error=str(exc))


def verify_game(game: GameProfile) -> GameVerification:
    game_check = inspect_path(game.game_folder)
    save_checks = [inspect_path(s.path) for s in game.save_folders]
    ok = game_check.exists and game_check.is_dir and all(c.exists for c in save_checks)
    return GameVerification(
        game_id=game.id,
        title=game.title,
        game_folder=game_check,
        save_folders=save_checks,
        ok=ok,
    )


def verify_all(games: list[GameProfile]) -> list[GameVerification]:
    return [verify_game(g) for g in games]


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"
