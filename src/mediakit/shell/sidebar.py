from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QLabel, QPushButton, QVBoxLayout, QWidget


class Sidebar(QWidget):
    selection_changed = Signal(int)  # modül navigasyonu
    language_selected = Signal(str)  # "tr" / "en"
    theme_toggled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(206)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 10)
        layout.setSpacing(0)

        # --- modül nav ---
        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        for index in range(3):  # IMAGE, AUDIO, PDF
            layout.addWidget(self._make_nav_button(index))
        self._nav.idClicked.connect(self.selection_changed)

        layout.addStretch()  # footer'ı en alta iter

        # --- footer: ayarlar başlığı + dil listesi ---
        self._footer_label = QLabel()
        self._footer_label.setObjectName("FooterLabel")
        layout.addWidget(self._footer_label)

        self._lang = QButtonGroup(self)  # nav'dan AYRI grup
        self._lang.setExclusive(True)
        self._lang_codes: dict[int, str] = {}
        for name, code in (("Türkçe", "tr"), ("English", "en")):
            button = QPushButton(name)  # endonym → asla çevrilmez
            button.setObjectName("LangButton")
            button.setCheckable(True)
            btn_id = len(self._lang_codes)
            self._lang.addButton(button, btn_id)
            self._lang_codes[btn_id] = code
            layout.addWidget(button)
        self._lang.idClicked.connect(self._emit_language)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("ThemeButton")
        layout.addWidget(self.theme_button)
        self.theme_button.clicked.connect(self._toggle_theme)
        self.retranslate()

    def _make_nav_button(self, index: int) -> QPushButton:
        button = QPushButton()
        button.setObjectName("NavButton")
        button.setCheckable(True)
        self._nav.addButton(button, index)
        return button

    def _emit_language(self, btn_id: int) -> None:
        self.language_selected.emit(self._lang_codes[btn_id])

    def set_active_language(self, code: str) -> None:
        for btn_id, current in self._lang_codes.items():
            if current == code:
                self._lang.button(btn_id).setChecked(True)

    def _toggle_theme(self) -> None:
        self.theme_toggled.emit()

    def set_theme_label(self, theme: str) -> None:
        # butonun üstünde GİDİLECEK tema yazar (bir switch mantığı)
        if theme == "dark":
            self.theme_button.setText(self.tr("☾  DARK"))
        else:
            self.theme_button.setText(self.tr("☀  LIGHT"))

    def retranslate(self) -> None:
        self._nav.button(0).setText(self.tr("IMAGE"))
        self._nav.button(1).setText(self.tr("AUDIO"))
        self._nav.button(2).setText(self.tr("PDF"))
        self._footer_label.setText(self.tr("SETTINGS"))

    def select(self, index: int) -> None:
        button = self._nav.button(index)
        if button is not None:
            button.setChecked(True)
            self.selection_changed.emit(index)
