import io
import json
import struct

import numpy as np
import trimesh
from PIL import Image

from imageto3d.bundle import save_bundle
from imageto3d.mesh import build_mesh


def _disk(n=72):
    y, x = np.mgrid[0:n, 0:n]
    center = (n - 1) / 2
    radius = np.sqrt((x - center) ** 2 + (y - center) ** 2) / (n * 0.34)
    mask = (radius <= 1).astype(np.float32)
    depth = np.clip(1 - radius, 0, 1).astype(np.float32) * mask
    rgb = np.zeros((n, n, 3), dtype=np.uint8)
    rgb[..., 0] = 190
    rgb[..., 1] = 48
    rgb[..., 2] = 36
    rgb[mask < 0.5] = 240
    return rgb, depth, mask


def _sealed(mesh):
    sealed = trimesh.Trimesh(mesh.vertices.copy(), mesh.faces.copy(), process=False)
    sealed.merge_vertices()
    sealed.remove_unreferenced_vertices()
    return sealed


def test_volume_disk_is_a_closed_solid():
    rgb, depth, mask = _disk()
    mesh = build_mesh(
        rgb,
        depth,
        mask,
        mode="volume",
        resolution=72,
        depth_scale=0.45,
        inflate=0.3,
        thickness=0.05,
        smooth=0.4,
    )
    sealed = _sealed(mesh)
    assert sealed.is_watertight
    assert sealed.volume > 0
    assert len(mesh.faces) > 100
    assert mesh.visual.uv.shape == (len(mesh.vertices), 2)
    front = mesh.triangles_center[:, 2] > 0.01
    assert mesh.face_normals[front, 2].mean() > 0.2
    span = np.ptp(mesh.visual.uv[mesh.faces], axis=1)
    assert float(span.max()) < 0.25


def test_relief_has_a_flat_back_and_positive_thickness():
    rgb, depth, mask = _disk()
    mesh = build_mesh(
        rgb,
        depth,
        mask,
        mode="relief",
        resolution=64,
        depth_scale=0.3,
        inflate=0.15,
        thickness=0.08,
        smooth=0.3,
    )
    sealed = _sealed(mesh)
    assert sealed.is_watertight
    assert sealed.volume > 0
    assert mesh.vertices[:, 2].min() >= -1e-4
    assert mesh.vertices[:, 2].max() > 0.02


def test_full_frame_volume_exports_glb(tmp_path):
    rgb = np.full((40, 48, 3), 120, dtype=np.uint8)
    rgb[8:32, 10:38] = (30, 90, 160)
    depth = np.zeros((40, 48), dtype=np.float32)
    depth[8:32, 10:38] = 1
    mask = np.ones((40, 48), dtype=np.float32)
    mesh = build_mesh(rgb, depth, mask, mode="volume", resolution=48, smooth=0)
    path = tmp_path / "model.glb"
    mesh.export(path)
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    loaded = trimesh.load(path, force="mesh")
    assert len(loaded.faces) == len(mesh.faces)


def test_bundle_writes_obj_package(tmp_path):
    rgb, depth, mask = _disk(48)
    mesh = build_mesh(rgb, depth, mask, mode="relief", resolution=48, smooth=0.2, thickness=0.06)
    save_bundle(mesh, tmp_path)
    assert (tmp_path / "model.glb").stat().st_size > 1000
    assert (tmp_path / "model.stl").stat().st_size > 80
    obj = (tmp_path / "model.obj").read_text()
    assert "mtllib model.mtl" in obj
    assert "usemtl material_0" in obj
    mtl = (tmp_path / "model.mtl").read_text()
    assert "map_Kd texture.png" in mtl
    assert (tmp_path / "texture.png").is_file()
    assert (tmp_path / "model-obj.zip").is_file()
    glb = (tmp_path / "model.glb").read_bytes()
    json_length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + json_length])
    assert "NORMAL" in document["meshes"][0]["primitives"][0]["attributes"]
    with Image.open(tmp_path / "texture.png") as image:
        assert image.mode == "RGB"
        assert image.size[0] > 8


def test_empty_mask_falls_back_to_a_plaque():
    rgb = np.full((30, 30, 3), 200, dtype=np.uint8)
    depth = np.linspace(0, 1, 30, dtype=np.float32)[None, :].repeat(30, axis=0)
    mask = np.zeros((30, 30), dtype=np.float32)
    mesh = build_mesh(rgb, depth, mask, mode="volume", resolution=30, smooth=0, inflate=0.2)
    assert len(mesh.faces) > 10
    buffer = io.BytesIO()
    mesh.export(buffer, file_type="glb")
    assert buffer.getvalue()[:4] == b"glTF"
