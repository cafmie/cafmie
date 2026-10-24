"""Write GLB, STL, and an OBJ package for one mesh."""

from __future__ import annotations

import zipfile
from pathlib import Path

import trimesh


def save_bundle(mesh: trimesh.Trimesh, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    # Touching the normals caches them so the GLB is smooth-shaded.
    mesh.vertex_normals
    mesh.export(directory / "model.glb")
    geometry = trimesh.Trimesh(
        vertices=np_copy(mesh.vertices),
        faces=np_copy(mesh.faces),
        process=False,
    )
    # The rim is a separate UV island that sits on the same edge. Weld it for printing.
    geometry.merge_vertices()
    geometry.export(directory / "model.stl")
    _export_obj(mesh, directory)
    with zipfile.ZipFile(directory / "model-obj.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("model.obj", "model.mtl", "texture.png"):
            path = directory / name
            if path.is_file():
                archive.write(path, arcname=name)


def np_copy(array):
    return array.copy()


def _export_obj(mesh: trimesh.Trimesh, directory: Path) -> None:
    from trimesh.exchange import obj as obj_exchange

    exported = obj_exchange.export_obj(mesh, include_texture=True, return_texture=True)
    # trimesh returns (obj_text, texture_dict) when return_texture is set,
    # and a string otherwise. Handle both.
    if isinstance(exported, tuple):
        obj_text, textures = exported
    else:
        obj_text = exported
        textures = {}
    obj_path = directory / "model.obj"
    obj_path.write_text(_rewrite_obj(obj_text), encoding="utf-8")
    image = None
    if getattr(mesh.visual, "material", None) is not None:
        image = getattr(mesh.visual.material, "baseColorTexture", None)
    if image is None and textures:
        image = next(iter(textures.values()))
    if image is not None:
        image.convert("RGB").save(directory / "texture.png")
    mtl = "\n".join(
        [
            "newmtl material_0",
            "Ka 1.000 1.000 1.000",
            "Kd 1.000 1.000 1.000",
            "Ks 0.050 0.050 0.050",
            "Ns 16.000",
            "map_Kd texture.png",
            "",
        ]
    )
    (directory / "model.mtl").write_text(mtl, encoding="utf-8")


def _rewrite_obj(obj_text: str) -> str:
    lines = []
    wrote_mtl = False
    for line in obj_text.splitlines():
        if line.startswith("mtllib "):
            lines.append("mtllib model.mtl")
            wrote_mtl = True
            continue
        if line.startswith("usemtl "):
            lines.append("usemtl material_0")
            continue
        lines.append(line)
    if not wrote_mtl:
        lines.insert(0, "mtllib model.mtl")
    return "\n".join(lines) + "\n"
