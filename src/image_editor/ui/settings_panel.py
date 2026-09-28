"""設定パネル（サイズ変更・加工・トリミング・各ボタン）。"""

from typing import Literal

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from image_editor.core.effects import VIGNETTE_MAX, VIGNETTE_MIN
from image_editor.core.filters import FilterType
from image_editor.core.pipeline import EditSettings
from image_editor.core.transform import MAX_SIZE, MIN_SIZE, CropRect, clamp_crop, fit_size

# 未読込時に数値欄へ表示する文字（空文字だと QSpinBox の特殊表示が無効になるため空白）
BLANK_TEXT = " "
TRIM_TEXT = "トリミング実行"
EDIT_RANGE_TEXT = "範囲を編集"


class SettingsPanel(QWidget):
    """編集設定を入力するパネル。入力が変わるたびに settings_changed を発行する。

    幅・高さの初期値はトリミング後のサイズで、その値のままならリサイズしない。
    """

    settings_changed = pyqtSignal(object)  # EditSettings
    save_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    trim_view_toggled = pyqtSignal(bool)  # True: 切り抜き後の表示、False: 全体表示

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_size: tuple[int, int] | None = None
        # ユーザーが幅・高さを手で変えたか。変えていなければトリミング範囲に追従する
        self._size_edited = False
        # 縦横比保持時に基準にする側（最後に編集した側）
        self._last_edited: Literal["width", "height"] = "width"
        self._updating = False

        # サイズ変更
        self.width_spin = _spin_box(MIN_SIZE, MAX_SIZE, " px")
        self.height_spin = _spin_box(MIN_SIZE, MAX_SIZE, " px")
        self.keep_aspect_check = QCheckBox("縦横比を保持")
        self.keep_aspect_check.setChecked(True)
        size_box = QGroupBox("サイズ変更")
        size_form = QFormLayout(size_box)
        size_form.addRow("幅", self.width_spin)
        size_form.addRow("高さ", self.height_spin)
        size_form.addRow(self.keep_aspect_check)

        # 加工
        self.filter_combo = QComboBox()
        for filter_type in FilterType:
            self.filter_combo.addItem(filter_type.label, filter_type)
        self.vignette_slider = QSlider(Qt.Orientation.Horizontal)
        self.vignette_slider.setRange(VIGNETTE_MIN, VIGNETTE_MAX)
        self.vignette_slider.setPageStep(10)
        self.vignette_value_label = QLabel("0")
        self.vignette_value_label.setMinimumWidth(28)
        self.vignette_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        vignette_row = QHBoxLayout()
        vignette_row.addWidget(self.vignette_slider)
        vignette_row.addWidget(self.vignette_value_label)
        filter_box = QGroupBox("加工")
        filter_form = QFormLayout(filter_box)
        filter_form.addRow(self.filter_combo)
        filter_form.addRow("周辺減光", vignette_row)

        # トリミング
        self.crop_x_spin = _spin_box(0, MAX_SIZE, " px")
        self.crop_y_spin = _spin_box(0, MAX_SIZE, " px")
        self.crop_width_spin = _spin_box(0, MAX_SIZE, " px")
        self.crop_height_spin = _spin_box(0, MAX_SIZE, " px")
        self.clear_crop_button = QPushButton("範囲をクリア")
        # 押すと切り抜き後の表示に切り替わり、「範囲を編集」になる（範囲は設定として保持）
        self.trim_button = QPushButton(TRIM_TEXT)
        self.trim_button.setCheckable(True)
        crop_box = QGroupBox("トリミング")
        crop_form = QFormLayout(crop_box)
        crop_form.addRow("X", self.crop_x_spin)
        crop_form.addRow("Y", self.crop_y_spin)
        crop_form.addRow("幅", self.crop_width_spin)
        crop_form.addRow("高さ", self.crop_height_spin)
        crop_buttons = QHBoxLayout()
        crop_buttons.addWidget(self.clear_crop_button)
        crop_buttons.addWidget(self.trim_button)
        crop_form.addRow(crop_buttons)

        # ボタン（プレビューは設定の変更に合わせて自動で更新するので、更新ボタンは置かない）
        self.save_button = QPushButton("保存")
        self.reset_button = QPushButton("リセット")
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reset_button)

        layout = QVBoxLayout(self)
        layout.addWidget(size_box)
        layout.addWidget(filter_box)
        layout.addWidget(crop_box)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self.width_spin.valueChanged.connect(lambda _: self._on_size_edited("width"))
        self.height_spin.valueChanged.connect(lambda _: self._on_size_edited("height"))
        self.keep_aspect_check.toggled.connect(self._on_keep_aspect_toggled)
        self.filter_combo.currentIndexChanged.connect(lambda _: self._emit_changed())
        for spin in self._crop_spins():
            spin.valueChanged.connect(lambda _: self._on_crop_edited())
        self.clear_crop_button.clicked.connect(self.clear_crop)
        self.trim_button.toggled.connect(self._on_trim_toggled)
        self.vignette_slider.valueChanged.connect(self._on_vignette_changed)
        self.save_button.clicked.connect(self.save_requested)
        self.reset_button.clicked.connect(self.reset_requested)

        self.set_image_size(None)

    # --- 公開 API -------------------------------------------------------------

    def set_image_size(self, size: tuple[int, int] | None) -> None:
        """画像のサイズを設定し、すべての設定を初期状態に戻す。None で未読込状態にする。"""
        self._image_size = size
        self._size_edited = False
        self._last_edited = "width"
        with self._block():
            self._show_blank(size is None)
            width, height = size or (MIN_SIZE, MIN_SIZE)
            self.crop_x_spin.setMaximum(max(0, width - 1))
            self.crop_y_spin.setMaximum(max(0, height - 1))
            self.crop_width_spin.setMaximum(width)
            self.crop_height_spin.setMaximum(height)
            for spin in self._crop_spins():
                spin.setValue(0)
            self.keep_aspect_check.setChecked(True)
            self.filter_combo.setCurrentIndex(0)
            self.vignette_slider.setValue(0)
            self.trim_button.setChecked(False)
            if size is None:
                self._set_size_spins((0, 0))  # 空欄表示
            else:
                self._set_size_spins(self.base_size())
        self._set_controls_enabled(size is not None)
        self._update_trim_button()
        self._emit_changed()

    def settings(self) -> EditSettings:
        """現在の入力から EditSettings を組み立てる。未読込なら既定値を返す。"""
        if self._image_size is None:
            return EditSettings()
        crop = self._crop_rect()
        keep_aspect = self.keep_aspect_check.isChecked()
        width: int | None = self.width_spin.value()
        height: int | None = self.height_spin.value()
        if (width, height) == self.base_size():
            width = height = None
        elif keep_aspect:
            # 最後に編集した側だけを渡し、他方は縦横比から計算させる（表示値と一致する）
            if self._last_edited == "width":
                height = None
            else:
                width = None
        return EditSettings(
            crop=crop,
            width=width,
            height=height,
            keep_aspect=keep_aspect,
            filter=self.filter_combo.currentData(),
            vignette=self.vignette_slider.value(),
        )

    def base_size(self) -> tuple[int, int]:
        """リサイズ前のサイズ（トリミング後のサイズ。トリミングなしなら原寸）を返す。"""
        if self._image_size is None:
            return (MIN_SIZE, MIN_SIZE)
        rect = self._effective_crop()
        return (rect.width, rect.height) if rect else self._image_size

    def set_crop(self, rect: CropRect | None) -> None:
        """トリミング範囲を設定する（原画像の座標系）。None で解除。"""
        rect = rect or CropRect(0, 0, 0, 0)
        with self._block():
            self.crop_x_spin.setValue(rect.x)
            self.crop_y_spin.setValue(rect.y)
            self.crop_width_spin.setValue(rect.width)
            self.crop_height_spin.setValue(rect.height)
        self._on_crop_edited()

    def clear_crop(self) -> None:
        """トリミングを解除する。"""
        self.set_crop(None)

    def is_trim_view(self) -> bool:
        """切り抜き後の表示（「トリミング実行」が押された状態）かを返す。"""
        return self.trim_button.isChecked()

    def set_trim_view(self, enabled: bool) -> None:
        """切り抜き後の表示を切り替える（変化すれば trim_view_toggled を発行）。"""
        if enabled and not self.trim_button.isEnabled():
            return
        self.trim_button.setChecked(enabled)

    def set_busy(self, busy: bool) -> None:
        """処理中はボタンを無効化する。"""
        enabled = not busy and self._image_size is not None
        for button in (self.save_button, self.reset_button):
            button.setEnabled(enabled)

    # --- 内部 -----------------------------------------------------------------

    def _on_size_edited(self, side: Literal["width", "height"]) -> None:
        if self._updating:
            return
        self._size_edited = True
        self._last_edited = side
        if self.keep_aspect_check.isChecked():
            self._sync_aspect()
        self._emit_changed()

    def _on_keep_aspect_toggled(self, checked: bool) -> None:
        if self._updating:
            return
        if checked:
            self._sync_aspect()
        self._emit_changed()

    def _on_vignette_changed(self, value: int) -> None:
        self.vignette_value_label.setText(str(value))
        self._emit_changed()

    def _on_trim_toggled(self, checked: bool) -> None:
        self.trim_button.setText(EDIT_RANGE_TEXT if checked else TRIM_TEXT)
        if not self._updating:
            self.trim_view_toggled.emit(checked)

    def _update_trim_button(self) -> None:
        """トリミング範囲があるときだけ「トリミング実行」を押せるようにする。

        範囲がなくなったら全体表示に戻す。
        """
        has_crop = self._image_size is not None and self._effective_crop() is not None
        if not has_crop and self.trim_button.isChecked():
            self.trim_button.setChecked(False)
        self.trim_button.setEnabled(has_crop)

    def _on_crop_edited(self) -> None:
        if self._updating:
            return
        base = self.base_size()
        if not self._size_edited:
            with self._block():
                self._set_size_spins(base)
        elif self.keep_aspect_check.isChecked():
            self._sync_aspect()
        self._emit_changed()

    def _sync_aspect(self) -> None:
        """最後に編集した側を基準に、もう片方を縦横比から計算して表示する。"""
        base = self.base_size()
        if self._last_edited == "width":
            size = fit_size(base, self.width_spin.value(), None, keep_aspect=True)
        else:
            size = fit_size(base, None, self.height_spin.value(), keep_aspect=True)
        with self._block():
            self._set_size_spins(size)

    def _show_blank(self, blank: bool) -> None:
        """未読込時は数値欄を空欄で表示する。

        幅・高さは最小値を 0 にして 0 を空欄で表示し、読み込み後は最小値を 1 に戻す
        （1 px は有効な値なので空欄にならない）。トリミング欄の 0 は読み込み後は表示する。
        """
        text = BLANK_TEXT if blank else ""
        for spin in (self.width_spin, self.height_spin):
            spin.setMinimum(0 if blank else MIN_SIZE)
            spin.setSpecialValueText(text)
        for spin in self._crop_spins():
            spin.setSpecialValueText(text)

    def _set_size_spins(self, size: tuple[int, int]) -> None:
        # 計算結果が上限を超える場合は上限に丸める（QSpinBox の範囲外は設定できない）
        self.width_spin.setValue(min(size[0], MAX_SIZE))
        self.height_spin.setValue(min(size[1], MAX_SIZE))

    def _crop_rect(self) -> CropRect | None:
        width, height = self.crop_width_spin.value(), self.crop_height_spin.value()
        if width <= 0 or height <= 0:
            return None
        return CropRect(self.crop_x_spin.value(), self.crop_y_spin.value(), width, height)

    def _effective_crop(self) -> CropRect | None:
        rect = self._crop_rect()
        if rect is None or self._image_size is None:
            return None
        return clamp_crop(rect, self._image_size)

    def _crop_spins(self) -> tuple[QSpinBox, ...]:
        return (self.crop_x_spin, self.crop_y_spin, self.crop_width_spin, self.crop_height_spin)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in self.findChildren(QWidget):
            widget.setEnabled(enabled)

    def _emit_changed(self) -> None:
        if not self._updating:
            self._update_trim_button()
            self.settings_changed.emit(self.settings())

    def _block(self) -> "_Updating":
        return _Updating(self)


class _Updating:
    """プログラムから値を変える間、連動処理とシグナル発行を止める。"""

    def __init__(self, panel: SettingsPanel) -> None:
        self._panel = panel
        self._previous = False

    def __enter__(self) -> None:
        self._previous = self._panel._updating
        self._panel._updating = True

    def __exit__(self, *exc: object) -> None:
        self._panel._updating = self._previous


def _spin_box(minimum: int, maximum: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)  # 入力確定時にだけ連動させる
    spin.setAccelerated(True)
    return spin
