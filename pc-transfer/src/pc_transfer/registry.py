"""Persistent local registry of game profiles and app settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .models import AppSettings, DeviceRole, GameProfile, SaveFolder, new_id, utc_now


def default_data_dir() -> Path:
    override = os.environ.get("PC_TRANSFER_DATA")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "PCTransfer"
    return Path.home() / ".local" / "share" / "pc-transfer"


class Registry:
    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self.games_path = self.data_dir / "games.json"
        self.settings = self._load_settings()
        self.games: dict[str, GameProfile] = self._load_games()

    def _load_settings(self) -> AppSettings:
        if self.settings_path.exists():
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            settings = AppSettings.model_validate(raw)
        else:
            role = DeviceRole.HANDHELD if os.environ.get("PC_TRANSFER_ROLE") == "handheld" else DeviceRole.MAIN
            name = os.environ.get("PC_TRANSFER_NAME") or (
                "Handheld" if role == DeviceRole.HANDHELD else "Main PC"
            )
            settings = AppSettings(device_name=name, role=role, data_dir=str(self.data_dir))
        settings.data_dir = str(self.data_dir)
        self._save_settings(settings)
        return settings

    def _save_settings(self, settings: AppSettings) -> None:
        self.settings_path.write_text(
            settings.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _load_games(self) -> dict[str, GameProfile]:
        if not self.games_path.exists():
            return {}
        raw = json.loads(self.games_path.read_text(encoding="utf-8"))
        games = [GameProfile.model_validate(item) for item in raw]
        return {g.id: g for g in games}

    def save_games(self) -> None:
        payload = [g.model_dump(mode="json") for g in self.games.values()]
        self.games_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def update_settings(self, **kwargs) -> AppSettings:
        data = self.settings.model_dump()
        data.update(kwargs)
        self.settings = AppSettings.model_validate(data)
        self.settings.data_dir = str(self.data_dir)
        self._save_settings(self.settings)
        return self.settings

    def list_games(self) -> list[GameProfile]:
        return sorted(self.games.values(), key=lambda g: g.title.lower())

    def get_game(self, game_id: str) -> GameProfile:
        if game_id not in self.games:
            raise KeyError(f"Unknown game id: {game_id}")
        return self.games[game_id]

    def upsert_game(
        self,
        title: str,
        game_folder: str,
        save_folders: list[dict],
        notes: str = "",
        game_id: Optional[str] = None,
    ) -> GameProfile:
        saves = [
            SaveFolder(
                id=s.get("id") or new_id(),
                label=s.get("label") or "Saves",
                path=s["path"],
            )
            for s in save_folders
        ]
        if game_id and game_id in self.games:
            existing = self.games[game_id]
            game = existing.model_copy(
                update={
                    "title": title,
                    "game_folder": game_folder,
                    "save_folders": saves,
                    "notes": notes,
                    "updated_at": utc_now(),
                }
            )
        else:
            game = GameProfile(
                id=game_id or new_id(),
                title=title,
                game_folder=game_folder,
                save_folders=saves,
                notes=notes,
            )
        self.games[game.id] = game
        self.save_games()
        return game

    def delete_game(self, game_id: str) -> None:
        if game_id in self.games:
            del self.games[game_id]
            self.save_games()
