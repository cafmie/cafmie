"""Foreground mask from the silueta ONNX model."""

from __future__ import annotations

import threading

import numpy as np
import onnxruntime as ort
from PIL import Image

from .download import MODELS, ensure_models

_session: ort.InferenceSession | None = None
_lock = threading.Lock()

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)


def get_session() -> ort.InferenceSession:
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is None:
            ensure_models()
            path = next(model.path() for model in MODELS if model.key == "cutout")
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


def estimate_mask(image: Image.Image) -> np.ndarray:
    """Return a float mask in 0..1, shaped (height, width), same size as ``image``."""

    rgb = image.convert("RGB")
    session = get_session()
    resized = rgb.resize((320, 320), Image.Resampling.LANCZOS)
    array = np.asarray(resized).astype(np.float32)
    array /= max(float(array.max()), 1.0)
    array = (array - _MEAN) / 1.0
    tensor = np.transpose(array, (2, 0, 1))[None].astype(np.float32)
    input_name = session.get_inputs()[0].name
    prediction = np.asarray(session.run(None, {input_name: tensor})[0], dtype=np.float32)
    mask = prediction[0, 0]
    low = float(mask.min())
    high = float(mask.max())
    mask = (mask - low) / (high - low + 1e-6)
    sized = Image.fromarray(mask, mode="F").resize(rgb.size, Image.Resampling.BILINEAR)
    return np.asarray(sized, dtype=np.float32)
