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


def test_photo_detail_adds_fine_ridges_without_contouring_smooth_shading():
    rgb, depth, mask = _disk(80)
    rgb[mask > 0.5] = (30, 30, 30)
    rgb[:, 1::4] = (240, 240, 240)
    plain = build_mesh(
        rgb, depth, mask, mode="volume", resolution=80, smooth=0, inflate=0.3, depth_scale=0.2, detail=0
    )
    fine = build_mesh(
        rgb, depth, mask, mode="volume", resolution=80, smooth=0, inflate=0.3, depth_scale=0.2, detail=1
    )
    ridges = float(np.max(np.abs(fine.vertices[:, 2] - plain.vertices[:, 2])))
    assert ridges > 0.01
    assert _sealed(fine).is_watertight

    n = 96
    y, x = np.mgrid[0:n, 0:n]
    radius = np.sqrt((x - (n - 1) / 2) ** 2 + (y - (n - 1) / 2) ** 2)
    shade = np.clip(1.0 - radius / (n * 0.42), 0.0, 1.0)
    smooth_rgb = np.clip(shade[..., None] * 180 + 40, 0, 255).astype(np.uint8)
    smooth_rgb = np.repeat(smooth_rgb, 3, axis=2)
    smooth_mask = (radius < n * 0.42).astype(np.float32)
    base = build_mesh(
        smooth_rgb, smooth_mask, smooth_mask, mode="volume", resolution=96, smooth=0, inflate=0.25, detail=0
    )
    contoured = build_mesh(
        smooth_rgb, smooth_mask, smooth_mask, mode="volume", resolution=96, smooth=0, inflate=0.25, detail=1
    )
    bands = float(np.max(np.abs(contoured.vertices[:, 2] - base.vertices[:, 2])))
    assert bands < ridges * 0.35


def test_guided_depth_gets_sharper_at_an_image_edge():
    from PIL import Image

    from imageto3d.pipeline import guide_depth

    width = 80
    soft = 1 / (1 + np.exp(-(np.linspace(-4, 4, width))))
    depth = np.tile(soft, (width, 1)).astype(np.float32)
    rgb = np.zeros((width, width, 3), dtype=np.uint8)
    rgb[:, : width // 2] = 255
    guided = guide_depth(depth, Image.fromarray(rgb))
    assert float(np.max(np.abs(np.diff(guided[width // 2])))) > float(np.max(np.abs(np.diff(depth[width // 2])))) * 1.4


def test_settings_keep_a_fine_resolution():
    from imageto3d.pipeline import Settings

    clamped = Settings(resolution=900, detail=4).clamped()
    assert clamped.resolution == 768
    assert clamped.detail == 1.5
    assert Settings().clamped().resolution == 512


def test_empty_mask_falls_back_to_a_plaque():
    rgb = np.full((30, 30, 3), 200, dtype=np.uint8)
    depth = np.linspace(0, 1, 30, dtype=np.float32)[None, :].repeat(30, axis=0)
    mask = np.zeros((30, 30), dtype=np.float32)
    mesh = build_mesh(rgb, depth, mask, mode="volume", resolution=30, smooth=0, inflate=0.2)
    assert len(mesh.faces) > 10
    buffer = io.BytesIO()
    mesh.export(buffer, file_type="glb")
    assert buffer.getvalue()[:4] == b"glTF"
