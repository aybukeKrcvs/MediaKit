"""Collect the license files of everything MediaKit ships.

Run after any dependency change, then commit the result (project root):

    uv run python tools/collect_licenses.py

It writes
    src/mediakit/assets/licenses/libraries/<package>/...   copied license files
    src/mediakit/assets/licenses/libraries.json            name, version, license
    THIRD_PARTY_NOTICES.md                                  human-readable summary

Libraries: the runtime dependency tree of `mediakit`, read from the
installed package metadata (importlib.metadata), plus two things
PyInstaller puts in the installer that are not dependencies: the Python
runtime itself and PyInstaller's bootloader (mediakit.exe is that
bootloader). Run it on Windows: the Windows build ships
onnxruntime-directml, whose notices differ from the plain package.

Models come from the Credit on each ModelSpec (mediakit.modules.models).
tests/test_licenses.py fails when this output is out of date.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
LICENSES = ROOT / "src" / "mediakit" / "assets" / "licenses"
LIBRARIES = LICENSES / "libraries"
LICENSE_NAME = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS|THIRD.?PARTY)", re.IGNORECASE)

# Packages whose wheels carry no license file at all. Canonical texts,
# taken from the SPDX license list, live in tools/license_texts/.
FALLBACK_TEXTS = {
    "pyside6": ("LGPL-3.0-only", "GPL-3.0-only"),
    "pyside6-addons": ("LGPL-3.0-only", "GPL-3.0-only"),
    "pyside6-essentials": ("LGPL-3.0-only", "GPL-3.0-only"),
    "pyside6-pdf": ("LGPL-3.0-only", "GPL-3.0-only"),
    "pyside6-webengine": ("LGPL-3.0-only", "GPL-3.0-only"),
    "shiboken6": ("LGPL-3.0-only", "GPL-3.0-only"),
    "flatbuffers": ("Apache-2.0",),
}
TEXTS = Path(__file__).resolve().parent / "license_texts"


def runtime_closure(root: str = "mediakit") -> list[metadata.Distribution]:
    """`root` and everything it needs at runtime, extras excluded."""
    env = default_environment()
    seen: dict[str, metadata.Distribution] = {}
    queue = [root]
    while queue:
        name = canonicalize_name(queue.pop())
        if name in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # marker-excluded on this platform
        seen[name] = dist
        for line in dist.requires or ():
            req = Requirement(line)
            if req.marker is None or req.marker.evaluate({**env, "extra": ""}):
                queue.append(req.name)
    seen.pop(canonicalize_name(root), None)
    return sorted(seen.values(), key=lambda d: canonicalize_name(d.metadata["Name"]))


def license_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    field = (meta.get("License") or "").strip()
    if field and len(field) < 60 and "\n" not in field:
        return field
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    return ", ".join(classifiers) or "see license files"


def license_files(dist: metadata.Distribution) -> list[tuple[str, Path]]:
    """(flat name, source path) for every license-like file the package
    ships: anything in its .dist-info, plus top-level ones such as
    onnxruntime/ThirdPartyNotices.txt. Deeper copies (test fixtures,
    vendored examples) are skipped."""
    found = []
    for entry in dist.files or ():
        parts = Path(str(entry)).parts
        if not parts or not LICENSE_NAME.search(parts[-1]):
            continue
        in_dist_info = parts[0].endswith(".dist-info")
        if not in_dist_info and len(parts) > 2:
            continue
        inner = parts[1:] if in_dist_info else parts
        if inner and inner[0] == "licenses":
            inner = inner[1:]
        found.append(("__".join(inner), Path(dist.locate_file(entry))))
    return found


def copy_into(name: str, sources: list[tuple[str, Path]]) -> list[str]:
    target = LIBRARIES / name
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for flat, source in sources:
        if not source.is_file():
            continue
        destination = target / flat
        shutil.copyfile(source, destination)
        written.append(destination.relative_to(LICENSES).as_posix())
    return sorted(written)


def fallback_texts(name: str) -> list[tuple[str, Path]]:
    return [(f"{spdx}.txt", TEXTS / f"{spdx}.txt") for spdx in FALLBACK_TEXTS.get(name, ())]


def python_license() -> list[tuple[str, Path]]:
    base = Path(sys.base_prefix)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for candidate in (
        base / "LICENSE.txt",  # Windows installer layout
        base / "lib" / version / "LICENSE.txt",
        Path("/usr/lib") / version / "LICENSE.txt",
    ):
        if candidate.is_file():
            return [("LICENSE.txt", candidate)]
    return []


def collect_libraries() -> list[dict]:
    if LIBRARIES.exists():
        shutil.rmtree(LIBRARIES)
    entries = []
    for dist in runtime_closure():
        name = dist.metadata["Name"]
        key = canonicalize_name(name)
        files = copy_into(key, license_files(dist) or fallback_texts(key))
        entries.append(
            {
                "name": name,
                "version": dist.version,
                "license": license_of(dist),
                "url": dist.metadata.get("Home-page") or _project_url(dist),
                "files": files,
            }
        )

    # Shipped inside the installer, but not a dependency of mediakit.
    entries.append(
        {
            "name": "Python",
            "version": sys.version.split()[0],
            "license": "PSF-2.0",
            "url": "https://www.python.org",
            "files": copy_into("python", python_license()),
        }
    )
    try:
        bootloader = metadata.distribution("pyinstaller")
        entries.append(
            {
                "name": "PyInstaller bootloader",
                "version": bootloader.version,
                "license": "GPL-2.0-or-later WITH Bootloader-exception",
                "url": "https://pyinstaller.org",
                "files": copy_into("pyinstaller", license_files(bootloader)),
            }
        )
    except metadata.PackageNotFoundError:
        print("warning: pyinstaller not installed, bootloader license not collected")
    return entries


def _project_url(dist: metadata.Distribution) -> str:
    for line in dist.metadata.get_all("Project-URL") or []:
        label, _, url = line.partition(",")
        if label.strip().lower() in ("homepage", "home", "source", "repository"):
            return url.strip()
    return ""


def write_notices(libraries: list[dict]) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from mediakit.modules.models import all_model_specs

    lines = [
        "# Third-party notices",
        "",
        "MediaKit is built on the open-source work listed here. Full license",
        "texts are in `src/mediakit/assets/licenses/` and inside the app",
        "(sidebar \u2192 About).",
        "",
        "This file is generated by `tools/collect_licenses.py`; do not edit it by hand.",
        "",
        "## Models (downloaded on first use)",
        "",
        "| Model | Authors | License | Source | Notes |",
        "|---|---|---|---|---|",
    ]
    for spec in all_model_specs():
        c = spec.credit
        lines.append(f"| {c.name} | {c.authors} | {c.license} | {c.url} | {c.note} |")
    lines += [
        "",
        "## Libraries (bundled in the installer)",
        "",
        "| Package | Version | License |",
        "|---|---|---|",
    ]
    for entry in libraries:
        lines.append(f"| {entry['name']} | {entry['version']} | {entry['license']} |")
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    libraries = collect_libraries()
    (LICENSES / "libraries.json").write_text(
        json.dumps(libraries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_notices(libraries)
    missing = [e["name"] for e in libraries if not e["files"]]
    print(f"{len(libraries)} libraries collected")
    if missing:
        print("no license file found for:", ", ".join(missing), "(check by hand)")


if __name__ == "__main__":
    main()
