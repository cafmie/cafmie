"""Turn one image into a mesh."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import distance_transform_edt

from . import depth as depth_model
from . import segment as segment_model
from .mesh import build_mesh
from .preview import clean_mask, colorize_depth, mask_preview


@dataclass
class Settings:
    mode: str = "volume"
    cutout: bool = True
    resolution: int = 220
    depth_scale: float = 0.22
    inflate: float = 0.46
    thickness: float = 0.08
    smooth: float = 1.0

    def clamped(self) -> Settings:
        mode = self.mode if self.mode in {"volume", "relief"} else "volume"
        return replace(
            self,
            mode=mode,
            cutout=bool(self.cutout),
            resolution=int(np.clip(self.resolution, 64, 360)),
            depth_scale=float(np.clip(self.depth_scale, 0.0, 1.5)),
            inflate=float(np.clip(self.inflate, 0.0, 1.2)),
            thickness=float(np.clip(self.thickness, 0.0, 0.6)),
            smooth=float(np.clip(self.smooth, 0.0, 4.0)),
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
    image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
    return image


def reconstruct(image: Image.Image, settings: Settings, on_status=None) -> Result:
    settings = settings.clamped()
    started = time.perf_counter()
    notice = ""
    rgb, alpha = _split_alpha(image)

    if settings.cutout and alpha is not None:
        if on_status:
            on_status("画像の透明部分を輪郭に使います")
        mask = alpha
    elif settings.cutout:
        if on_status:
            on_status("背景を切り抜いています")
        mask = clean_mask(segment_model.estimate_mask(rgb))
    else:
        mask = np.ones((rgb.height, rgb.width), dtype=np.float32)
        mask[0, :] = mask[-1, :] = 0
        mask[:, 0] = mask[:, -1] = 0

    if float((mask > 0.5).mean()) < 0.004:
        notice = "被写体を検出できなかったので、画像全体を立体にしました。"
        mask = np.ones((rgb.height, rgb.width), dtype=np.float32)
        mask[0, :] = mask[-1, :] = 0
        mask[:, 0] = mask[:, -1] = 0

    if on_status:
        on_status("奥行きを推定しています")
    composite = _on_gray(rgb, mask) if settings.cutout else rgb
    depth = depth_model.estimate_depth(composite)
    depth = _near_is_large(depth, mask)

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
