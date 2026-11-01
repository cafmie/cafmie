import base64
import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from imageto3d.objects import describe_objects, find_objects, keep_objects, parse_object_ids
from imageto3d.paths import WEB_DIR
from imageto3d.pipeline import Settings, reconstruct
from imageto3d.server import app


def _two_blobs() -> np.ndarray:
    mask = np.zeros((100, 180), dtype=np.float32)
    mask[20:80, 10:50] = 1
    mask[10:90, 100:160] = 1
    return mask


def test_two_blobs_are_listed_largest_first():
    objects, labels = find_objects(_two_blobs())
    assert [item["id"] for item in objects] == [1, 2]
    assert labels[50, 130] == 1
    assert labels[50, 30] == 2
    assert objects[0]["label"] == "物体 1"
    kept = keep_objects(_two_blobs(), (2,))
    assert kept is not None
    kept_mask, used = kept
    assert used == (2,)
    assert kept_mask[50, 130] == 0
    assert kept_mask[50, 30] == 1.0


def test_specks_are_not_objects():
    mask = np.zeros((120, 120), dtype=np.float32)
    mask[10:90, 10:90] = 1
    mask[0:2, 0:2] = 1
    objects, _labels = find_objects(mask)
    assert len(objects) == 1
    described = describe_objects(mask)
    assert described["count"] == 1
    assert described["objects"] == []
    assert "label" not in described


def test_parse_object_ids():
    assert parse_object_ids("1, 3、2") == (1, 3, 2)
    assert parse_object_ids("0, x, 1, 1") == (1,)
    assert parse_object_ids("") == ()


def test_label_png_keeps_ids():
    described = describe_objects(_two_blobs())
    image = Image.open(io.BytesIO(base64.b64decode(described["label"])))
    values = set(np.asarray(image).ravel().tolist())
    assert values >= {1, 2}


def test_selected_alpha_blob_is_the_only_one_meshed(monkeypatch):
    def fake_depth(image):
        return np.ones((image.height, image.width), dtype=np.float32)

    monkeypatch.setattr("imageto3d.depth.estimate_depth", fake_depth)
    image = Image.new("RGBA", (180, 100), (0, 0, 0, 0))
    for y in range(20, 80):
        for x in range(10, 50):
            image.putpixel((x, y), (200, 40, 40, 255))
    for y in range(10, 90):
        for x in range(100, 160):
            image.putpixel((x, y), (40, 80, 200, 255))
    result = reconstruct(
        image,
        Settings(cutout=True, resolution=48, smooth=0, inflate=0.2, depth_scale=0.1, detail=0, objects=(2,)),
    )
    mask = np.asarray(result.mask_image.convert("L"))
    width = mask.shape[1]
    assert mask[:, width // 2 :].mean() < mask[:, : width // 2].mean()
    assert "物体 2" in result.notice


def test_objects_endpoint_lists_separate_shapes(monkeypatch):
    def fake_mask(image):
        mask = np.zeros((image.height, image.width), dtype=np.float32)
        mask[20:80, 10:50] = 1
        mask[10:90, 100:160] = 1
        return mask

    monkeypatch.setattr("imageto3d.segment.estimate_mask", fake_mask)
    picture = Image.new("RGB", (180, 100), (240, 236, 230))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    with TestClient(app) as client:
        response = client.post(
            "/api/objects",
            files={"image": ("two.png", buffer.getvalue(), "image/png")},
            data={"cutout": "true"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert [item["id"] for item in body["objects"]] == [1, 2]
    assert body["label"]


def test_sample_is_the_castle_photo():
    path = WEB_DIR / "sample.jpg"
    image = Image.open(path)
    assert image.format == "JPEG"
    assert image.size == (1536, 2048)
    assert not (WEB_DIR / "sample.png").exists()
