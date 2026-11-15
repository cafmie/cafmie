"""Separate foreground blobs so the user can choose which one to model."""

from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label

# Keep a second subject when it is at least this fraction of the largest blob.
_MIN_RATIO = 0.012
_MIN_PIXELS = 48
_MAX_OBJECTS = 12
_LABEL_LONG_SIDE = 480


def parse_object_ids(value: str) -> tuple[int, ...]:
    """Read ``1,3`` or ``1、3`` into stable ids. Unknown text is ignored."""

    found: list[int] = []
    for part in str(value).replace("、", ",").split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        number = int(part)
        if 1 <= number <= 255 and number not in found:
            found.append(number)
    return tuple(found)


def find_objects(mask: np.ndarray) -> tuple[list[dict], np.ndarray]:
    """Return sizable blobs, largest first, and a map of their public ids.

    The label map matches ``mask`` and uses 0 for background. Ids start at 1.
    """

    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.uint8)
    hard = mask > 0.45
    labeled, count = label(hard)
    if count == 0:
        return [], labels
    areas = np.bincount(labeled.ravel())
    areas[0] = 0
    largest = int(areas.max())
    threshold = max(int(largest * _MIN_RATIO), _MIN_PIXELS)
    raw: list[tuple[int, int, int, int]] = []
    for index in range(1, count + 1):
        area = int(areas[index])
        if area < threshold:
            continue
        ys, xs = np.nonzero(labeled == index)
        raw.append((area, int(ys.min()), int(xs.min()), index))
    raw.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    raw = raw[:_MAX_OBJECTS]
    objects: list[dict] = []
    for public_id, (area, _top, _left, index) in enumerate(raw, start=1):
        component = labeled == index
        labels[component] = public_id
        ys, xs = np.nonzero(component)
        x0 = int(xs.min())
        y0 = int(ys.min())
        x1 = int(xs.max())
        y1 = int(ys.max())
        objects.append(
            {
                "id": public_id,
                "label": f"物体 {public_id}",
                "area": area,
                "box": {
                    "x": x0 / width,
                    "y": y0 / height,
                    "width": (x1 - x0 + 1) / width,
                    "height": (y1 - y0 + 1) / height,
                },
                "cx": float(xs.mean() / width),
                "cy": float(ys.mean() / height),
            }
        )
    return objects, labels


def keep_objects(mask: np.ndarray, ids: tuple[int, ...]) -> tuple[np.ndarray, tuple[int, ...]] | None:
    """Restrict ``mask`` to the requested ids. ``None`` when none of them exist."""

    objects, labels = find_objects(mask)
    present = {item["id"] for item in objects}
    used = tuple(number for number in ids if number in present)
    if not used:
        return None
    chosen = np.isin(labels, used)
    halo = binary_dilation(chosen, iterations=2)
    kept = np.where(halo, mask, 0).astype(np.float32)
    return kept, used


def describe_objects(mask: np.ndarray) -> dict:
    """JSON-ready object list. A label image is included only when there is a choice."""

    objects, labels = find_objects(mask)
    payload: dict = {
        "count": len(objects),
        "objects": objects if len(objects) >= 2 else [],
    }
    if len(objects) >= 2:
        payload["label"] = base64.b64encode(_label_png(labels)).decode("ascii")
    return payload


def _label_png(labels: np.ndarray) -> bytes:
    image = Image.fromarray(labels, mode="L")
    image.thumbnail((_LABEL_LONG_SIDE, _LABEL_LONG_SIDE), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
