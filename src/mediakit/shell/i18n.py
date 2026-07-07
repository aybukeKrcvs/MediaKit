from importlib.resources import as_file, files

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication


class LanguageManager:
    """Aktif QTranslator'ı yönetir. set_language çağrısı Qt'ye LanguageChange yaydırır."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._translator: QTranslator | None = None
        self.language = "en"

    def set_language(self, language: str) -> None:
        # önce eskiyi kaldır (remove de LanguageChange yayar → "en"e dönüş çalışır)
        if self._translator is not None:
            self._app.removeTranslator(self._translator)
            self._translator = None

        qm = files("mediakit").joinpath("assets", "i18n", f"mediakit_{language}.qm")
        if qm.is_file():  # "en" için .qm yok → source'a düş
            translator = QTranslator(self._app)
            with as_file(qm) as qm_path:
                if translator.load(str(qm_path)):
                    self._app.installTranslator(translator)
                    self._translator = translator

        self.language = language
