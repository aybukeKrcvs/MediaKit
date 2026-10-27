"""On-demand AI model files. Pure Python: stdlib only, no Qt.

Models are not bundled with the installer (hundreds of MB each). They
are downloaded on first use into a per-user cache and verified with a
SHA-256 checksum, so a truncated or tampered file is never loaded.

Download writes to `<name>.part` and renames only after the checksum
matches: a crash or cancel never leaves a half file under the real name.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mediakit.core.batch import CancelToken

# on_progress(bytes_done, bytes_total)
DownloadProgress = Callable[[int, int], None]

CHUNK = 1024 * 1024
TIMEOUT_SECONDS = 30


class ModelDownloadError(Exception):
    """Network failure, bad checksum or cancellation."""


class DownloadCancelled(ModelDownloadError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    key: str
    filename: str
    url: str
    sha256: str
    size: int  # bytes, for the UI before the download starts
    license: str

    @property
    def size_mb(self) -> int:
        return round(self.size / 1_000_000)


def default_model_dir() -> Path:
    """Per-user cache. MEDIAKIT_MODEL_DIR overrides (tests, portable use)."""
    override = os.environ.get("MEDIAKIT_MODEL_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "MediaKit" / "models"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "mediakit" / "models"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


class ModelStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_model_dir()

    def path(self, spec: ModelSpec) -> Path:
        return self.root / spec.filename

    def is_installed(self, spec: ModelSpec) -> bool:
        """Cheap check (size only). The checksum ran at download time."""
        path = self.path(spec)
        return path.is_file() and path.stat().st_size == spec.size

    def remove(self, spec: ModelSpec) -> None:
        self.path(spec).unlink(missing_ok=True)

    def download(
        self,
        spec: ModelSpec,
        on_progress: DownloadProgress | None = None,
        cancel: CancelToken | None = None,
    ) -> Path:
        target = self.path(spec)
        if self.is_installed(spec):
            return target
        self.root.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")

        request = urllib.request.Request(spec.url, headers={"User-Agent": "MediaKit"})
        digest = hashlib.sha256()
        done = 0
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                total = int(response.headers.get("Content-Length") or spec.size)
                with partial.open("wb") as handle:
                    while True:
                        if cancel is not None and cancel.cancelled:
                            raise DownloadCancelled("cancelled")
                        block = response.read(CHUNK)
                        if not block:
                            break
                        handle.write(block)
                        digest.update(block)
                        done += len(block)
                        if on_progress is not None:
                            on_progress(done, total)
        except DownloadCancelled:
            partial.unlink(missing_ok=True)
            raise
        except OSError as exc:  # URLError, timeouts, disk full all land here
            partial.unlink(missing_ok=True)
            raise ModelDownloadError(f"Download failed: {exc}") from exc

        if digest.hexdigest() != spec.sha256:
            partial.unlink(missing_ok=True)
            raise ModelDownloadError("Checksum mismatch: the file is corrupt or was modified")
        os.replace(partial, target)  # atomic on the same volume
        return target
