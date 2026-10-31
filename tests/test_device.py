import pytest

from imageto3d import device
from imageto3d.device import open_session, provider_chain


def test_auto_tries_cuda_before_cpu(monkeypatch):
    monkeypatch.delenv("IMAGETO3D_DEVICE", raising=False)
    monkeypatch.setattr(
        device.ort,
        "get_available_providers",
        lambda: ["CPUExecutionProvider", "CUDAExecutionProvider"],
    )
    assert provider_chain() == ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_cpu_flag_skips_the_gpu(monkeypatch):
    monkeypatch.setenv("IMAGETO3D_DEVICE", "cpu")
    monkeypatch.setattr(
        device.ort,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    assert provider_chain() == ["CPUExecutionProvider"]


def test_cuda_flag_requires_the_provider(monkeypatch):
    monkeypatch.setenv("IMAGETO3D_DEVICE", "cuda")
    monkeypatch.setattr(device.ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    with pytest.raises(RuntimeError, match="CUDA"):
        provider_chain()


def test_session_falls_back_when_cuda_does_not_stay_active(monkeypatch):
    monkeypatch.delenv("IMAGETO3D_DEVICE", raising=False)

    class FakeSession:
        def __init__(self, path, sess_options, providers):
            name = providers[0][0] if isinstance(providers[0], tuple) else providers[0]
            if name == "CUDAExecutionProvider":
                raise RuntimeError("no device")
            self._active = [name]

        def get_providers(self):
            return list(self._active)

    monkeypatch.setattr(device, "provider_chain", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(device.ort, "InferenceSession", FakeSession)
    session, chosen = open_session("model.onnx")
    assert chosen.provider == "CPUExecutionProvider"
    assert chosen.gpu is False
    assert session.get_providers() == ["CPUExecutionProvider"]
    assert device.current().provider == "CPUExecutionProvider"


def test_cuda_session_records_a_gpu(monkeypatch):
    class FakeSession:
        def __init__(self, path, sess_options, providers):
            entry = providers[0]
            assert isinstance(entry, tuple)
            assert entry[0] == "CUDAExecutionProvider"
            assert entry[1]["device_id"] == 0
            assert entry[1]["cudnn_conv_algo_search"] == "HEURISTIC"

        def get_providers(self):
            return ["CUDAExecutionProvider"]

    monkeypatch.setattr(device, "provider_chain", lambda: ["CUDAExecutionProvider"])
    monkeypatch.setattr(device.ort, "InferenceSession", FakeSession)
    _session, chosen = open_session("model.onnx")
    assert chosen.gpu is True
    assert chosen.label == "GPU (CUDA)"
