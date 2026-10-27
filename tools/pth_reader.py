"""Read a PyTorch .pth state_dict into numpy arrays, without torch.

A modern .pth is a zip archive:
    <root>/data.pkl      pickle of the object tree (dicts, tensor stubs)
    <root>/data/<key>    raw little-endian bytes of each tensor storage

The pickle refers to storages through "persistent ids" and rebuilds
tensors with torch._utils._rebuild_tensor_v2. We intercept both and
return numpy views instead, so the dev tool needs only numpy.
Only dense, contiguous float/int tensors are supported, which is all a
conv network checkpoint contains.
"""

from __future__ import annotations

import pickle
import zipfile
from collections import OrderedDict
from pathlib import Path

import numpy as np

_DTYPES = {
    "FloatStorage": np.float32,
    "HalfStorage": np.float16,
    "DoubleStorage": np.float64,
    "LongStorage": np.int64,
    "IntStorage": np.int32,
    "ByteStorage": np.uint8,
}


class _StorageType:
    def __init__(self, name: str) -> None:
        self.dtype = _DTYPES[name]


def _rebuild_tensor(storage, offset, size, stride, *_rest):
    if not size:
        return storage[offset].copy()
    itemsize = storage.dtype.itemsize
    return np.lib.stride_tricks.as_strided(
        storage[offset:],
        shape=tuple(size),
        strides=tuple(s * itemsize for s in stride),
    ).copy()


class _Unpickler(pickle.Unpickler):
    def __init__(self, handle, archive: zipfile.ZipFile, root: str) -> None:
        super().__init__(handle)
        self._archive = archive
        self._root = root
        self._storages: dict[str, np.ndarray] = {}

    def find_class(self, module: str, name: str):
        if module == "torch._utils" and name == "_rebuild_tensor_v2":
            return _rebuild_tensor
        if module == "torch" and name in _DTYPES:
            return _StorageType(name)
        if module == "collections" and name == "OrderedDict":
            return OrderedDict
        raise pickle.UnpicklingError(f"unsupported global {module}.{name}")

    def persistent_load(self, pid):
        _kind, storage_type, key, _location, _numel = pid
        if key not in self._storages:
            raw = self._archive.read(f"{self._root}/data/{key}")
            self._storages[key] = np.frombuffer(raw, dtype=storage_type.dtype)
        return self._storages[key]


def load_state_dict(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        pkl = next(n for n in archive.namelist() if n.endswith("/data.pkl"))
        root = pkl.rsplit("/", 1)[0]
        with archive.open(pkl) as handle:
            return _Unpickler(handle, archive, root).load()
