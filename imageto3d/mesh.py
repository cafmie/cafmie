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
        rim = np.float32(max(0.0015, 0.004 * subject))
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
    # Low-pass the outline before the side wall is cut, so the rim follows one curve.
    points = _smooth_outline(points, front_faces, radius=8)
    points = _smooth_outline(points, front_faces, radius=8)
    front_to_back = _front_to_back(front_id, back_id, len(points))
    grid_count = len(points)
    wall_faces, points, texcoord, wall_normals = _walls(
        points, texcoord, front_faces, front_to_back, v_back
    )
    parts = [front_faces, back_faces, wall_faces]
    stacked = [part for part in parts if len(part)]
    if not stacked:
        raise RuntimeError("メッシュを組めませんでした。被写体が小さすぎます。")
    face_array = np.vstack(stacked).astype(np.int32)
    normals = _vertex_normals(valid, front_id, back_id, front_height, back_height, grid_count)
    if len(wall_normals):
        normals = np.vstack([normals, wall_normals])

    # Drop faces that repeat a vertex. Keep tiny slivers: deleting them opens the rim.
    degenerate = face_array[:, 0] == face_array[:, 1]
    degenerate |= face_array[:, 1] == face_array[:, 2]
    degenerate |= face_array[:, 0] == face_array[:, 2]
    if degenerate.any():
        face_array = face_array[~degenerate]
        used = np.zeros(len(points), dtype=bool)
        used[face_array] = True
        remap = np.full(len(points), -1, dtype=np.int32)
        remap[used] = np.arange(int(used.sum()), dtype=np.int32)
        points = points[used]
        texcoord = texcoord[used]
        normals = normals[used]
        face_array = remap[face_array]

    if _volume_is_negative(points, face_array):
        face_array = face_array[:, ::-1]
        normals = -normals

    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=texture,
        metallicFactor=0.0,
        roughnessFactor=0.84,
        doubleSided=True,
    )
    visual = trimesh.visual.TextureVisuals(uv=texcoord, material=material)
    mesh = trimesh.Trimesh(vertices=points, faces=face_array, visual=visual, process=False)
    mesh.vertex_normals = normals
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


def _walls(
    points: np.ndarray,
    texcoord: np.ndarray,
    front_faces: np.ndarray,
    front_to_back: np.ndarray,
    v_back: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Stitch the rim with its own vertices so the side stays a solid color.

    Sharing the front vertices would stretch the photograph across the wall,
    which draws a bright jagged seam along the silhouette.
    """

    empty_faces = np.zeros((0, 3), dtype=np.int32)
    empty_normals = np.zeros((0, 3), dtype=np.float32)
    edges = _directed_boundary(front_faces)
    if len(edges) == 0:
        return empty_faces, points, texcoord, empty_normals
    center = points[::2].mean(axis=0)
    clone: dict[int, int] = {}
    extra_points: list[list[float]] = []
    extra_uv: list[list[float]] = []
    extra_normals: list[list[float]] = []

    def rim(vertex: int) -> int:
        cached = clone.get(vertex)
        if cached is not None:
            return cached
        outward = points[vertex, :2] - center[:2]
        length = float(np.linalg.norm(outward))
        if length < 1e-8:
            outward = np.array([0.0, 1.0], dtype=np.float32)
        else:
            outward = outward / length
        normal = np.array([outward[0], outward[1], 0.18], dtype=np.float32)
        normal /= float(np.linalg.norm(normal))
        clone[vertex] = len(points) + len(extra_points)
        extra_points.append(points[vertex].tolist())
        extra_uv.append([0.5, v_back])
        extra_normals.append(normal.tolist())
        return clone[vertex]

    faces: list[tuple[int, int, int]] = []
    for start, end in edges.tolist():
        back_start = int(front_to_back[start])
        back_end = int(front_to_back[end])
        if back_start < 0 or back_end < 0:
            continue
        rim_start = rim(int(start))
        rim_end = rim(int(end))
        for tri in ((rim_start, rim_end, back_end), (rim_start, back_end, back_start)):
            corners = [points[start] if index == rim_start else points[end] if index == rim_end else points[index] for index in tri]
            normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
            midpoint = (corners[0] + corners[1] + corners[2]) / 3.0
            if float(np.dot(normal, midpoint - center)) < 0.0:
                tri = (tri[0], tri[2], tri[1])
            faces.append(tri)
    if not faces:
        return empty_faces, points, texcoord, empty_normals
    points = np.vstack([points, np.asarray(extra_points, dtype=np.float32)])
    texcoord = np.vstack([texcoord, np.asarray(extra_uv, dtype=np.float32)])
    return (
        np.asarray(faces, dtype=np.int32),
        points,
        texcoord,
        np.asarray(extra_normals, dtype=np.float32),
    )


def _vertex_normals(
    valid: np.ndarray,
    front_id: np.ndarray,
    back_id: np.ndarray,
    front_height: np.ndarray,
    back_height: np.ndarray,
    count: int,
) -> np.ndarray:
    """Normals from the height field, so grid triangles do not stripe the light."""

    normals = np.zeros((count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    front = _height_normals(_filled(front_height, valid), facing=1.0)
    back = _height_normals(_filled(back_height, valid), facing=-1.0)
    known = front_id >= 0
    normals[front_id[known]] = front[known]
    normals[back_id[known]] = back[known]
    return normals


def _filled(height: np.ndarray, valid: np.ndarray) -> np.ndarray:
    filled = height.astype(np.float64, copy=True)
    if valid.all() or not valid.any():
        return filled
    _, (near_y, near_x) = distance_transform_edt(~valid, return_indices=True)
    missing = ~valid
    filled[missing] = filled[near_y[missing], near_x[missing]]
    return filled


def _height_normals(height: np.ndarray, *, facing: float) -> np.ndarray:
    rows, cols = height.shape
    long_side = float(max(rows, cols))
    dx = (cols / long_side) / max(cols - 1, 1)
    dy = (rows / long_side) / max(rows - 1, 1)
    gradient_y, gradient_x = np.gradient(height)
    dzdx = gradient_x / dx
    dzdy = -gradient_y / dy
    if facing > 0:
        normals = np.stack([-dzdx, -dzdy, np.ones_like(dzdx)], axis=-1)
    else:
        normals = np.stack([dzdx, dzdy, -np.ones_like(dzdx)], axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True) + 1e-12
    return normals.astype(np.float32)


def _volume_is_negative(points: np.ndarray, faces: np.ndarray) -> bool:
    probe = trimesh.Trimesh(vertices=points, faces=faces, process=False)
    probe.merge_vertices()
    return bool(probe.is_watertight and probe.volume < 0)


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


def _smooth_outline(points: np.ndarray, front_faces: np.ndarray, radius: int = 5) -> np.ndarray:
    """Low-pass the real silhouette so pixel stairs stop catching the light."""

    if len(front_faces) == 0 or radius < 1:
        return points
    edges = _directed_boundary(front_faces)
    if len(edges) < 8:
        return points
    successor: dict[int, int] = {}
    for start, end in edges.tolist():
        successor[int(start)] = int(end)
    unused = set(successor)
    while unused:
        start = unused.pop()
        loop = [start]
        current = successor.get(start)
        while current is not None and current in unused:
            unused.discard(current)
            loop.append(current)
            current = successor.get(current)
        count = len(loop)
        if count < radius * 2 + 3:
            continue
        indices = np.asarray(loop, dtype=np.int64)
        xy = points[indices, :2]
        smoothed = np.empty_like(xy)
        for index in range(count):
            samples = [xy[(index + offset) % count] for offset in range(-radius, radius + 1)]
            smoothed[index] = np.mean(samples, axis=0)
        mixed = xy * 0.2 + smoothed * 0.8
        points[indices, 0] = mixed[:, 0]
        points[indices, 1] = mixed[:, 1]
        # The back vertex is stored immediately after its front partner.
        back = indices + 1
        keep = back < len(points)
        points[back[keep], 0] = points[indices[keep], 0]
        points[back[keep], 1] = points[indices[keep], 1]
    return points


