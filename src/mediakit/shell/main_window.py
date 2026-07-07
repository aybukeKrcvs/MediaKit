from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from mediakit.shell.i18n import LanguageManager
from mediakit.shell.placeholder import PlaceholderScreen
from mediakit.shell.sidebar import Sidebar
from mediakit.shell.theme import ThemeManager


class MainWindow(QMainWindow):
    def __init__(self, language_manager: LanguageManager, theme_manager: ThemeManager) -> None:
        super().__init__()
        self._languages = language_manager
        self._themes = theme_manager
        self.setWindowTitle("mediakit")
        self.resize(900, 600)

        self.sidebar = Sidebar()
        self.image_screen = PlaceholderScreen()
        self.audio_screen = PlaceholderScreen()
        self.pdf_screen = PlaceholderScreen()

        self.stack = QStackedWidget()
        for screen in (self.image_screen, self.audio_screen, self.pdf_screen):
            self.stack.addWidget(screen)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.sidebar.selection_changed.connect(self.stack.setCurrentIndex)
        self.sidebar.language_selected.connect(self._languages.set_language)
        self.sidebar.theme_toggled.connect(self._on_theme_toggled)
        self.sidebar.set_active_language(self._languages.language)
        self.sidebar.set_theme_label(self._themes.theme)

        self.retranslate()
        self.sidebar.select(0)

    def retranslate(self) -> None:
        self.image_screen.set_content(
            self.tr("IMAGE TOOLS"), self.tr("format · resize · compress · upscale")
        )
        self.audio_screen.set_content(
            self.tr("AUDIO & SPEECH"), self.tr("transcribe · denoise · convert · TTS")
        )
        self.pdf_screen.set_content(
            self.tr("PDF TOOLS"), self.tr("merge · split · convert · secure")
        )
        self.sidebar.retranslate()
        self.sidebar.set_theme_label(self._themes.theme)

    def _on_theme_toggled(self) -> None:
        new_theme = "light" if self._themes.theme == "dark" else "dark"
        self._themes.set_theme(new_theme)  # stylesheet is reapplied -> change is instant
        self.sidebar.set_theme_label(new_theme)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)
