from importlib.resources import files
from string import Template

from PySide6.QtWidgets import QApplication

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0E0D0B",
        "panel": "#15110B",
        "panel2": "#1C1712",
        "hover": "#231D14",
        "line": "#33302A",
        "ink": "#E8E2D4",
        "muted": "#8A8477",
        "faint": "#55514A",
        "amber": "#FFB000",
    },
    "light": {
        "bg": "#EDE8DC",
        "panel": "#E3DCCB",
        "panel2": "#D8CFBA",
        "hover": "#D0C6AE",
        "line": "#C2B79E",
        "ink": "#2B2620",
        "muted": "#6E6656",
        "faint": "#9C9179",
        "amber": "#9A5B00",
    },
}


class ThemeManager:
    def __init__(self, app: QApplication) -> None:
        self._app = app
        template_file = files("mediakit").joinpath("assets", "themes", "retro.qss.tmpl")
        raw = template_file.read_text(encoding="utf-8")
        self._template = Template(raw)
        self.theme = "dark"

    def set_theme(self, theme: str) -> None:
        palette = PALETTES[theme]
        self._app.setStyleSheet(self._template.substitute(palette))  # $bg → #0E0D0B
        self.theme = theme
