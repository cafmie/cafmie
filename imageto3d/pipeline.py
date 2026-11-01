"""Turn one image into a mesh."""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import distance_transform_edt, uniform_filter

from . import depth as depth_model
from . import segment as segment_model
from .mesh import build_mesh
from .objects import find_objects, keep_objects
from .preview import clean_mask, colorize_depth, mask_preview


@dataclass
class Settings:
    mode: str = "volume"
    cutout: bool = True
    resolution: int = 512
    depth_scale: float = 0.22
    inflate: float = 0.46
    thickness: float = 0.08
    smooth: float = 1.0
    detail: float = 0.85
    objects: tuple[int, ...] = ()

    def clamped(self) -> Settings:
        mode = self.mode if self.mode in {"volume", "relief"} else "volume"
        picked: list[int] = []
        for item in self.objects or ():
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= 255 and number not in picked:
                picked.append(number)
        return replace(
            self,
            mode=mode,
            cutout=bool(self.cutout),
            resolution=int(np.clip(self.resolution, 64, 768)),
            depth_scale=float(np.clip(self.depth_scale, 0.0, 1.5)),
            inflate=float(np.clip(self.inflate, 0.0, 1.2)),
            thickness=float(np.clip(self.thickness, 0.0, 0.6)),
            smooth=float(np.clip(self.smooth, 0.0, 4.0)),
            detail=float(np.clip(self.detail, 0.0, 1.5)),
            objects=tuple(picked),
        )


@dataclass
class Result:
    mesh: object
    depth_image: Image.Image
    mask_image: Image.Image
    vertices: int
    faces: int
    elapsed_s: float
    notice: str
    mode: str


def open_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as error:
        raise ValueError("画像を読み取れませんでした。PNG、JPEG、WebP を選んでください。") from error
    image = ImageOps.exif_transpose(image)
    if image.mode == "P":
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    elif image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    return image


_mask_lock = threading.Lock()
_mask_cache: tuple[bytes, bool, np.ndarray, str] | None = None


def prepare_mask(
    image: Image.Image, cutout: bool, cache_key: bytes | None = None
) -> tuple[np.ndarray, str]:
    """Foreground before speck cleanup. Kind is ``alpha``, ``cutout``, or ``full``.

    ``cache_key`` reuses the last cutout for the same upload so choosing an
    object does not run the cutout model twice. The returned array must not
    be edited in place.
    """

    global _mask_cache
    if cache_key is not None:
        with _mask_lock:
            if _mask_cache is not None and _mask_cache[0] == cache_key and _mask_cache[1] == cutout:
                return _mask_cache[2], _mask_cache[3]
    rgb, alpha = _split_alpha(image)
    if not cutout:
        mask = _full_mask(rgb)
        kind = "full"
    elif alpha is not None:
        mask = alpha
        kind = "alpha"
    else:
        mask = segment_model.estimate_mask(rgb)
        kind = "cutout"
    if cache_key is not None:
        with _mask_lock:
            _mask_cache = (cache_key, cutout, mask, kind)
    return mask, kind


def reconstruct(
    image: Image.Image,
    settings: Settings,
    on_status=None,
    mask_key: bytes | None = None,
) -> Result:
    settings = settings.clamped()
    started = time.perf_counter()
    notice = ""
    rgb, alpha = _split_alpha(image)

    if settings.cutout and alpha is not None:
        if on_status:
            on_status("画像の透明部分を輪郭に使います")
    elif settings.cutout and on_status:
        on_status("背景を切り抜いています")
    raw, kind = prepare_mask(image, settings.cutout, mask_key)
    explicit = False
    if settings.cutout and settings.objects:
        kept = keep_objects(raw, settings.objects)
        if kept is None:
            notice = "選んだ物体が見つからなかったので、主な被写体を立体にしました。"
            mask = raw if kind == "alpha" else clean_mask(raw)
        else:
            mask, used = kept
            explicit = True
            total = len(find_objects(raw)[0])
            if len(used) < total:
                names = "、".join(f"物体 {number}" for number in used)
                notice = f"{names}を立体にしました。"
    elif settings.cutout and kind != "alpha":
        mask = clean_mask(raw)
    else:
        mask = raw

    if not explicit and float((mask > 0.5).mean()) < 0.004:
        notice = "被写体を検出できなかったので、画像全体を立体にしました。"
        mask = _full_mask(rgb)

    if on_status:
        on_status("奥行きを推定しています")
    composite = _on_gray(rgb, mask) if settings.cutout else rgb
    depth = depth_model.estimate_depth(composite)
    depth = _near_is_large(depth, mask)
    depth = guide_depth(depth, composite)

    if on_status:
        on_status("メッシュを組んでいます")
    mesh = build_mesh(
        rgb,
        depth,
        mask,
        mode=settings.mode,
        resolution=settings.resolution,
        depth_scale=settings.depth_scale,
        inflate=settings.inflate,
        thickness=settings.thickness,
        smooth=settings.smooth,
        detail=settings.detail,
    )
    preview = _resize_preview(depth, mask, 420)
    return Result(
        mesh=mesh,
        depth_image=colorize_depth(preview[0], preview[1]),
        mask_image=mask_preview(preview[1]),
        vertices=int(len(mesh.vertices)),
        faces=int(len(mesh.faces)),
        elapsed_s=time.perf_counter() - started,
        notice=notice,
        mode=settings.mode,
    )


def _full_mask(image: Image.Image) -> np.ndarray:
    mask = np.ones((image.height, image.width), dtype=np.float32)
    mask[0, :] = mask[-1, :] = 0
    mask[:, 0] = mask[:, -1] = 0
    return mask


def _split_alpha(image: Image.Image) -> tuple[Image.Image, np.ndarray | None]:
    if image.mode != "RGBA":
        return image.convert("RGB"), None
    alpha = np.asarray(image.getchannel("A"), dtype=np.float32) / 255.0
    if float(alpha.min()) > 0.995:
        return image.convert("RGB"), None
    return image.convert("RGB"), alpha


def _on_gray(image: Image.Image, mask: np.ndarray) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    alpha = np.clip(mask, 0.0, 1.0)[..., None]
    flat = np.full_like(rgb, 128.0)
    mixed = rgb * alpha + flat * (1.0 - alpha)
    return Image.fromarray(mixed.astype(np.uint8))


def guide_depth(depth: np.ndarray, image: Image.Image) -> np.ndarray:
    """Move blurry depth onto the photograph's edges so small shapes stay separate."""

    guide = image.convert("L").resize((depth.shape[1], depth.shape[0]), Image.Resampling.LANCZOS)
    gray = np.asarray(guide, dtype=np.float32) / 255.0
    radius = max(2, min(12, min(depth.shape) // 24))
    return _guided_filter(gray, depth.astype(np.float32), radius, eps=1e-3)


def _guided_filter(guide: np.ndarray, source: np.ndarray, radius: int, eps: float) -> np.ndarray:
    window = radius * 2 + 1
    mean_guide = uniform_filter(guide, size=window)
    mean_source = uniform_filter(source, size=window)
    corr_guide = uniform_filter(guide * guide, size=window)
    corr_both = uniform_filter(guide * source, size=window)
    variance = corr_guide - mean_guide * mean_guide
    covariance = corr_both - mean_guide * mean_source
    slope = covariance / (variance + eps)
    intercept = mean_source - slope * mean_guide
    refined = uniform_filter(slope, size=window) * guide + uniform_filter(intercept, size=window)
    return refined.astype(np.float32)


def _near_is_large(depth: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Flip the map when the middle of the subject is farther than its edge."""

    valid = mask > 0.5
    if int(valid.sum()) < 32:
        return depth
    distance = distance_transform_edt(valid)
    center = distance >= np.percentile(distance[valid], 75)
    edge = valid & (distance <= 2.0)
    if int(center.sum()) < 8 or int(edge.sum()) < 8:
        return depth
    if float(depth[center].mean()) < float(depth[edge].mean()):
        return -depth
    return depth


def _resize_preview(depth: np.ndarray, mask: np.ndarray, long_side: int) -> tuple[np.ndarray, np.ndarray]:
    height, width = depth.shape
    scale = long_side / max(height, width, 1)
    if scale >= 1:
        return depth, mask
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    depth_image = Image.fromarray(depth.astype(np.float32), mode="F").resize(size, Image.Resampling.BILINEAR)
    mask_image = Image.fromarray(mask.astype(np.float32), mode="F").resize(size, Image.Resampling.BILINEAR)
    return np.asarray(depth_image), np.asarray(mask_image)
