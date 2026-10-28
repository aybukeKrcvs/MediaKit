"""Who made the third-party work MediaKit ships or downloads, and under
which license. Pure data, no Qt.

Every downloadable model carries a Credit (see ModelSpec.credit), so a
model cannot be added without saying where it came from. The full
license texts live in src/mediakit/assets/licenses/ and are bundled
with the installer; `license_files` are paths relative to that folder.

Libraries are not listed here by hand: tools/collect_licenses.py reads
the installed packages and writes assets/licenses/libraries.json.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Credit:
    name: str  # what the user sees, e.g. "Real-ESRGAN x4plus"
    authors: str
    license: str  # SPDX identifier, e.g. "BSD-3-Clause"
    url: str  # upstream project
    license_files: tuple[str, ...]  # relative to assets/licenses/
    note: str = ""  # changes we made, or where the weights came from

    def short(self) -> str:
        """One line for the model panel."""
        return f"{self.name} \u00b7 {self.authors} \u00b7 {self.license}"
