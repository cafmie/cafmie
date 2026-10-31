"""Local web app for image-to-3D conversion."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .bundle import save_bundle
from .download import ensure_models, models_present
from .paths import WEB_DIR, output_dir
from .pipeline import Settings, open_image, reconstruct

logger = logging.getLogger("imageto3d")

_ID = re.compile(r"^[a-f0-9]{32}$")
_FILE = re.compile(r"^(model\.(glb|stl|obj|mtl)|model-obj\.zip|texture\.png|depth\.png|mask\.png)$")

_state_lock = threading.Lock()
_state = {"state": "checking", "message": "", "ready": False, "device": None}


def _set_state(state: str, message: str = "", device=None) -> None:
    with _state_lock:
        _state["state"] = state
        _state["message"] = message
        _state["ready"] = state == "ready"
        if state == "ready":
            _state["device"] = device
        elif state == "error":
            _state["device"] = None


def _snapshot() -> dict:
    with _state_lock:
        device = _state["device"]
        ready_label = "このPCの中で処理できます"
        if device is not None:
            ready_label = "GPUで処理します" if device.gpu else "CPUで処理します"
        labels = {
            "checking": "状態を確認しています",
            "downloading": "初回のモデルをダウンロードしています",
            "loading": "モデルを読み込んでいます",
            "ready": ready_label,
            "error": "モデルの準備に失敗しました",
        }
        return {
            "state": _state["state"],
            "ready": _state["ready"],
            "message": _state["message"],
            "label": labels.get(_state["state"], _state["state"]),
            "device": None if device is None else device.provider,
            "gpu": bool(device and device.gpu),
        }


def prepare_models() -> None:
    if os.environ.get("IMAGETO3D_SKIP_MODELS") == "1":
        _set_state("ready", "テストモード")
        return
    try:
        _set_state("downloading" if not models_present() else "loading")
        ensure_models()
        _set_state("loading")
        from . import depth, segment

        segment.get_session()
        depth.get_session()
        from .device import current

        device = current()
        _set_state("ready", device=device)
        logger.info("models ready on %s", device.label if device else "unknown")
    except Exception as error:
        logger.exception("model preparation failed")
        _set_state("error", str(error))


def _sweep_old_outputs() -> None:
    root = output_dir()
    cutoff = time.time() - 24 * 60 * 60
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                for item in child.iterdir():
                    item.unlink(missing_ok=True)
                child.rmdir()
        except OSError:
            logger.warning("could not remove old output %s", child)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _sweep_old_outputs()
        if os.environ.get("IMAGETO3D_SKIP_MODELS") == "1":
            _set_state("ready", "テストモード")
        else:
            threading.Thread(target=prepare_models, name="imageto3d-models", daemon=True).start()
        yield

    app = FastAPI(title="画像から3D", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/install")
    def install_status() -> dict:
        from .installer import status

        return status()

    @app.post("/api/install")
    def install_now() -> dict:
        from .installer import install

        try:
            return install()
        except RuntimeError as error:
            raise HTTPException(500, str(error)) from error

    @app.get("/api/status")
    def status() -> dict:
        return _snapshot()

    @app.post("/api/models/retry")
    def retry_models() -> dict:
        if _snapshot()["state"] == "downloading":
            return _snapshot()
        threading.Thread(target=prepare_models, name="imageto3d-models-retry", daemon=True).start()
        return _snapshot()

    @app.post("/api/reconstruct")
    async def reconstruct_endpoint(
        image: UploadFile = File(...),
        mode: str = Form("volume"),
        cutout: str = Form("true"),
        resolution: int = Form(220),
        depth_scale: float = Form(0.22),
        inflate: float = Form(0.46),
        thickness: float = Form(0.08),
        smooth: float = Form(1.0),
    ) -> JSONResponse:
        snapshot = _snapshot()
        if not snapshot["ready"]:
            detail = snapshot["message"] or snapshot["label"]
            raise HTTPException(503, detail)
        payload = await image.read()
        if len(payload) > 20 * 1024 * 1024:
            raise HTTPException(413, "画像は20MBまでです")
        if not payload:
            raise HTTPException(400, "画像が空です")
        try:
            picture = open_image(payload)
            settings = Settings(
                mode=mode,
                cutout=_as_bool(cutout),
                resolution=resolution,
                depth_scale=depth_scale,
                inflate=inflate,
                thickness=thickness,
                smooth=smooth,
            ).clamped()
            result = reconstruct(picture, settings, on_status=lambda note: logger.info(note))
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except Exception as error:
            logger.exception("reconstruct failed")
            raise HTTPException(500, f"変換に失敗しました: {error}") from error

        import uuid

        job = uuid.uuid4().hex
        directory = output_dir() / job
        save_bundle(result.mesh, directory)
        result.depth_image.save(directory / "depth.png")
        result.mask_image.save(directory / "mask.png")
        return JSONResponse(
            {
                "id": job,
                "mode": result.mode,
                "vertices": result.vertices,
                "faces": result.faces,
                "elapsed_s": round(result.elapsed_s, 2),
                "notice": result.notice,
                "glb": f"/outputs/{job}/model.glb",
                "stl": f"/outputs/{job}/model.stl",
                "obj_zip": f"/outputs/{job}/model-obj.zip",
                "depth": f"/outputs/{job}/depth.png",
                "mask": f"/outputs/{job}/mask.png",
            }
        )

    @app.get("/outputs/{job}/{name}")
    def output_file(job: str, name: str) -> FileResponse:
        if not _ID.fullmatch(job) or not _FILE.fullmatch(name):
            raise HTTPException(404)
        path = output_dir() / job / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
    return app


def _as_bool(value: str) -> bool:
    return str(value).lower() in {"1", "true", "on", "yes"}


app = create_app()
