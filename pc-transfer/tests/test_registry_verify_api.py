from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pc_transfer.registry import Registry
from pc_transfer.server import create_app
from pc_transfer.verify import verify_game


def test_registry_and_verify(tmp_path: Path) -> None:
    game_dir = tmp_path / "GameA"
    save_dir = tmp_path / "SavesA"
    game_dir.mkdir()
    save_dir.mkdir()
    (game_dir / "x.bin").write_bytes(b"12345")
    (save_dir / "s.sav").write_text("ok", encoding="utf-8")

    reg = Registry(tmp_path / "data")
    game = reg.upsert_game(
        title="Game A",
        game_folder=str(game_dir),
        save_folders=[{"label": "Saves", "path": str(save_dir)}],
    )
    result = verify_game(game)
    assert result.ok
    assert result.game_folder.size_bytes == 5


def test_api_seed_verify_and_manual_peer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PC_TRANSFER_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("PC_TRANSFER_HEADLESS", "1")
    reg = Registry(tmp_path / "data")
    app = create_app(reg)
    client = TestClient(app)

    assert client.get("/api/health").json()["ok"] is True

    seeded = client.post("/api/demo/seed").json()
    assert seeded["game"]["title"] == "Sample Quest"

    games = client.get("/api/games").json()["games"]
    assert len(games) == 1

    verified = client.get("/api/games/verify").json()["results"]
    assert verified[0]["ok"] is True

    peer = client.post(
        "/api/peers/manual",
        json={"host": "127.0.0.1", "port": 9, "name": "Nope", "device_id": "x"},
    ).json()
    assert peer["peer"]["name"] == "Nope"
    assert peer["reachable"] is False

    peers = client.get("/api/peers").json()["peers"]
    assert any(p["device_id"] == "x" for p in peers)
