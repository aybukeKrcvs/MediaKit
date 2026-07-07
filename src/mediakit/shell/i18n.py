from importlib.resources import as_file, files

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication


class LanguageManager:
    """Manages the active QTranslator. Calling set_language propagates LanguageChange to Qt."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._translator: QTranslator | None = None
        self.language = "en"

    def set_language(self, language: str) -> None:
        # Remove the old one first (remove also emits LanguageChange, so reverting to "en" works)
        if self._translator is not None:
            self._app.removeTranslator(self._translator)
            self._translator = None

        qm = files("mediakit").joinpath("assets", "i18n", f"mediakit_{language}.qm")
        if qm.is_file():  # No .qm for "en" -> falls back to source
            translator = QTranslator(self._app)
            with as_file(qm) as qm_path:
                if translator.load(str(qm_path)):
                    self._app.installTranslator(translator)
                    self._translator = translator

        self.language = language
