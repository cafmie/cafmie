"""Small image helpers shared by the mesher and the UI previews."""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, distance_transform_edt, label


def clean_mask(mask: np.ndarray, min_ratio: float = 0.08) -> np.ndarray:
    """Drop specks and keep parts that are large relative to the main subject."""

    hard = mask > 0.5
    labeled, count = label(hard)
    if count == 0:
        return mask
    areas = np.bincount(labeled.ravel())
    areas[0] = 0
    largest = int(areas.max())
    keep = areas >= max(largest * min_ratio, 64)
    keep[0] = False
    kept = keep[labeled]
    if not kept.any():
        kept = labeled == int(areas.argmax())
    halo = binary_dilation(kept, iterations=2)
    return np.where(halo, mask, 0).astype(np.float32)


def extend_colors(rgb: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Paint background pixels with the nearest foreground color to avoid edge halos."""

    if valid.all() or not valid.any():
        return rgb
    _, nearest = distance_transform_edt(~valid, return_indices=True)
    painted = rgb.copy()
    missing = ~valid
    painted[missing] = rgb[nearest[0][missing], nearest[1][missing]]
    return painted


def colorize_depth(depth: np.ndarray, mask: np.ndarray) -> Image.Image:
    valid = mask > 0.45
    if int(valid.sum()) < 8:
        valid = np.ones(depth.shape, dtype=bool)
    low, high = np.percentile(depth[valid], [3, 97])
    if float(high - low) < 1e-6:
        gray = np.full((*depth.shape, 3), 40, dtype=np.uint8)
        return Image.fromarray(gray)
    amount = np.clip((depth - low) / (high - low), 0.0, 1.0)
    stops = np.array(
        [
            [28, 22, 19],
            [120, 62, 42],
            [216, 122, 70],
            [246, 232, 214],
        ],
        dtype=np.float32,
    )
    position = amount * (len(stops) - 1)
    index = np.floor(position).astype(np.int32)
    index = np.clip(index, 0, len(stops) - 2)
    local = (position - index)[..., None]
    colored = stops[index] * (1.0 - local) + stops[index + 1] * local
    colored[~valid] = np.array([18, 16, 14], dtype=np.float32)
    return Image.fromarray(colored.astype(np.uint8))


def mask_preview(mask: np.ndarray) -> Image.Image:
    gray = np.clip(mask * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(gray, mode="L")
