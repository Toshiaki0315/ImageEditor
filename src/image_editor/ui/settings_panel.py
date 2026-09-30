"""設定パネル（サイズ変更・加工・トリミング・各ボタン）。"""

from typing import Literal

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
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

from image_editor.core.effects import (
    AGING_MAX,
    AGING_MIN,
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CONTRAST_MAX,
    CONTRAST_MIN,
    EXPOSURE_MAX,
    EXPOSURE_MIN,
    EXPOSURE_STEP,
    SATURATION_MAX,
    SATURATION_MIN,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    TEMPERATURE_NEUTRAL,
    TEMPERATURE_STEP,
    VIGNETTE_MAX,
    VIGNETTE_MIN,
)
from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType, window_aspect
from image_editor.core.pipeline import EditSettings, effective_crop
from image_editor.core.shapes import (
    CORNER_RADIUS_DEFAULT,
    CORNER_RADIUS_MAX,
    CORNER_RADIUS_MIN,
    ShapeType,
)
from image_editor.core.transform import (
    MAX_SIZE,
    MIN_SIZE,
    AspectRatio,
    CropRect,
    clamp_crop,
    constrain_rect,
    fit_aspect,
    fit_size,
)

# 未読込時に数値欄へ表示する文字（空文字だと QSpinBox の特殊表示が無効になるため空白）
BLANK_TEXT = " "
TRIM_TEXT = "トリミング実行"
EDIT_RANGE_TEXT = "範囲を編集"
# フレーム・円を選んでいるとき、比のプルダウンに表示する項目（ユーザーは選べない）
FOLLOW_FRAME_TEXT = "フレーム・円に合わせる"
FOLLOW_FRAME_DATA = "follow_frame"
# 「加工」のスライダーの最小の長さ（細かく調整しやすいよう長めにする）
SLIDER_MIN_WIDTH = 225


class SettingsPanel(QWidget):
    """編集設定を入力するパネル。入力が変わるたびに settings_changed を発行する。

    幅・高さの初期値はトリミング後のサイズ（フレームがあれば写真部分の比率に切り抜いた後の
    サイズ）で、その値のままならリサイズしない。
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
        # 最後に確定したトリミング範囲（数値入力で比の向きを決めるのに使う）
        self._committed_crop: CropRect | None = None

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
        # スライダーはダブルクリックで既定値に戻る
        self.vignette_slider, self.vignette_value_label, vignette_row = _amount_slider(
            VIGNETTE_MIN, VIGNETTE_MAX
        )
        self.aging_slider, self.aging_value_label, aging_row = _amount_slider(AGING_MIN, AGING_MAX)
        # 色温度は 100K 刻み。スライダーの値は「ケルビン ÷ 100」で持つ
        self.temperature_slider, self.temperature_value_label, temperature_row = _amount_slider(
            TEMPERATURE_MIN // TEMPERATURE_STEP,
            TEMPERATURE_MAX // TEMPERATURE_STEP,
            default=TEMPERATURE_NEUTRAL // TEMPERATURE_STEP,
        )
        self.temperature_slider.setPageStep(5)
        self.temperature_value_label.setText(_kelvin_text(TEMPERATURE_NEUTRAL))
        self.saturation_slider, self.saturation_value_label, saturation_row = _amount_slider(
            SATURATION_MIN, SATURATION_MAX
        )
        self.saturation_value_label.setText(_signed_text(0))
        self.brightness_slider, self.brightness_value_label, brightness_row = _amount_slider(
            BRIGHTNESS_MIN, BRIGHTNESS_MAX
        )
        self.brightness_value_label.setText(_signed_text(0))
        # 露出は 0.1 EV 刻み。スライダーの値は「EV × 10」で持つ
        self.exposure_slider, self.exposure_value_label, exposure_row = _amount_slider(
            round(EXPOSURE_MIN / EXPOSURE_STEP), round(EXPOSURE_MAX / EXPOSURE_STEP)
        )
        self.exposure_value_label.setText(_ev_text(0.0))
        self.contrast_slider, self.contrast_value_label, contrast_row = _amount_slider(
            CONTRAST_MIN, CONTRAST_MAX
        )
        self.contrast_value_label.setText(_signed_text(0))
        self.frame_combo = QComboBox()
        for frame_type in FrameType:
            self.frame_combo.addItem(frame_type.label, frame_type)
        self.shape_combo = QComboBox()
        for shape_type in ShapeType:
            self.shape_combo.addItem(shape_type.label, shape_type)
        # 角丸の半径（短辺に対する %）。形が角丸のときだけ操作できる
        self.corner_slider, self.corner_value_label, corner_row = _amount_slider(
            CORNER_RADIUS_MIN, CORNER_RADIUS_MAX, default=CORNER_RADIUS_DEFAULT
        )
        self.corner_slider.setPageStep(5)
        self.corner_value_label.setText(_percent_text(CORNER_RADIUS_DEFAULT))
        filter_box = QGroupBox("加工")
        filter_form = QFormLayout(filter_box)
        filter_form.addRow(self.filter_combo)
        filter_form.addRow("フレーム", self.frame_combo)
        filter_form.addRow("形", self.shape_combo)
        filter_form.addRow("角丸", corner_row)
        filter_form.addRow("露出", exposure_row)
        filter_form.addRow("明るさ", brightness_row)
        filter_form.addRow("コントラスト", contrast_row)
        filter_form.addRow("色温度", temperature_row)
        filter_form.addRow("彩度", saturation_row)
        filter_form.addRow("周辺減光", vignette_row)
        filter_form.addRow("経年劣化", aging_row)
        # テイストと色のスライダーだけを戻す（フレーム・形・角丸は切り抜きに関わるので残す）
        self.reset_adjustments_button = QPushButton("加工をリセット")
        filter_form.addRow(self.reset_adjustments_button)

        # トリミング
        self.crop_x_spin = _spin_box(0, MAX_SIZE, " px")
        self.crop_y_spin = _spin_box(0, MAX_SIZE, " px")
        self.crop_width_spin = _spin_box(0, MAX_SIZE, " px")
        self.crop_height_spin = _spin_box(0, MAX_SIZE, " px")
        self.clear_crop_button = QPushButton("範囲をクリア")
        # 押すと切り抜き後の表示に切り替わり、「範囲を編集」になる（範囲は設定として保持）
        self.trim_button = QPushButton(TRIM_TEXT)
        self.trim_button.setCheckable(True)
        # 縦横比。フレーム・円を選んでいるときはその比に固定する
        self.aspect_combo = QComboBox()
        for aspect_ratio in AspectRatio:
            self.aspect_combo.addItem(aspect_ratio.label, aspect_ratio)
        self.aspect_combo.addItem(FOLLOW_FRAME_TEXT, FOLLOW_FRAME_DATA)
        follow_item = self.aspect_combo.model().item(self.aspect_combo.count() - 1)
        follow_item.setEnabled(False)
        self._aspect_index = 0  # 固定を解いたときに戻す選択
        self.portrait_check = QCheckBox("縦向き")
        aspect_row = QHBoxLayout()
        aspect_row.addWidget(self.aspect_combo, 1)
        aspect_row.addWidget(self.portrait_check)
        crop_box = QGroupBox("トリミング")
        crop_form = QFormLayout(crop_box)
        crop_form.addRow("比", aspect_row)
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
        # フレームを変えると写真部分の比率への切り抜きが変わるので、トリミングと同じく扱う
        self.frame_combo.currentIndexChanged.connect(lambda _: self._on_aspect_source_changed())
        # 円は正方形に切り抜くので、形もトリミングと同じく扱う
        self.shape_combo.currentIndexChanged.connect(lambda _: self._on_shape_changed())
        self.corner_slider.valueChanged.connect(self._on_corner_changed)
        for name, spin in zip(("x", "y", "width", "height"), self._crop_spins(), strict=True):
            spin.valueChanged.connect(lambda _, name=name: self._on_crop_spin_edited(name))
        self.aspect_combo.currentIndexChanged.connect(lambda _: self._on_aspect_source_changed())
        self.portrait_check.toggled.connect(lambda _: self._on_aspect_source_changed())
        self.clear_crop_button.clicked.connect(self.clear_crop)
        self.trim_button.toggled.connect(self._on_trim_toggled)
        self.vignette_slider.valueChanged.connect(self._on_vignette_changed)
        self.aging_slider.valueChanged.connect(self._on_aging_changed)
        self.temperature_slider.valueChanged.connect(self._on_temperature_changed)
        self.saturation_slider.valueChanged.connect(self._on_saturation_changed)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.exposure_slider.valueChanged.connect(self._on_exposure_changed)
        self.contrast_slider.valueChanged.connect(self._on_contrast_changed)
        self.reset_adjustments_button.clicked.connect(self.reset_adjustments)
        self.save_button.clicked.connect(self.save_requested)
        self.reset_button.clicked.connect(self.reset_requested)

        self.set_image_size(None)

    # --- 公開 API -------------------------------------------------------------

    def set_image_size(self, size: tuple[int, int] | None) -> None:
        """画像のサイズを設定し、すべての設定を初期状態に戻す。None で未読込状態にする。"""
        self._image_size = size
        self._committed_crop = None
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
            self.frame_combo.setCurrentIndex(0)
            self._aspect_index = 0
            self.aspect_combo.setCurrentIndex(0)
            self.portrait_check.setChecked(False)
            self.shape_combo.setCurrentIndex(0)
            self.corner_slider.reset()
            for slider in self._adjustment_sliders():
                slider.reset()
            self.trim_button.setChecked(False)
            if size is None:
                self._set_size_spins((0, 0))  # 空欄表示
            else:
                self._set_size_spins(self.base_size())
        self._set_controls_enabled(size is not None)
        self._update_corner_enabled()
        self._update_aspect_controls()
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
            aging=self.aging_slider.value(),
            temperature=self.temperature_kelvin(),
            saturation=self.saturation_slider.value(),
            brightness=self.brightness_slider.value(),
            exposure=self.exposure_ev(),
            contrast=self.contrast_slider.value(),
            frame=self.frame(),
            shape=self.shape(),
            corner_radius=self.corner_slider.value(),
        )

    def base_size(self) -> tuple[int, int]:
        """リサイズ前のサイズを返す。

        トリミング後のサイズ（フレームがあれば写真部分の比率に切り抜いた後のサイズ）。
        切り抜かないなら原寸。
        """
        if self._image_size is None:
            return (MIN_SIZE, MIN_SIZE)
        rect = self._effective_crop()
        return (rect.width, rect.height) if rect else self._image_size

    def frame(self) -> FrameType:
        """選ばれているフレームを返す。"""
        return self.frame_combo.currentData()

    def shape(self) -> ShapeType:
        """選ばれている形を返す。"""
        return self.shape_combo.currentData()

    def crop_aspect(self) -> tuple[tuple[float, float] | None, bool]:
        """トリミング範囲に保たせる縦横比 (幅, 高さ) と、向きを自由にするかを返す。

        フレームがあれば写真部分の比（チェキは範囲の形に合わせて縦横どちらにもなる）、
        フレームなしの円は 1:1、それ以外は比のプルダウンの選択（自由なら None）。
        """
        size = self._range_size()
        aspect = self._aspect_for(size)
        free = self.frame() is not FrameType.NONE and aspect is not None and aspect[0] != aspect[1]
        return aspect, free

    def is_aspect_locked_by_frame(self) -> bool:
        """フレーム・円に合わせて比を固定しているかを返す。"""
        return self.frame() is not FrameType.NONE or self.shape() is ShapeType.CIRCLE

    def set_crop(self, rect: CropRect | None) -> None:
        """トリミング範囲を設定する（原画像の座標系）。None で解除。

        比を指定しているときは、範囲をその比に直してから設定する。
        """
        if rect is not None and self._image_size is not None:
            aspect = self._aspect_for((rect.width, rect.height))
            if aspect is not None and rect.width > 0 and rect.height > 0:
                rect = constrain_rect(rect, aspect, self._image_size)
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

    def reset_adjustments(self) -> None:
        """テイストと色のスライダー（露出〜経年劣化）を既定値に戻す。

        画像・サイズ変更・トリミング・フレーム・形・角丸はそのまま残す。変更は 1 回だけ通知する。
        """
        with self._block():
            self.filter_combo.setCurrentIndex(0)
            for slider in self._adjustment_sliders():
                slider.reset()
        self._emit_changed()

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

    def _on_aging_changed(self, value: int) -> None:
        self.aging_value_label.setText(str(value))
        self._emit_changed()

    def temperature_kelvin(self) -> int:
        """色温度スライダーの値をケルビンで返す。"""
        return self.temperature_slider.value() * TEMPERATURE_STEP

    def _on_temperature_changed(self, _value: int) -> None:
        self.temperature_value_label.setText(_kelvin_text(self.temperature_kelvin()))
        self._emit_changed()

    def _on_saturation_changed(self, value: int) -> None:
        self.saturation_value_label.setText(_signed_text(value))
        self._emit_changed()

    def _on_brightness_changed(self, value: int) -> None:
        self.brightness_value_label.setText(_signed_text(value))
        self._emit_changed()

    def exposure_ev(self) -> float:
        """露出スライダーの値を EV で返す（0.1 刻み）。"""
        return self.exposure_slider.value() / round(1 / EXPOSURE_STEP)

    def _on_exposure_changed(self, _value: int) -> None:
        self.exposure_value_label.setText(_ev_text(self.exposure_ev()))
        self._emit_changed()

    def _on_contrast_changed(self, value: int) -> None:
        self.contrast_value_label.setText(_signed_text(value))
        self._emit_changed()

    def _on_shape_changed(self) -> None:
        self._update_corner_enabled()
        self._on_aspect_source_changed()

    def _on_aspect_source_changed(self) -> None:
        """比・縦向き・フレーム・形が変わったら、比の表示を更新し、範囲をその比に直す。"""
        if self._updating:
            return
        self._update_aspect_controls()
        self._fit_range_to_aspect()
        self._on_crop_edited()

    def _update_aspect_controls(self) -> None:
        """フレーム・円を選んでいるときは比をそれに固定して操作できなくする。"""
        locked = self.is_aspect_locked_by_frame()
        follow_index = self.aspect_combo.count() - 1
        with self._block():
            if locked:
                if self.aspect_combo.currentIndex() != follow_index:
                    self._aspect_index = self.aspect_combo.currentIndex()
                self.aspect_combo.setCurrentIndex(follow_index)
            elif self.aspect_combo.currentIndex() == follow_index:
                self.aspect_combo.setCurrentIndex(self._aspect_index)
        enabled = self._image_size is not None and not locked
        self.aspect_combo.setEnabled(enabled)
        preset = self.aspect_combo.currentData()
        # 自由と 1:1 には向きがない
        has_orientation = isinstance(preset, AspectRatio) and preset not in (
            AspectRatio.FREE,
            AspectRatio.SQUARE,
        )
        self.portrait_check.setEnabled(enabled and has_orientation)

    def _aspect_for(self, size: tuple[int, int]) -> tuple[float, float] | None:
        """size の範囲に保たせる縦横比を返す（自由なら None）。"""
        frame = self.frame()
        if frame is not FrameType.NONE:
            return window_aspect(frame, size)
        if self.shape() is ShapeType.CIRCLE:
            return (1, 1)
        preset = self.aspect_combo.currentData()
        if not isinstance(preset, AspectRatio):
            return None
        return preset.ratio(portrait=self.portrait_check.isChecked())

    def _range_size(self) -> tuple[int, int]:
        """今の範囲（画像内に収めたもの）の大きさ。範囲がなければ画像の大きさ。"""
        rect = self._clamped_range()
        if rect is not None:
            return (rect.width, rect.height)
        return self._image_size or (MIN_SIZE, MIN_SIZE)

    def _clamped_range(self) -> CropRect | None:
        rect = self._crop_rect()
        if rect is None or self._image_size is None:
            return None
        return clamp_crop(rect, self._image_size)

    def _fit_range_to_aspect(self) -> None:
        """範囲があれば、その中央を今の比に合わせた範囲に直す。"""
        rect = self._clamped_range()
        if rect is None:
            return
        aspect = self._aspect_for((rect.width, rect.height))
        if aspect is None:
            return
        self._set_crop_spins(fit_aspect(rect, aspect))

    def _on_crop_spin_edited(self, name: str) -> None:
        """数値欄の変更。比を指定しているときは、もう一方の辺や位置を直して比を保つ。"""
        if self._updating:
            return
        rect = self._crop_rect()
        size = self._image_size
        previous = self._committed_crop
        aspect = self._aspect_for(
            (previous.width, previous.height) if previous else self._range_size()
        )
        width, height = self.crop_width_spin.value(), self.crop_height_spin.value()
        if aspect is not None and size is not None:
            x, y = self.crop_x_spin.value(), self.crop_y_spin.value()
            aspect_width, aspect_height = aspect
            if name == "width" and width > 0:
                height = max(MIN_SIZE, round(width * aspect_height / aspect_width))
            elif name == "height" and height > 0:
                width = max(MIN_SIZE, round(height * aspect_width / aspect_height))
            elif rect is not None:
                # 位置を変えたときは大きさを保ち、画像からはみ出す分だけ戻す
                x = min(x, max(size[0] - width, 0))
                y = min(y, max(size[1] - height, 0))
            if width > 0 and height > 0:
                fitted = constrain_rect(CropRect(x, y, width, height), aspect, size)
                if fitted is not None:
                    self._set_crop_spins(fitted)
        self._on_crop_edited()

    def _set_crop_spins(self, rect: CropRect) -> None:
        with self._block():
            self.crop_x_spin.setValue(rect.x)
            self.crop_y_spin.setValue(rect.y)
            self.crop_width_spin.setValue(rect.width)
            self.crop_height_spin.setValue(rect.height)

    def _on_corner_changed(self, value: int) -> None:
        self.corner_value_label.setText(_percent_text(value))
        self._emit_changed()

    def _update_corner_enabled(self) -> None:
        """角丸のスライダーは、画像があって形が角丸のときだけ操作できる。"""
        enabled = self._image_size is not None and self.shape() is ShapeType.ROUNDED
        self.corner_slider.setEnabled(enabled)
        self.corner_value_label.setEnabled(enabled)

    def _on_trim_toggled(self, checked: bool) -> None:
        self.trim_button.setText(EDIT_RANGE_TEXT if checked else TRIM_TEXT)
        if not self._updating:
            self.trim_view_toggled.emit(checked)

    def _update_trim_button(self) -> None:
        """トリミング範囲・フレーム・形（矩形以外）のどれかがあるときだけ「トリミング実行」を
        押せるようにする。

        どれもなくなったら全体表示に戻す。
        """
        has_crop = self._image_size is not None and (
            self._effective_crop() is not None or self.shape() is not ShapeType.RECTANGLE
        )
        if not has_crop and self.trim_button.isChecked():
            self.trim_button.setChecked(False)
        self.trim_button.setEnabled(has_crop)

    def _on_crop_edited(self) -> None:
        if self._updating:
            return
        self._committed_crop = self._clamped_range()
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
        if self._image_size is None:
            return None
        return effective_crop(self._image_size, self._crop_rect(), self.frame(), self.shape())

    def _adjustment_sliders(self) -> tuple["ResettableSlider", ...]:
        """色を変えるスライダー（「加工をリセット」で戻すもの）。"""
        return (
            self.exposure_slider,
            self.brightness_slider,
            self.contrast_slider,
            self.temperature_slider,
            self.saturation_slider,
            self.vignette_slider,
            self.aging_slider,
        )

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


def _ev_text(ev: float) -> str:
    """露出を「+1.3 EV」「-0.5 EV」「0.0 EV」のように表示する。"""
    return f"{ev:+.1f} EV" if ev else "0.0 EV"


def _signed_text(value: int) -> str:
    """0 以外は符号付きで表示する（例: +30, -50）。"""
    return f"{value:+d}" if value else "0"


def _percent_text(value: int) -> str:
    return f"{value}%"


def _kelvin_text(kelvin: int) -> str:
    return f"{kelvin} K"


class ResettableSlider(QSlider):
    """ダブルクリックで既定値に戻る横向きのスライダー。"""

    def __init__(self, default: int, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._default = default

    def default_value(self) -> int:
        """既定値を返す。"""
        return self._default

    def reset(self) -> None:
        """既定値に戻す（変われば valueChanged を発行する）。"""
        self.setValue(self._default)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.reset()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def _amount_slider(
    minimum: int, maximum: int, default: int = 0
) -> tuple[ResettableSlider, QLabel, QHBoxLayout]:
    """強さを指定するスライダーと、現在値を表示するラベルを横に並べて返す。

    スライダーは default で始まり、ダブルクリックで default に戻る。
    """
    slider = ResettableSlider(default)
    slider.setRange(minimum, maximum)
    slider.setValue(default)
    slider.setPageStep(10)
    slider.setMinimumWidth(SLIDER_MIN_WIDTH)
    label = QLabel(str(minimum))
    label.setMinimumWidth(64)  # 「10000 K」が入る幅で、各スライダーの長さをそろえる
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    row = QHBoxLayout()
    row.addWidget(slider)
    row.addWidget(label)
    return slider, label, row


def _spin_box(minimum: int, maximum: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)  # 入力確定時にだけ連動させる
    spin.setAccelerated(True)
    return spin
