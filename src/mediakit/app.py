import sys

from PySide6.QtWidgets import QApplication

from mediakit.shell.i18n import LanguageManager
from mediakit.shell.main_window import MainWindow
from mediakit.shell.theme import ThemeManager

DEFAULT_LANGUAGE = "en"
DEFAULT_THEME = "light"


def main() -> int:
    app = QApplication(sys.argv)

    themes = ThemeManager(app)
    themes.set_theme(DEFAULT_THEME)  # QSS'i uygula (setStyleSheet burada)

    languages = LanguageManager(app)
    languages.set_language(DEFAULT_LANGUAGE)

    window = MainWindow(languages, themes)
    window.show()

    return app.exec()
