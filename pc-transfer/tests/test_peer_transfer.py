from __future__ import annotations

import threading
import time
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from pc_transfer.registry import Registry
from pc_transfer.server import create_app


def _run_server(app, host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # wait until listening
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.05)
    return server


def test_game_and_save_transfer_between_peers(tmp_path: Path, monkeypatch) -> None:
    main_data = tmp_path / "main"
    hand_data = tmp_path / "hand"
    main_data.mkdir()
    hand_data.mkdir()

    # Source game on main
    game_dir = tmp_path / "MainGame"
    save_dir = tmp_path / "MainSaves"
    game_dir.mkdir()
    save_dir.mkdir()
    (game_dir / "play.exe").write_bytes(b"GAMEBYTES")
    (save_dir / "slot.sav").write_text("progress=1", encoding="utf-8")

    monkeypatch.setenv("PC_TRANSFER_HEADLESS", "1")

    main_reg = Registry(main_data)
    main_reg.update_settings(device_name="Main", role="main", http_port=18787, discovery_port=18788)
    main_game = main_reg.upsert_game(
        title="Peer Quest",
        game_folder=str(game_dir),
        save_folders=[{"label": "Saves", "path": str(save_dir)}],
    )
    main_app = create_app(main_reg)

    # Handheld registers empty destinations with same game id for saves
    hand_game_dir = tmp_path / "HandGame"
    hand_save_dir = tmp_path / "HandSaves"
    hand_game_dir.mkdir()
    hand_save_dir.mkdir()
    (hand_save_dir / "slot.sav").write_text("progress=0", encoding="utf-8")
    import os

    older = time.time() - 200
    os.utime(hand_save_dir / "slot.sav", (older, older))

    hand_reg = Registry(hand_data)
    hand_reg.update_settings(device_name="Handheld", role="handheld", http_port=18797, discovery_port=18798)
    hand_reg.upsert_game(
        title="Peer Quest",
        game_folder=str(hand_game_dir),
        save_folders=[{"id": main_game.save_folders[0].id, "label": "Saves", "path": str(hand_save_dir)}],
        game_id=main_game.id,
    )
    hand_app = create_app(hand_reg)

    main_server = _run_server(main_app, "127.0.0.1", 18787)
    hand_server = _run_server(hand_app, "127.0.0.1", 18797)
    try:
        client = TestClient(main_app)
        # Send game ZIP main -> handheld
        job = client.post(
            "/api/transfer/send-game",
            json={
                "game_id": main_game.id,
                "peer_host": "127.0.0.1",
                "peer_port": 18797,
            },
        ).json()
        job_id = job["job_id"]
        for _ in range(100):
            status = client.get(f"/api/transfer/jobs/{job_id}").json()
            if status["done"]:
                break
            time.sleep(0.05)
        assert status["done"] and not status.get("error"), status
        assert (hand_game_dir / "play.exe").exists() or any(hand_data.joinpath("received_games").rglob("play.exe"))

        # Sync saves main -> handheld (remote newer should overwrite)
        job2 = client.post(
            "/api/transfer/send-saves",
            json={
                "game_id": main_game.id,
                "peer_host": "127.0.0.1",
                "peer_port": 18797,
                "policy": "newer_wins",
            },
        ).json()
        job2_id = job2["job_id"]
        for _ in range(100):
            status2 = client.get(f"/api/transfer/jobs/{job2_id}").json()
            if status2["done"]:
                break
            time.sleep(0.05)
        assert status2["done"] and not status2.get("error"), status2
        assert (hand_save_dir / "slot.sav").read_text(encoding="utf-8") == "progress=1"
    finally:
        main_server.should_exit = True
        hand_server.should_exit = True
