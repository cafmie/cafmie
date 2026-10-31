"""An original shaded apple, used as the in-app sample."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def render_sample(size: int = 960) -> Image.Image:
    y, x = np.mgrid[0:size, 0:size]
    cx, cy = size * 0.5, size * 0.54
    radius = size * 0.30
    dx = (x - cx) / radius
    dy = (y - cy) / radius
    r2 = dx * dx + dy * dy
    body = r2 <= 1.0
    z = np.zeros_like(dx)
    z[body] = np.sqrt(np.clip(1.0 - r2[body], 0.0, 1.0))

    light = np.array([-0.35, 0.52, 0.78], dtype=np.float32)
    light /= np.linalg.norm(light)
    nx = np.zeros_like(dx)
    ny = np.zeros_like(dy)
    nx[body] = dx[body]
    ny[body] = -dy[body]
    nz = z
    lambert = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0.0, 1.0)
    half = (light + np.array([0.0, 0.0, 1.0])) 
    half = half / np.linalg.norm(half)
    spec = np.clip(nx * half[0] + ny * half[1] + nz * half[2], 0.0, 1.0) ** 40

    stripe = 0.5 + 0.5 * np.sin((dx * 1.4 + dy * 0.2) * np.pi)
    red = np.array([168, 42, 36], dtype=np.float32)
    highlight = np.array([214, 86, 62], dtype=np.float32)
    shade = np.array([92, 18, 22], dtype=np.float32)
    color = shade + (red - shade) * lambert[..., None] + (highlight - red) * (stripe * body)[..., None] * 0.35
    color += spec[..., None] * np.array([90, 50, 40], dtype=np.float32)
    color = np.clip(color, 0, 255)

    paper = np.full((size, size, 3), [244, 239, 230], dtype=np.float32)
    shadow = np.exp(-(((x - cx) / (radius * 0.92)) ** 2 + ((y - (cy + radius * 0.78)) / (radius * 0.16)) ** 2))
    paper *= 1.0 - shadow[..., None] * 0.28
    alpha = np.clip((1.0 - r2) * 18.0, 0.0, 1.0)[..., None]
    # A slightly soft edge, still an obvious foreground.
    alpha = np.where(r2 <= 1.0, 1.0, np.clip(1.0 - (np.sqrt(r2) - 1.0) * 30.0, 0.0, 1.0))[..., None]
    image = paper * (1.0 - alpha) + color * alpha
    picture = Image.fromarray(image.astype(np.uint8))

    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    stem_top = (cx, cy - radius * 0.92)
    draw.line([(cx, cy - radius * 0.15), stem_top], fill=(92, 58, 36, 255), width=max(6, size // 90))
    leaf = [
        (cx + radius * 0.02, cy - radius * 0.72),
        (cx + radius * 0.38, cy - radius * 0.98),
        (cx + radius * 0.16, cy - radius * 0.58),
    ]
    draw.polygon(leaf, fill=(64, 112, 62, 255))
    draw.line(leaf[:2], fill=(36, 72, 40, 255), width=max(3, size // 180))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.6))
    picture = Image.alpha_composite(picture.convert("RGBA"), overlay).convert("RGB")
    return picture


def write_sample(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    render_sample().save(path, format="PNG", optimize=True)
