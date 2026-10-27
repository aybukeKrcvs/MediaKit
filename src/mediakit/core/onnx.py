"""ONNX Runtime session creation with GPU-first, CPU-fallback policy.

Provider order:
  DirectML (Windows, any DX12 GPU: NVIDIA/AMD/Intel, no CUDA install)
  CUDA     (if onnxruntime-gpu happens to be installed)
  CPU      (always available)

Sessions are expensive to create (seconds for a 200 MB model), so they
are cached per model file and reused across a whole batch.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import onnxruntime as ort

_GPU_PROVIDERS = ("DmlExecutionProvider", "CUDAExecutionProvider")
_DEVICE_NAMES = {
    "DmlExecutionProvider": "GPU (DirectML)",
    "CUDAExecutionProvider": "GPU (CUDA)",
    "CPUExecutionProvider": "CPU",
}


@dataclass(frozen=True)
class LoadedModel:
    session: ort.InferenceSession
    device: str


_cache: dict[tuple[Path, bool], LoadedModel] = {}
_lock = threading.Lock()


def available_device() -> str:
    """What a new session would run on. For display only."""
    providers = ort.get_available_providers()
    for name in _GPU_PROVIDERS:
        if name in providers:
            return _DEVICE_NAMES[name]
    return _DEVICE_NAMES["CPUExecutionProvider"]


def _make_session(path: Path, provider: str) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if provider == "DmlExecutionProvider":
        # DirectML does not support memory pattern optimisation or
        # parallel execution; leaving them on fails at session creation.
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers = (
        [provider] if provider == "CPUExecutionProvider" else [provider, "CPUExecutionProvider"]
    )
    return ort.InferenceSession(str(path), sess_options=options, providers=providers)


def load_model(path: Path, prefer_gpu: bool = True) -> LoadedModel:
    """Cached session for `path`. Falls back to CPU if the GPU path fails
    (old driver, out of VRAM at load time, unsupported operator)."""
    key = (path.resolve(), prefer_gpu)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached

        candidates = []
        if prefer_gpu:
            available = ort.get_available_providers()
            candidates = [p for p in _GPU_PROVIDERS if p in available]
        candidates.append("CPUExecutionProvider")

        last_error: Exception | None = None
        for provider in candidates:
            try:
                session = _make_session(path, provider)
            except Exception as exc:  # noqa: BLE001 - try the next provider
                last_error = exc
                continue
            active = session.get_providers()[0]
            loaded = LoadedModel(session, _DEVICE_NAMES.get(active, active))
            _cache[key] = loaded
            return loaded
        raise RuntimeError(f"Could not load model {path.name}: {last_error}")


def unload_all() -> None:
    """Free cached sessions (and their GPU memory)."""
    with _lock:
        _cache.clear()
