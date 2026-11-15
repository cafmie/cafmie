"""HTTP-backed game ZIP and save sync between peers."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from .archive import unzip_to, zip_folder
from .models import GameProfile, TransferKind, TransferProgress, utc_now
from .saves import sync_saves


ProgressCb = Optional[Callable[[TransferProgress], None]]


class TransferHub:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, TransferProgress] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Optional[TransferProgress]:
        with self._lock:
            return self._jobs.get(job_id)

    def _set(self, progress: TransferProgress) -> None:
        with self._lock:
            self._jobs[progress.job_id] = progress

    def start_send_game(
        self,
        game: GameProfile,
        peer_base_url: str,
        on_progress: ProgressCb = None,
    ) -> str:
        job_id = uuid4().hex[:10]
        progress = TransferProgress(
            job_id=job_id,
            kind=TransferKind.GAME_ZIP,
            stage="queued",
            message="Queued game ZIP send",
        )
        self._set(progress)

        def run() -> None:
            try:
                self._send_game(job_id, game, peer_base_url, on_progress)
            except Exception as exc:  # noqa: BLE001 — surface to UI
                done = TransferProgress(
                    job_id=job_id,
                    kind=TransferKind.GAME_ZIP,
                    stage="error",
                    percent=100.0,
                    message=str(exc),
                    done=True,
                    error=str(exc),
                )
                self._set(done)
                if on_progress:
                    on_progress(done)

        threading.Thread(target=run, name=f"send-game-{job_id}", daemon=True).start()
        return job_id

    def start_send_saves(
        self,
        game: GameProfile,
        peer_base_url: str,
        policy: str = "newer_wins",
        on_progress: ProgressCb = None,
    ) -> str:
        job_id = uuid4().hex[:10]
        progress = TransferProgress(
            job_id=job_id,
            kind=TransferKind.SAVE_SYNC,
            stage="queued",
            message="Queued save sync",
        )
        self._set(progress)

        def run() -> None:
            try:
                self._send_saves(job_id, game, peer_base_url, policy, on_progress)
            except Exception as exc:  # noqa: BLE001
                done = TransferProgress(
                    job_id=job_id,
                    kind=TransferKind.SAVE_SYNC,
                    stage="error",
                    percent=100.0,
                    message=str(exc),
                    done=True,
                    error=str(exc),
                )
                self._set(done)
                if on_progress:
                    on_progress(done)

        threading.Thread(target=run, name=f"send-saves-{job_id}", daemon=True).start()
        return job_id

    def _emit(self, job_id: str, kind: TransferKind, stage: str, percent: float, message: str, on_progress: ProgressCb, done: bool = False, error: Optional[str] = None) -> None:
        progress = TransferProgress(
            job_id=job_id,
            kind=kind,
            stage=stage,
            percent=percent,
            message=message,
            done=done,
            error=error,
        )
        self._set(progress)
        if on_progress:
            on_progress(progress)

    def _send_game(self, job_id: str, game: GameProfile, peer_base_url: str, on_progress: ProgressCb) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="pc-transfer-game-", dir=self.work_dir))
        try:
            zip_path = tmp / f"{game.id}.zip"

            def pack_cb(pct: float, msg: str) -> None:
                self._emit(job_id, TransferKind.GAME_ZIP, "packing", pct * 0.5, msg, on_progress)

            zip_folder(Path(game.game_folder), zip_path, progress=pack_cb)
            self._emit(job_id, TransferKind.GAME_ZIP, "uploading", 55.0, "Uploading archive to peer", on_progress)

            meta = {
                "game": game.model_dump(mode="json"),
                "sent_at": utc_now().isoformat(),
            }
            boundary = f"----pcTransfer{uuid4().hex}"
            body = self._multipart(
                boundary,
                fields={"meta": json.dumps(meta)},
                files={"archive": (zip_path.name, zip_path.read_bytes(), "application/zip")},
            )
            req = urllib.request.Request(
                f"{peer_base_url.rstrip('/')}/api/transfer/receive-game",
                data=body,
                method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                resp.read()
            self._emit(job_id, TransferKind.GAME_ZIP, "done", 100.0, "Game transfer complete", on_progress, done=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _send_saves(self, job_id: str, game: GameProfile, peer_base_url: str, policy: str, on_progress: ProgressCb) -> None:
        if not game.save_folders:
            self._emit(job_id, TransferKind.SAVE_SYNC, "done", 100.0, "No save folders registered", on_progress, done=True)
            return

        tmp = Path(tempfile.mkdtemp(prefix="pc-transfer-saves-", dir=self.work_dir))
        try:
            bundle = tmp / "saves_bundle"
            bundle.mkdir()
            total = len(game.save_folders)
            for idx, save in enumerate(game.save_folders):
                src = Path(save.path)
                if not src.exists():
                    continue
                dest = bundle / save.id
                shutil.copytree(src, dest, dirs_exist_ok=True)
                self._emit(
                    job_id,
                    TransferKind.SAVE_SYNC,
                    "packing",
                    (idx + 1) / total * 40.0,
                    f"Packed save folder {save.label}",
                    on_progress,
                )

            zip_path = tmp / f"{game.id}-saves.zip"

            def pack_cb(pct: float, msg: str) -> None:
                self._emit(job_id, TransferKind.SAVE_SYNC, "packing", 40.0 + pct * 0.2, msg, on_progress)

            zip_folder(bundle, zip_path, progress=pack_cb)
            self._emit(job_id, TransferKind.SAVE_SYNC, "uploading", 65.0, "Uploading saves to peer", on_progress)

            meta = {
                "game": game.model_dump(mode="json"),
                "policy": policy,
                "sent_at": utc_now().isoformat(),
            }
            boundary = f"----pcTransfer{uuid4().hex}"
            body = self._multipart(
                boundary,
                fields={"meta": json.dumps(meta)},
                files={"archive": (zip_path.name, zip_path.read_bytes(), "application/zip")},
            )
            req = urllib.request.Request(
                f"{peer_base_url.rstrip('/')}/api/transfer/receive-saves",
                data=body,
                method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                resp.read()
            self._emit(job_id, TransferKind.SAVE_SYNC, "done", 100.0, "Save sync complete", on_progress, done=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _multipart(boundary: str, fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> bytes:
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            chunks.append(value.encode("utf-8"))
            chunks.append(b"\r\n")
        for name, (filename, content, content_type) in files.items():
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
            )
            chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
            chunks.append(content)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        return b"".join(chunks)


def receive_game_archive(
    archive_bytes: bytes,
    game: GameProfile,
    dest_root: Path,
    work_dir: Path,
) -> Path:
    """Extract received game ZIP into dest_root / title (or registered folder if set)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / f"recv-{game.id}.zip"
    zip_path.write_bytes(archive_bytes)

    # Prefer the registered local game folder if it already exists; else create under dest_root
    target = Path(game.game_folder).expanduser()
    if not target.exists():
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in game.title).strip() or game.id
        target = dest_root / safe_title
    target.mkdir(parents=True, exist_ok=True)
    unzip_to(zip_path, target)
    zip_path.unlink(missing_ok=True)
    return target


def receive_saves_archive(
    archive_bytes: bytes,
    game: GameProfile,
    policy: str,
    work_dir: Path,
) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / f"recv-saves-{game.id}.zip"
    extract_dir = work_dir / f"recv-saves-{game.id}"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    zip_path.write_bytes(archive_bytes)
    unzip_to(zip_path, extract_dir)
    zip_path.unlink(missing_ok=True)

    results = []
    for save in game.save_folders:
        incoming = extract_dir / save.id
        if not incoming.exists():
            results.append({"label": save.label, "copied": 0, "decisions": []})
            continue
        local = Path(save.path).expanduser()
        decisions, copied = sync_saves(incoming, local, policy=policy)
        results.append(
            {
                "label": save.label,
                "path": str(local),
                "copied": copied,
                "decisions": [d.model_dump(mode="json") for d in decisions],
            }
        )
    shutil.rmtree(extract_dir, ignore_errors=True)
    return {"results": results}


def peer_reachable(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/health", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
