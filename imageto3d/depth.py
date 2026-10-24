"""Relative depth from Depth Anything V2 Small."""

from __future__ import annotations

import threading

import numpy as np
import onnxruntime as ort
from PIL import Image

from .download import MODELS, ensure_models

_session: ort.InferenceSession | None = None
_lock = threading.Lock()

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def get_session() -> ort.InferenceSession:
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is None:
            ensure_models()
            path = next(model.path() for model in MODELS if model.key == "depth")
            options = ort.SessionOptions()
            options.intra_op_num_threads = 0
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            options.log_severity_level = 3
            _session = ort.InferenceSession(
                str(path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
    return _session


def _snap(value: float, multiple: int = 14) -> int:
    return max(multiple, int(round(value / multiple)) * multiple)


def estimate_depth(image: Image.Image) -> np.ndarray:
    """Return a relative depth map, shaped (height, width). Larger values are nearer."""

    rgb = image.convert("RGB")
    width, height = rgb.size
    scale = 518.0 / min(width, height)
    if max(width, height) * scale > 756:
        scale *= 756.0 / (max(width, height) * scale)
    resized = rgb.resize((_snap(width * scale), _snap(height * scale)), Image.Resampling.BICUBIC)
    array = np.asarray(resized).astype(np.float32) / 255.0
    array = (array - _MEAN) / _STD
    tensor = np.transpose(array, (2, 0, 1))[None].astype(np.float32)

    session = get_session()
    input_name = session.get_inputs()[0].name
    predicted = np.asarray(session.run(None, {input_name: tensor})[0], dtype=np.float32)
    depth = np.squeeze(predicted).astype(np.float32)
    if depth.ndim != 2:
        raise RuntimeError(f"深度モデルの出力形状が想定外です: {predicted.shape}")
    sized = Image.fromarray(depth, mode="F").resize(rgb.size, Image.Resampling.BILINEAR)
    return np.asarray(sized, dtype=np.float32)
