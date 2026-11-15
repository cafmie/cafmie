"""FastAPI app: local UI + peer transfer endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .discovery import DiscoveryService
from .models import DeviceRole, GameProfile
from .registry import Registry
from .transfer import TransferHub, peer_reachable, receive_game_archive, receive_saves_archive
from .verify import format_bytes, verify_all, verify_game


class SettingsUpdate(BaseModel):
    device_name: Optional[str] = None
    role: Optional[DeviceRole] = None


class GameUpsert(BaseModel):
    id: Optional[str] = None
    title: str
    game_folder: str
    save_folders: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class ManualPeer(BaseModel):
    host: str
    port: int = 8787
    name: str = "Manual peer"
    device_id: str = "manual"
    role: DeviceRole = DeviceRole.MAIN


class SendRequest(BaseModel):
    game_id: str
    peer_host: str
    peer_port: int = 8787
    policy: str = "newer_wins"


def create_app(registry: Optional[Registry] = None) -> FastAPI:
    registry = registry or Registry()
    work_dir = Path(registry.data_dir) / "tmp"
    work_dir.mkdir(parents=True, exist_ok=True)
    hub = TransferHub(work_dir)
    incoming_games_root = Path(registry.data_dir) / "received_games"
    incoming_games_root.mkdir(parents=True, exist_ok=True)

    discovery = DiscoveryService(
        device_id=registry.settings.device_id,
        device_name=registry.settings.device_name,
        role=registry.settings.role,
        http_port=registry.settings.http_port,
        discovery_port=registry.settings.discovery_port,
    )
    discovery.start()

    app = FastAPI(title="PC Transfer", version="0.1.0")
    app.state.registry = registry
    app.state.discovery = discovery
    app.state.hub = hub

    web_dir = Path(__file__).resolve().parent / "web"
    if not web_dir.exists():
        # repo-root layout fallback (pc-transfer/web)
        web_dir = Path(__file__).resolve().parents[2] / "web"

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": "0.1.0"}

    @app.get("/api/settings")
    def get_settings() -> dict:
        return registry.settings.model_dump(mode="json")

    @app.put("/api/settings")
    def put_settings(body: SettingsUpdate) -> dict:
        kwargs: dict[str, Any] = {}
        if body.device_name is not None:
            kwargs["device_name"] = body.device_name
            discovery.device_name = body.device_name
        if body.role is not None:
            kwargs["role"] = body.role
            discovery.role = body.role
        if kwargs:
            registry.update_settings(**kwargs)
        return registry.settings.model_dump(mode="json")

    @app.get("/api/peers")
    def list_peers() -> dict:
        peers = [p.model_dump(mode="json") for p in discovery.list_peers()]
        return {"peers": peers}

    @app.post("/api/peers/manual")
    def add_manual_peer(body: ManualPeer) -> dict:
        from .models import PeerInfo, utc_now

        peer = PeerInfo(
            device_id=body.device_id,
            name=body.name,
            role=body.role,
            host=body.host,
            port=body.port,
            last_seen=utc_now(),
        )
        discovery.inject_peer_for_tests(peer)
        reachable = peer_reachable(f"http://{body.host}:{body.port}")
        return {"peer": peer.model_dump(mode="json"), "reachable": reachable}

    @app.get("/api/games")
    def list_games() -> dict:
        games = [g.model_dump(mode="json") for g in registry.list_games()]
        return {"games": games}

    @app.post("/api/games")
    def upsert_game(body: GameUpsert) -> dict:
        game = registry.upsert_game(
            title=body.title,
            game_folder=body.game_folder,
            save_folders=body.save_folders,
            notes=body.notes,
            game_id=body.id,
        )
        return game.model_dump(mode="json")

    @app.delete("/api/games/{game_id}")
    def delete_game(game_id: str) -> dict:
        registry.delete_game(game_id)
        return {"ok": True}

    @app.get("/api/games/verify")
    def verify_games() -> dict:
        results = verify_all(registry.list_games())
        payload = []
        for r in results:
            item = r.model_dump(mode="json")
            item["game_folder"]["size_label"] = format_bytes(r.game_folder.size_bytes)
            for s in item["save_folders"]:
                s["size_label"] = format_bytes(s["size_bytes"])
            payload.append(item)
        return {"results": payload}

    @app.get("/api/games/{game_id}/verify")
    def verify_one(game_id: str) -> dict:
        try:
            game = registry.get_game(game_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        r = verify_game(game)
        item = r.model_dump(mode="json")
        item["game_folder"]["size_label"] = format_bytes(r.game_folder.size_bytes)
        for s in item["save_folders"]:
            s["size_label"] = format_bytes(s["size_bytes"])
        return item

    @app.post("/api/transfer/send-game")
    def send_game(body: SendRequest) -> dict:
        try:
            game = registry.get_game(body.game_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        base = f"http://{body.peer_host}:{body.peer_port}"
        if not peer_reachable(base):
            raise HTTPException(400, f"Peer not reachable at {base}")
        job_id = hub.start_send_game(game, base)
        return {"job_id": job_id}

    @app.post("/api/transfer/send-saves")
    def send_saves(body: SendRequest) -> dict:
        try:
            game = registry.get_game(body.game_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        base = f"http://{body.peer_host}:{body.peer_port}"
        if not peer_reachable(base):
            raise HTTPException(400, f"Peer not reachable at {base}")
        job_id = hub.start_send_saves(game, base, policy=body.policy)
        return {"job_id": job_id}

    @app.get("/api/transfer/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        progress = hub.get(job_id)
        if not progress:
            raise HTTPException(404, "Unknown job")
        return progress.model_dump(mode="json")

    @app.post("/api/transfer/receive-game")
    async def receive_game(
        meta: str = Form(...),
        archive: UploadFile = File(...),
    ) -> dict:
        payload = json.loads(meta)
        incoming = GameProfile.model_validate(payload["game"])
        data = await archive.read()
        # Prefer an already-registered local install path for this game id
        if incoming.id in registry.games:
            local = registry.get_game(incoming.id)
            game = incoming.model_copy(update={"game_folder": local.game_folder})
            keep_saves = [s.model_dump() for s in local.save_folders] or [
                s.model_dump() for s in incoming.save_folders
            ]
        else:
            game = incoming
            keep_saves = [s.model_dump() for s in incoming.save_folders]
        target = receive_game_archive(data, game, incoming_games_root, work_dir)
        registry.upsert_game(
            title=game.title,
            game_folder=str(target),
            save_folders=keep_saves,
            notes=game.notes,
            game_id=game.id,
        )
        return {"ok": True, "game_folder": str(target)}

    @app.post("/api/transfer/receive-saves")
    async def receive_saves(
        meta: str = Form(...),
        archive: UploadFile = File(...),
    ) -> dict:
        payload = json.loads(meta)
        game = GameProfile.model_validate(payload["game"])
        policy = payload.get("policy", "newer_wins")
        data = await archive.read()

        # Ensure local game entry exists so save paths are known
        if game.id not in registry.games:
            # Keep remote save path hints but they may not exist locally —
            # receiver should have registered matching save folders already.
            registry.upsert_game(
                title=game.title,
                game_folder=game.game_folder,
                save_folders=[s.model_dump() for s in game.save_folders],
                notes=game.notes,
                game_id=game.id,
            )
        local_game = registry.get_game(game.id)
        # Sync into *local* registered save paths, matching by save folder id / label
        merged = game.model_copy(update={"save_folders": local_game.save_folders or game.save_folders})
        result = receive_saves_archive(data, merged, policy=policy, work_dir=work_dir)
        return {"ok": True, **result}

    @app.post("/api/demo/seed")
    def demo_seed() -> dict:
        """Create sample game folders + registry entries for demos/tests."""
        demo_root = Path(registry.data_dir) / "demo"
        game_dir = demo_root / "Sample Quest"
        save_dir = demo_root / "Sample Quest Saves"
        game_dir.mkdir(parents=True, exist_ok=True)
        save_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "game.exe").write_text("demo binary", encoding="utf-8")
        (game_dir / "readme.txt").write_text("Sample Quest v1", encoding="utf-8")
        (save_dir / "slot1.sav").write_text("progress=10", encoding="utf-8")
        game = registry.upsert_game(
            title="Sample Quest",
            game_folder=str(game_dir),
            save_folders=[{"label": "Local saves", "path": str(save_dir)}],
            notes="Demo profile for UI screenshots",
        )
        return {"game": game.model_dump(mode="json"), "demo_root": str(demo_root)}

    @app.get("/api/pick-folder")
    def pick_folder() -> dict:
        """Native folder picker via tkinter (Windows/Linux desktop)."""
        if os.environ.get("PC_TRANSFER_HEADLESS") == "1":
            raise HTTPException(503, "Folder picker unavailable in headless mode")
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"tkinter unavailable: {exc}") from exc

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select folder")
        root.destroy()
        if not path:
            return {"path": None}
        return {"path": path}

    if web_dir.exists():
        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

        app.mount("/static", StaticFiles(directory=web_dir), name="static")

    return app
