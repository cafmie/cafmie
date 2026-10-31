"""Pick an ONNX Runtime provider, preferring a GPU."""

from __future__ import annotations

import os
import threading

import onnxruntime as ort

_GPU_PROVIDERS = (
    "CUDAExecutionProvider",
    "ROCMExecutionProvider",
    "DmlExecutionProvider",
    "CoreMLExecutionProvider",
)

_LABELS = {
    "CUDAExecutionProvider": "GPU (CUDA)",
    "ROCMExecutionProvider": "GPU (ROCm)",
    "DmlExecutionProvider": "GPU (DirectML)",
    "CoreMLExecutionProvider": "GPU (CoreML)",
    "CPUExecutionProvider": "CPU",
}

_current_lock = threading.Lock()
_current: Device | None = None


class Device:
    def __init__(self, provider: str) -> None:
        self.provider = provider

    @property
    def gpu(self) -> bool:
        return self.provider != "CPUExecutionProvider"

    @property
    def label(self) -> str:
        return _LABELS.get(self.provider, self.provider)


def current() -> Device | None:
    with _current_lock:
        return _current


def requested_device() -> str:
    return os.environ.get("IMAGETO3D_DEVICE", "auto").strip().lower() or "auto"


def provider_chain() -> list[str]:
    """Providers to try, best GPU first. CPU is the last resort unless forced off."""

    available = set(ort.get_available_providers())
    choice = requested_device()
    if choice in {"cpu", "cpuexecutionprovider"}:
        return ["CPUExecutionProvider"]
    if choice in {"cuda", "gpu"}:
        if "CUDAExecutionProvider" not in available:
            raise RuntimeError(
                "CUDA が見つかりません。NVIDIA ドライバと onnxruntime-gpu を入れて、"
                "CPU 版の onnxruntime は外してください。"
            )
        return ["CUDAExecutionProvider"]
    if choice not in {"auto", ""}:
        raise RuntimeError("IMAGETO3D_DEVICE は auto、cuda、cpu のいずれかです。")
    chain = [name for name in _GPU_PROVIDERS if name in available]
    chain.append("CPUExecutionProvider")
    return chain


def open_session(model_path: str) -> tuple[ort.InferenceSession, Device]:
    """Load a model on the first provider that actually stays active."""

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.log_severity_level = 3
    errors: list[str] = []
    for provider in provider_chain():
        try:
            session = ort.InferenceSession(
                str(model_path),
                sess_options=options,
                providers=[_provider_entry(provider)],
            )
        except Exception as error:
            errors.append(f"{provider}: {error}")
            continue
        active = list(session.get_providers())
        if not active or active[0] != provider:
            errors.append(f"{provider}: 有効になったのは {active or 'なし'} です")
            continue
        device = Device(provider)
        global _current
        with _current_lock:
            _current = device
        return session, device
    detail = " / ".join(errors) if errors else "利用できる実行環境がありません"
    raise RuntimeError(f"モデルを読み込めませんでした。{detail}")


def _provider_entry(provider: str) -> str | tuple[str, dict[str, object]]:
    if provider != "CUDAExecutionProvider":
        return provider
    device_id = int(os.environ.get("IMAGETO3D_DEVICE_ID", "0"))
    return (
        provider,
        {
            "device_id": device_id,
            "arena_extend_strategy": "kNextPowerOfTwo",
            "cudnn_conv_algo_search": "HEURISTIC",
            "do_copy_in_default_stream": True,
        },
    )
