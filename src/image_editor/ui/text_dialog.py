"""文字・透かしの設定ダイアログ（開いたまま調整でき、変更はすぐプレビューに反映する）。"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from image_editor.core.text import (
    TEXT_OPACITY_MAX,
    TEXT_OPACITY_MIN,
    TEXT_SIZE_MAX,
    TEXT_SIZE_MIN,
    TextFont,
    TextPosition,
    TextSettings,
)

NOTE_TEXT = (
    "大きさは写真の短辺に対する % です。「フレームの余白」はポラロイド・チェキの広い余白に"
    "入れます（フレームがなければ写真の下中央）。フレームの余白の文字は「トリミング実行」の"
    "表示で確認できます。"
)


class TextDialog(QDialog):
    """文字・透かしの設定ダイアログ。変更するたびに settings_changed を発行する。"""

    settings_changed = pyqtSignal(object)  # TextSettings

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文字・透かし")
        self._updating = False
        self._color = TextSettings().color

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("入れる文字（例: © 2026 Toshiaki）。改行もできます")
        self.text_edit.setFixedHeight(72)

        self.font_combo = QComboBox()
        for font in TextFont:
            self.font_combo.addItem(font.label, font)

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(TEXT_SIZE_MIN, TEXT_SIZE_MAX)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setDecimals(1)
        self.size_spin.setSuffix(" %")

        self.color_button = QPushButton()
        self.color_button.setFixedWidth(64)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(TEXT_OPACITY_MIN, TEXT_OPACITY_MAX)
        self.opacity_label = QLabel()
        self.opacity_label.setMinimumWidth(40)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_label)

        self.position_combo = QComboBox()
        for position in TextPosition:
            self.position_combo.addItem(position.label, position)

        form = QFormLayout()
        form.addRow("文字", self.text_edit)
        form.addRow("フォント", self.font_combo)
        form.addRow("大きさ", self.size_spin)
        form.addRow("色", self.color_button)
        form.addRow("不透明度", opacity_row)
        form.addRow("位置", self.position_combo)

        note = QLabel(NOTE_TEXT)
        note.setWordWrap(True)
        self.clear_button = QPushButton("文字を消す")
        self.close_button = QPushButton("閉じる")
        buttons = QHBoxLayout()
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.resize(420, 0)

        self.text_edit.textChanged.connect(self._emit)
        self.font_combo.currentIndexChanged.connect(lambda _: self._emit())
        self.size_spin.valueChanged.connect(lambda _: self._emit())
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.position_combo.currentIndexChanged.connect(lambda _: self._emit())
        self.color_button.clicked.connect(self._choose_color)
        self.clear_button.clicked.connect(self.text_edit.clear)
        self.close_button.clicked.connect(self.close)

        self.set_settings(TextSettings())

    def settings(self) -> TextSettings:
        """入力から設定を組み立てる。"""
        return TextSettings(
            text=self.text_edit.toPlainText(),
            font=self.font_combo.currentData(),
            size=self.size_spin.value(),
            color=self._color,
            opacity=self.opacity_slider.value(),
            position=self.position_combo.currentData(),
        )

    def set_settings(self, settings: TextSettings) -> None:
        """設定を表示に反映する（settings_changed は発行しない）。"""
        if settings == self.settings():
            return
        self._updating = True
        try:
            if self.text_edit.toPlainText() != settings.text:
                self.text_edit.setPlainText(settings.text)
            self.font_combo.setCurrentIndex(self.font_combo.findData(settings.font))
            self.size_spin.setValue(settings.size)
            self._set_color(settings.color)
            self.opacity_slider.setValue(settings.opacity)
            self.position_combo.setCurrentIndex(self.position_combo.findData(settings.position))
        finally:
            self._updating = False
        self.opacity_label.setText(f"{settings.opacity}%")

    def set_color(self, color: tuple[int, int, int]) -> None:
        """文字の色を変える（色を選ぶダイアログを経ずに設定する）。"""
        self._set_color(color)
        self._emit()

    # --- 内部 -----------------------------------------------------------------

    def _choose_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(*self._color), self, "文字の色")
        if chosen.isValid():
            self.set_color((chosen.red(), chosen.green(), chosen.blue()))

    def _set_color(self, color: tuple[int, int, int]) -> None:
        self._color = color
        r, g, b = color
        self.color_button.setStyleSheet(
            f"QPushButton {{ background-color: rgb({r}, {g}, {b}); border: 1px solid #888; }}"
        )
        self.color_button.setToolTip(f"#{r:02X}{g:02X}{b:02X}")

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_label.setText(f"{value}%")
        self._emit()

    def _emit(self) -> None:
        if not self._updating:
            self.settings_changed.emit(self.settings())
