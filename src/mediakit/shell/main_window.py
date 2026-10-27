from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from mediakit.modules.audio.hub import build_audio_hub
from mediakit.modules.image.hub import build_image_hub
from mediakit.modules.pdf.hub import build_pdf_hub
from mediakit.shell.i18n import LanguageManager
from mediakit.shell.sidebar import Sidebar
from mediakit.shell.theme import ThemeManager


class MainWindow(QMainWindow):
    def __init__(self, language_manager: LanguageManager, theme_manager: ThemeManager) -> None:
        super().__init__()
        self._languages = language_manager
        self._themes = theme_manager
        self.setWindowTitle("mediakit")
        self.resize(1100, 760)
        self.setMinimumSize(900, 640)

        self.sidebar = Sidebar()
        self.image_screen = build_image_hub()
        self.audio_screen = build_audio_hub()
        self.pdf_screen = build_pdf_hub()
        self._hubs = (self.image_screen, self.audio_screen, self.pdf_screen)

        self.stack = QStackedWidget()
        for screen in self._hubs:
            self.stack.addWidget(screen)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.sidebar.selection_changed.connect(self._on_navigate)
        self.sidebar.language_selected.connect(self._languages.set_language)
        self.sidebar.theme_toggled.connect(self._on_theme_toggled)
        self.sidebar.set_active_language(self._languages.language)
        self.sidebar.set_theme_label(self._themes.theme)

        self.retranslate()
        self.sidebar.select(0)

    def _on_navigate(self, index: int) -> None:
        # Clicking a module in the sidebar always lands on its tool grid,
        # even if a tool inside it was open. A running job keeps running.
        self.stack.setCurrentIndex(index)
        self._hubs[index].show_home()

    def retranslate(self) -> None:
        for hub in self._hubs:
            hub.retranslate()
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
