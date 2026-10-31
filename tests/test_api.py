import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from imageto3d.pipeline import Settings, reconstruct
from imageto3d.server import app


def _png(size=(96, 120), color=(180, 40, 40)) -> bytes:
    image = Image.new("RGB", size, (245, 240, 232))
    pixels = image.load()
    cx, cy, radius = size[0] / 2, size[1] / 2, min(size) * 0.32
    for y in range(size[1]):
        for x in range(size[0]):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                pixels[x, y] = color
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_health_and_index():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        page = client.get("/")
        assert page.status_code == 200
        assert "画像から3D" in page.text
        assert 'type="module"' in page.text
        assert "model-viewer.min.js" in page.text
        assert client.get("/style.css").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/vendor/model-viewer.min.js").status_code == 200
        status = client.get("/api/status")
        body = status.json()
        assert body["ready"] is True
        assert body["gpu"] is False
        assert body["device"] is None


def test_reconstruct_endpoint_writes_a_viewable_model(monkeypatch):
    def fake_mask(image):
        width, height = image.size
        y, x = np.mgrid[0:height, 0:width]
        radius = np.sqrt((x - width / 2) ** 2 + (y - height / 2) ** 2)
        return (radius < min(width, height) * 0.32).astype(np.float32)

    def fake_depth(image):
        width, height = image.size
        y, x = np.mgrid[0:height, 0:width]
        radius = np.sqrt((x - width / 2) ** 2 + (y - height / 2) ** 2)
        return np.clip(1 - radius / (min(width, height) * 0.32), 0, 1).astype(np.float32)

    monkeypatch.setattr("imageto3d.segment.estimate_mask", fake_mask)
    monkeypatch.setattr("imageto3d.depth.estimate_depth", fake_depth)

    with TestClient(app) as client:
        response = client.post(
            "/api/reconstruct",
            files={"image": ("dot.png", _png(), "image/png")},
            data={
                "mode": "volume",
                "cutout": "true",
                "resolution": "64",
                "depth_scale": "0.4",
                "inflate": "0.25",
                "thickness": "0.08",
                "smooth": "0.4",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["vertices"] > 50
        assert body["faces"] > 50
        glb = client.get(body["glb"])
        assert glb.status_code == 200
        assert glb.content[:4] == b"glTF"
        assert client.get(body["stl"]).status_code == 200
        assert client.get(body["obj_zip"]).content[:2] == b"PK"
        assert client.get(body["depth"]).status_code == 200
        blocked = client.get("/outputs/not-an-id/../../etc/passwd")
        assert blocked.status_code == 404


def test_transparent_png_skips_the_cutout_network(monkeypatch):
    def fail_mask(image):
        raise AssertionError("alpha images should not call the cutout model")

    def fake_depth(image):
        return np.ones((image.height, image.width), dtype=np.float32)

    monkeypatch.setattr("imageto3d.segment.estimate_mask", fail_mask)
    monkeypatch.setattr("imageto3d.depth.estimate_depth", fake_depth)

    image = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    for y in range(12, 36):
        for x in range(12, 36):
            image.putpixel((x, y), (20, 80, 140, 255))
    result = reconstruct(
        image,
        Settings(cutout=True, resolution=40, smooth=0, inflate=0.2, depth_scale=0.2),
    )
    assert result.vertices > 20
    assert result.notice == ""


def test_rejects_a_non_image():
    with TestClient(app) as client:
        response = client.post(
            "/api/reconstruct",
            files={"image": ("notes.txt", b"hello", "text/plain")},
            data={"mode": "volume", "cutout": "false"},
        )
        assert response.status_code == 400
