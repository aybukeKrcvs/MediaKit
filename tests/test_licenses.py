"""Licenses and credits cannot be forgotten: these tests fail when a
model has no credit, a license file is missing, or the collected
library licenses no longer match what is installed."""

import importlib.util
import json
from importlib import metadata
from pathlib import Path

import pytest

from mediakit.modules.models import all_model_specs

ROOT = Path(__file__).resolve().parent.parent
LICENSES = ROOT / "src" / "mediakit" / "assets" / "licenses"


def test_every_model_is_credited_with_its_license_text():
    specs = all_model_specs()
    assert specs, "model discovery found nothing"
    for spec in specs:
        credit = spec.credit
        assert credit.name and credit.authors and credit.license, spec.key
        assert credit.url.startswith("https://"), spec.key
        assert credit.license_files, f"{spec.key}: no license text"
        for name in credit.license_files:
            assert (LICENSES / name).is_file(), f"{spec.key}: missing {name}"


def test_every_library_entry_has_its_files():
    entries = json.loads((LICENSES / "libraries.json").read_text(encoding="utf-8"))
    assert entries
    for entry in entries:
        assert entry["files"], f"{entry['name']}: no license file"
        for name in entry["files"]:
            assert (LICENSES / name).is_file(), f"{entry['name']}: missing {name}"


def test_notices_file_lists_every_model():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for spec in all_model_specs():
        assert spec.credit.name in notices, f"run tools/collect_licenses.py ({spec.key})"


def test_collected_libraries_match_installed_packages():
    pytest.importorskip("packaging")
    try:
        metadata.distribution("mediakit")
    except metadata.PackageNotFoundError:
        pytest.skip("mediakit is not installed as a package here")
    spec = importlib.util.spec_from_file_location(
        "collect_licenses", ROOT / "tools" / "collect_licenses.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    installed = {(d.metadata["Name"], d.version) for d in tool.runtime_closure()}
    entries = json.loads((LICENSES / "libraries.json").read_text(encoding="utf-8"))
    added_by_tool = ("Python", "PyInstaller bootloader")  # shipped, not dependencies
    collected = {(e["name"], e["version"]) for e in entries if e["name"] not in added_by_tool}
    assert installed == collected, (
        "dependencies changed: run `uv run python tools/collect_licenses.py` and commit"
    )


def test_about_dialog_shows_credit_and_full_license_text():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mediakit.shell.about import AboutDialog

    _app = QApplication.instance() or QApplication([])
    dialog = AboutDialog(focus="model:realesrgan-x4plus")
    assert dialog.current_key() == "model:realesrgan-x4plus"
    text = dialog.text.toPlainText()
    assert "Xintao Wang" in text and "BSD 3-Clause License" in text

    dialog.select("lib:pillow")
    assert "pillow" in dialog.text.toPlainText().lower()
    # section headers are labels, never selected
    dialog.select(None)
    assert dialog.current_key() is not None


def test_model_panel_shows_who_made_the_model(tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mediakit.core.models import ModelStore
    from mediakit.modules.image.upscale_tool import UpscaleTool

    _app = QApplication.instance() or QApplication([])
    tool = UpscaleTool(store=ModelStore(tmp_path))
    tool.model_panel.tiles[0].click()
    assert "Real-ESRGAN" in tool.model_panel.credit.text()
    assert "BSD-3-Clause" in tool.model_panel.credit.text()
