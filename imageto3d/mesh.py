"""Build a textured triangle mesh from a depth map and a foreground mask.

The front carries the photograph's depth. The back is a smooth shell from the
silhouette, so the unseen side stays a solid form instead of a mirrored face.
Relief mode lays the same surface on a flat base for printing.
"""

from __future__ import annotations

import numpy as np
import trimesh
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter

from .preview import extend_colors


def build_mesh(
    image: Image.Image | np.ndarray,
    depth: np.ndarray,
    mask: np.ndarray,
    *,
    mode: str = "volume",
    resolution: int = 220,
    depth_scale: float = 0.55,
    inflate: float = 0.32,
    thickness: float = 0.08,
    smooth: float = 1.0,
) -> trimesh.Trimesh:
    if mode not in {"volume", "relief"}:
        raise ValueError("mode は volume か relief です")

    depth_s, mask_s = _resize_fields(depth, mask, int(resolution))
    height, width = mask_s.shape
    sigma = float(max(smooth, 0.0))
    hard = mask_s > 0.5
    if hard.any():
        filled = depth_s.copy()
        filled[~hard] = np.median(depth_s[hard])
    else:
        filled = depth_s
    if sigma > 0:
        depth_s = gaussian_filter(filled, sigma=sigma)
        mask_s = gaussian_filter(mask_s, sigma=sigma)
    else:
        depth_s = filled

    valid = mask_s > 0.45
    if int(valid.sum()) < 16:
        valid = np.ones((height, width), dtype=bool)
        valid[0, :] = valid[-1, :] = False
        valid[:, 0] = valid[:, -1] = False

    depth_n = _normalize(depth_s, valid)
    distance = distance_transform_edt(valid).astype(np.float32)
    distance_n = distance / max(float(distance.max()), 1e-6)
    # Distance-from-edge is a cone. Turn it into a dome so the shell reads as a solid.
    dome = np.sqrt(np.clip(distance_n * (2.0 - distance_n), 0.0, 1.0)).astype(np.float32)
    relief = dome * float(inflate) + depth_n * dome * float(depth_scale)
    boundary = _boundary(valid)
    # Sliders are fractions of the subject, so a small object in a large frame
    # does not get stretched toward the camera.
    subject = _subject_size(valid)
    relief = relief * subject

    if mode == "volume":
        front_height = relief
        back_height = -(dome * float(inflate) * 0.92) * subject
        # The silhouette is where front and back meet. A hair of thickness keeps
        # the side wall from collapsing into a hole.
        rim = np.float32(max(0.002, 0.012 * subject))
        front_height = np.where(boundary, np.maximum(front_height, rim), front_height)
        back_height = np.where(boundary, np.minimum(back_height, -rim), back_height)
    else:
        base = max(float(thickness), 0.005)
        front_height = base * subject + relief
        back_height = np.zeros_like(relief)
    texture = _texture(image, mask)
    return _solid(texture, valid, boundary, front_height, back_height)


def _resize_fields(depth: np.ndarray, mask: np.ndarray, resolution: int) -> tuple[np.ndarray, np.ndarray]:
    source_h, source_w = depth.shape[:2]
    long_side = max(source_h, source_w, 1)
    scale = max(int(resolution), 8) / long_side
    width = max(8, int(round(source_w * scale)))
    height = max(8, int(round(source_h * scale)))
    return _resize_float(depth, width, height), _resize_float(mask, width, height)


def _resize_float(array: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(np.asarray(array, dtype=np.float32), mode="F")
    return np.asarray(image.resize((width, height), Image.Resampling.BILINEAR), dtype=np.float32)


def _normalize(depth: np.ndarray, valid: np.ndarray) -> np.ndarray:
    values = depth[valid]
    low, high = np.percentile(values, [3, 97])
    if float(high - low) < 1e-6:
        return np.zeros_like(depth, dtype=np.float32)
    return np.clip((depth - low) / (high - low), 0.0, 1.0).astype(np.float32)


def _texture(image: Image.Image | np.ndarray, mask: np.ndarray, limit: int = 1024) -> Image.Image:
    """High-resolution texture with a solid-color strip for the unseen back."""

    if isinstance(image, Image.Image):
        rgb = np.asarray(image.convert("RGB"))
    else:
        rgb = np.asarray(image)
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        rgb = rgb[:, :, :3].astype(np.uint8)
    height, width = rgb.shape[:2]
    scale = min(1.0, limit / max(height, width, 1))
    if scale < 1.0:
        sized = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        rgb = np.asarray(Image.fromarray(rgb).resize(sized, Image.Resampling.LANCZOS))
        mask_r = _resize_float(mask, sized[0], sized[1])
    else:
        mask_r = np.asarray(mask, dtype=np.float32)
        if mask_r.shape[:2] != rgb.shape[:2]:
            mask_r = _resize_float(mask, width, height)
    covered = mask_r > 0.4
    if not covered.any():
        covered = np.ones(rgb.shape[:2], dtype=bool)
    painted = extend_colors(rgb, covered)
    clay = np.median(painted[covered], axis=0).astype(np.uint8)
    bar = np.tile(clay, (8, painted.shape[1], 1))
    return Image.fromarray(np.vstack([painted, bar]))


def _subject_size(valid: np.ndarray) -> float:
    height, width = valid.shape
    ys, xs = np.nonzero(valid)
    if len(xs) == 0:
        return 1.0
    long_side = float(max(height, width))
    span_x = float(xs.max() - xs.min()) / max(width - 1, 1) * (width / long_side)
    span_y = float(ys.max() - ys.min()) / max(height - 1, 1) * (height / long_side)
    return max(span_x, span_y, 0.05)


def _boundary(valid: np.ndarray) -> np.ndarray:
    padded = np.pad(valid, 1, constant_values=False)
    neighbors = (
        padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )
    return valid & ~neighbors


def _solid(
    texture: Image.Image,
    valid: np.ndarray,
    boundary: np.ndarray,
    front_height: np.ndarray,
    back_height: np.ndarray,
) -> trimesh.Trimesh:
    height, width = valid.shape
    long_side = float(max(height, width))
    photo_rows = texture.size[1] - 8
    total_rows = texture.size[1]
    v_bottom = 1.0 - (photo_rows - 1) / max(total_rows - 1, 1)
    v_back = 1.0 - (photo_rows + 3) / max(total_rows - 1, 1)
    ys, xs = np.nonzero(valid)
    front_id = -np.ones((height, width), dtype=np.int32)
    back_id = -np.ones((height, width), dtype=np.int32)
    vertices: list[list[float]] = []
    uvs: list[list[float]] = []

    for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
        position = [
            (x / max(width - 1, 1) - 0.5) * (width / long_side),
            (0.5 - y / max(height - 1, 1)) * (height / long_side),
        ]
        span = 1.0 - y / max(height - 1, 1)
        front_uv = [x / max(width - 1, 1), v_bottom + span * (1.0 - v_bottom)]
        front_id[y, x] = len(vertices)
        vertices.append([position[0], position[1], float(front_height[y, x])])
        uvs.append(front_uv)
        back_id[y, x] = len(vertices)
        vertices.append([position[0], position[1], float(back_height[y, x])])
        uvs.append([0.5, v_back])

    points = np.asarray(vertices, dtype=np.float32)
    texcoord = np.asarray(uvs, dtype=np.float32)
    front_faces = _quads(front_id)
    back_faces = _quads(back_id, reverse=True)
    faces = [front_faces, back_faces]
    if len(front_faces):
        faces.append(_walls(points, front_faces, _front_to_back(front_id, back_id, len(points))))
    stacked = [part for part in faces if len(part)]
    if not stacked:
        raise RuntimeError("メッシュを組めませんでした。被写体が小さすぎます。")
    face_array = np.vstack(stacked).astype(np.int32)

    seam = np.unique(front_id[boundary])
    seam = seam[seam >= 0]
    points = _smooth_seam(points, face_array, seam, rounds=14)
    paired = _front_to_back(front_id, back_id, len(points))
    for front_index in seam.tolist():
        back_index = int(paired[int(front_index)])
        if back_index >= 0:
            points[back_index, 0] = points[int(front_index), 0]
            points[back_index, 1] = points[int(front_index), 1]

    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=texture,
        metallicFactor=0.0,
        roughnessFactor=0.84,
        doubleSided=True,
    )
    visual = trimesh.visual.TextureVisuals(uv=texcoord, material=material)
    mesh = trimesh.Trimesh(vertices=points, faces=face_array, visual=visual, process=False)
    # Drop faces that repeat a vertex. Keep tiny slivers: deleting them opens the rim.
    degenerate = mesh.faces[:, 0] == mesh.faces[:, 1]
    degenerate |= mesh.faces[:, 1] == mesh.faces[:, 2]
    degenerate |= mesh.faces[:, 0] == mesh.faces[:, 2]
    if degenerate.any():
        mesh.update_faces(~degenerate)
        mesh.remove_unreferenced_vertices()
    _orient_outward(mesh)
    return mesh


def _quads(
    ids: np.ndarray,
    *,
    reverse: bool = False,
    skip_when_same_as: np.ndarray | None = None,
) -> np.ndarray:
    id00 = ids[:-1, :-1]
    id10 = ids[:-1, 1:]
    id01 = ids[1:, :-1]
    id11 = ids[1:, 1:]
    ok = (id00 >= 0) & (id10 >= 0) & (id01 >= 0) & (id11 >= 0)
    if skip_when_same_as is not None:
        same00 = skip_when_same_as[:-1, :-1]
        same10 = skip_when_same_as[:-1, 1:]
        same01 = skip_when_same_as[1:, :-1]
        same11 = skip_when_same_as[1:, 1:]
        identical = (id00 == same00) & (id10 == same10) & (id01 == same01) & (id11 == same11)
        ok = ok & ~identical
    if not np.any(ok):
        return np.zeros((0, 3), dtype=np.int32)
    if reverse:
        first = np.stack([id00[ok], id10[ok], id11[ok]], axis=1)
        second = np.stack([id00[ok], id11[ok], id01[ok]], axis=1)
    else:
        first = np.stack([id00[ok], id01[ok], id11[ok]], axis=1)
        second = np.stack([id00[ok], id11[ok], id10[ok]], axis=1)
    return np.vstack([first, second]).astype(np.int32)


def _front_to_back(front_id: np.ndarray, back_id: np.ndarray, count: int) -> np.ndarray:
    mapping = np.full(count, -1, dtype=np.int32)
    valid = front_id >= 0
    mapping[front_id[valid]] = back_id[valid]
    return mapping


def _walls(points: np.ndarray, front_faces: np.ndarray, front_to_back: np.ndarray) -> np.ndarray:
    edges = _directed_boundary(front_faces)
    if len(edges) == 0:
        return np.zeros((0, 3), dtype=np.int32)
    center = points.mean(axis=0)
    faces: list[tuple[int, int, int]] = []
    for start, end in edges.tolist():
        back_start = int(front_to_back[start])
        back_end = int(front_to_back[end])
        if back_start < 0 or back_end < 0:
            continue
        for tri in ((start, end, back_end), (start, back_end, back_start)):
            normal = np.cross(points[tri[1]] - points[tri[0]], points[tri[2]] - points[tri[0]])
            midpoint = (points[tri[0]] + points[tri[1]] + points[tri[2]]) / 3.0
            if float(np.dot(normal, midpoint - center)) < 0.0:
                tri = (tri[0], tri[2], tri[1])
            faces.append(tri)
    if not faces:
        return np.zeros((0, 3), dtype=np.int32)
    return np.asarray(faces, dtype=np.int32)


def _directed_boundary(faces: np.ndarray) -> np.ndarray:
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]).astype(np.int64)
    undirected = np.sort(edges, axis=1)
    order = np.lexsort((undirected[:, 1], undirected[:, 0]))
    undirected = undirected[order]
    edges = edges[order]
    if len(edges) == 1:
        return edges.astype(np.int32)
    change = np.any(undirected[1:] != undirected[:-1], axis=1)
    starts = np.concatenate([[0], np.flatnonzero(change) + 1])
    ends = np.concatenate([starts[1:], [len(edges)]])
    single = (ends - starts) == 1
    return edges[starts[single]].astype(np.int32)


def _smooth_seam(points: np.ndarray, faces: np.ndarray, seam_ids: np.ndarray, rounds: int = 3) -> np.ndarray:
    seam_ids = np.asarray(seam_ids, dtype=np.int64)
    seam_ids = seam_ids[(seam_ids >= 0) & (seam_ids < len(points))]
    if len(seam_ids) < 3 or len(faces) == 0:
        return points
    seam_set = set(seam_ids.tolist())
    neighbors: dict[int, set[int]] = {int(index): set() for index in seam_ids.tolist()}
    for a, b, c in faces.tolist():
        for start, end in ((a, b), (b, c), (c, a)):
            if start in seam_set and end in seam_set:
                neighbors[start].add(end)
                neighbors[end].add(start)
    updated = points.copy()
    for _ in range(rounds):
        nxt = updated.copy()
        for index, adjacent in neighbors.items():
            if not adjacent:
                continue
            average = updated[list(adjacent), :2].mean(axis=0)
            nxt[index, 0] = updated[index, 0] * 0.55 + average[0] * 0.45
            nxt[index, 1] = updated[index, 1] * 0.55 + average[1] * 0.45
        updated = nxt
    return updated


def _orient_outward(mesh: trimesh.Trimesh) -> None:
    if not mesh.is_watertight or mesh.volume >= 0:
        return
    mesh.invert()
