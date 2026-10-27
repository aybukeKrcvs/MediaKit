"""Output path resolution. Pure Python, no Qt, no Pillow."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class ConflictPolicy(StrEnum):
    """What to do when the target file already exists."""

    RENAME = "rename"      # photo.png -> photo (1).png
    OVERWRITE = "overwrite"
    SKIP = "skip"


def unique_path(path: Path) -> Path:
    """Return `path` if free, else append ' (n)' until it is."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    n = 1
    while True:
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def resolve_output_path(
    source: Path,
    out_dir: Path,
    extension: str,
    policy: ConflictPolicy = ConflictPolicy.RENAME,
) -> Path | None:
    """Build the destination path for `source` inside `out_dir`.

    `extension` is given without a dot ('png', 'webp').
    Returns None when the file exists and the policy is SKIP.
    """
    ext = extension.lower().lstrip(".")
    target = out_dir / f"{source.stem}.{ext}"

    if not target.exists():
        return target
    # `==` not `is`: Qt's QComboBox.currentData() can hand back a plain
    # str instead of the ConflictPolicy member it was given, and identity
    # comparison silently fails for that case (StrEnum equality is safe).
    if policy == ConflictPolicy.OVERWRITE:
        return target
    if policy == ConflictPolicy.SKIP:
        return None
    return unique_path(target)


def collect_files(paths: list[Path], extensions: set[str], recursive: bool = True) -> list[Path]:
    """Expand a mixed list of files and folders into a flat list of files.

    `extensions` are lowercase, dotless ('jpg', 'png').
    Order is preserved, duplicates removed.
    """
    seen: set[Path] = set()
    out: list[Path] = []

    def accept(p: Path) -> None:
        rp = p.resolve()
        if rp in seen:
            return
        if rp.suffix.lower().lstrip(".") in extensions:
            seen.add(rp)
            out.append(rp)

    for p in paths:
        if p.is_dir():
            globber = p.rglob("*") if recursive else p.glob("*")
            for child in sorted(globber):
                if child.is_file():
                    accept(child)
        elif p.is_file():
            accept(p)

    return out