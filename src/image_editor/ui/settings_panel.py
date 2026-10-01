"""設定パネル（サイズ変更・加工・トリミング・各ボタン）。"""

from typing import Literal

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QTabBar,
    QTabWidget,
    QToolButton,
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
    DETAIL_MAX,
    DETAIL_MIN,
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
from image_editor.core.frames import FrameType
from image_editor.core.io import (
    DEFAULT_JPEG_QUALITY,
    JPEG_QUALITY_MAX,
    JPEG_QUALITY_MIN,
    SaveOptions,
)
from image_editor.core.pipeline import EditSettings
from image_editor.core.presets import Preset
from image_editor.core.shapes import (
    CORNER_RADIUS_DEFAULT,
    CORNER_RADIUS_MAX,
    CORNER_RADIUS_MIN,
    ShapeType,
)
from image_editor.core.text import TextSettings
from image_editor.core.transform import (
    MAX_SIZE,
    MIN_SIZE,
    AspectRatio,
    CropRect,
    Orientation,
    OrientOp,
    fit_size,
)
from image_editor.ui.panel_crop import CropMixin
from image_editor.ui.panel_parts import (  # noqa: F401 - PanelState は外からも使う
    BLANK_TEXT,
    EDIT_RANGE_TEXT,
    FOLLOW_FRAME_DATA,
    FOLLOW_FRAME_TEXT,
    PANEL_MARGIN,
    PANEL_SPACING,
    SLIDER_MIN_WIDTH,
    TAB_ADJUST_TEXT,
    TAB_CROP_TEXT,
    TAB_OUTPUT_TEXT,
    TRIM_TEXT,
    PanelState,
    ResettableSlider,
    Updating,
    amount_slider,
    ev_text,
    kelvin_text,
    percent_text,
    signed_text,
    spin_box,
    tab_page,
)
from image_editor.ui.panel_state import StateMixin


class SettingsPanel(CropMixin, StateMixin, QWidget):
    """編集設定を入力するパネル。入力が変わるたびに settings_changed を発行する。

    幅・高さの初期値はトリミング後のサイズ（フレームがあれば写真部分の比率に切り抜いた後の
    サイズ）で、その値のままならリサイズしない。
    """

    settings_changed = pyqtSignal(object)  # EditSettings
    save_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    save_options_changed = pyqtSignal(object)  # SaveOptions
    tab_changed = pyqtSignal(int)  # 開いたタブの番号
    compare_toggled = pyqtSignal(bool)  # 「加工前」ボタンを押している間だけ True
    preset_save_requested = pyqtSignal()  # 「今の加工を保存…」
    preset_delete_requested = pyqtSignal(str)  # 削除するプリセットの名前
    text_dialog_requested = pyqtSignal()  # 「文字…」
    trim_view_toggled = pyqtSignal(bool)  # True: 切り抜き後の表示、False: 全体表示

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_size: tuple[int, int] | None = None
        self._orientation = Orientation()
        # ユーザーが幅・高さを手で変えたか。変えていなければトリミング範囲に追従する
        self._size_edited = False
        # 縦横比保持時に基準にする側（最後に編集した側）
        self._last_edited: Literal["width", "height"] = "width"
        self._updating = False
        # 最後に確定したトリミング範囲（数値入力で比の向きを決めるのに使う）
        self._committed_crop: CropRect | None = None

        # サイズ変更
        self.width_spin = spin_box(MIN_SIZE, MAX_SIZE, " px")
        self.height_spin = spin_box(MIN_SIZE, MAX_SIZE, " px")
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
        self.vignette_slider, self.vignette_value_label, vignette_row = amount_slider(
            VIGNETTE_MIN, VIGNETTE_MAX
        )
        self.aging_slider, self.aging_value_label, aging_row = amount_slider(AGING_MIN, AGING_MAX)
        # 色温度は 100K 刻み。スライダーの値は「ケルビン ÷ 100」で持つ
        self.temperature_slider, self.temperature_value_label, temperature_row = amount_slider(
            TEMPERATURE_MIN // TEMPERATURE_STEP,
            TEMPERATURE_MAX // TEMPERATURE_STEP,
            default=TEMPERATURE_NEUTRAL // TEMPERATURE_STEP,
        )
        self.temperature_slider.setPageStep(5)
        self.temperature_value_label.setText(kelvin_text(TEMPERATURE_NEUTRAL))
        self.saturation_slider, self.saturation_value_label, saturation_row = amount_slider(
            SATURATION_MIN, SATURATION_MAX
        )
        self.saturation_value_label.setText(signed_text(0))
        self.brightness_slider, self.brightness_value_label, brightness_row = amount_slider(
            BRIGHTNESS_MIN, BRIGHTNESS_MAX
        )
        self.brightness_value_label.setText(signed_text(0))
        # 露出は 0.1 EV 刻み。スライダーの値は「EV × 10」で持つ
        self.exposure_slider, self.exposure_value_label, exposure_row = amount_slider(
            round(EXPOSURE_MIN / EXPOSURE_STEP), round(EXPOSURE_MAX / EXPOSURE_STEP)
        )
        self.exposure_value_label.setText(ev_text(0.0))
        self.contrast_slider, self.contrast_value_label, contrast_row = amount_slider(
            CONTRAST_MIN, CONTRAST_MAX
        )
        self.contrast_value_label.setText(signed_text(0))
        self.frame_combo = QComboBox()
        for frame_type in FrameType:
            self.frame_combo.addItem(frame_type.label, frame_type)
        self.shape_combo = QComboBox()
        for shape_type in ShapeType:
            self.shape_combo.addItem(shape_type.label, shape_type)
        # 角丸の半径（短辺に対する %）。形が角丸のときだけ操作できる
        self.corner_slider, self.corner_value_label, corner_row = amount_slider(
            CORNER_RADIUS_MIN, CORNER_RADIUS_MAX, default=CORNER_RADIUS_DEFAULT
        )
        self.corner_slider.setPageStep(5)
        self.corner_value_label.setText(percent_text(CORNER_RADIUS_DEFAULT))
        # プリセット・文字はテイストと同じ行に置く
        self.preset_menu = QMenu(self)
        self.preset_button = QToolButton()
        self.preset_button.setText("プリセット")
        self.preset_button.setMenu(self.preset_menu)
        self.preset_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._presets: list[Preset] = []
        self.set_presets([])
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.filter_combo, 1)
        filter_row.addWidget(self.preset_button)
        # 文字・透かしは専用のダイアログで設定する
        self.text_button = QToolButton()
        self.text_button.setText("文字…")
        self.text_button.setToolTip("文字・透かしを入れる（⌘T）")
        filter_row.addWidget(self.text_button)
        self._text = TextSettings()
        filter_box = QGroupBox("加工")
        filter_form = QFormLayout(filter_box)
        filter_form.addRow(filter_row)
        filter_form.addRow("露出", exposure_row)
        filter_form.addRow("明るさ", brightness_row)
        filter_form.addRow("コントラスト", contrast_row)
        filter_form.addRow("色温度", temperature_row)
        filter_form.addRow("彩度", saturation_row)
        filter_form.addRow("周辺減光", vignette_row)
        filter_form.addRow("経年劣化", aging_row)

        # ディテール（シャープ・ぼかし・ノイズ除去）
        self.sharpen_slider, self.sharpen_value_label, sharpen_row = amount_slider(
            DETAIL_MIN, DETAIL_MAX
        )
        self.blur_slider, self.blur_value_label, blur_row = amount_slider(DETAIL_MIN, DETAIL_MAX)
        self.denoise_slider, self.denoise_value_label, denoise_row = amount_slider(
            DETAIL_MIN, DETAIL_MAX
        )
        detail_box = QGroupBox("ディテール")
        detail_form = QFormLayout(detail_box)
        detail_form.addRow("シャープ", sharpen_row)
        detail_form.addRow("ぼかし", blur_row)
        detail_form.addRow("ノイズ除去", denoise_row)
        # テイスト・色・ディテールだけを戻す（フレーム・形・角丸は切り抜きに関わるので残す）
        self.reset_adjustments_button = QPushButton("加工をリセット")

        # フレーム・形
        frame_box = QGroupBox("フレーム・形")
        frame_form = QFormLayout(frame_box)
        frame_form.addRow("フレーム", self.frame_combo)
        frame_form.addRow("形", self.shape_combo)
        frame_form.addRow("角丸", corner_row)

        # 回転・反転（表示中の向きに対して行う）
        self.rotate_left_button = QPushButton("左に回転")
        self.rotate_right_button = QPushButton("右に回転")
        self.flip_horizontal_button = QPushButton("左右反転")
        self.flip_vertical_button = QPushButton("上下反転")
        orient_box = QGroupBox("回転・反転")
        orient_row = QHBoxLayout(orient_box)
        for button in self._orient_buttons():
            orient_row.addWidget(button)

        # トリミング
        self.crop_x_spin = spin_box(0, MAX_SIZE, " px")
        self.crop_y_spin = spin_box(0, MAX_SIZE, " px")
        self.crop_width_spin = spin_box(0, MAX_SIZE, " px")
        self.crop_height_spin = spin_box(0, MAX_SIZE, " px")
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

        # 保存の設定（画像ごとには戻さない。アプリを終了しても残すのはメインウィンドウ側）
        self.quality_slider, self.quality_value_label, quality_row = amount_slider(
            JPEG_QUALITY_MIN, JPEG_QUALITY_MAX, default=DEFAULT_JPEG_QUALITY
        )
        self.quality_value_label.setText(str(DEFAULT_JPEG_QUALITY))
        self.keep_exif_check = QCheckBox("撮影情報 (EXIF) を残す")
        self.keep_exif_check.setToolTip("撮影日時・カメラなど。JPEG・PNG・TIFF で保存するとき")
        self.keep_exif_check.setChecked(True)
        self.keep_gps_check = QCheckBox("位置情報 (GPS) も残す")
        save_box = QGroupBox("保存の設定")
        save_form = QFormLayout(save_box)
        save_form.addRow("JPEG 品質", quality_row)
        save_form.addRow(self.keep_exif_check)
        save_form.addRow(self.keep_gps_check)

        # ボタン（どのタブでも出す。プレビューは設定の変更に合わせて自動で更新する）
        self.save_button = QPushButton("保存")
        self.reset_button = QPushButton("リセット")
        # 押している間だけ加工前の画像を表示する（\ キーでも同じ）
        self.compare_button = QPushButton("加工前")
        self.compare_button.setToolTip("押している間だけ加工前の画像を表示します（\\ キー）")
        buttons = QHBoxLayout()
        buttons.addWidget(self.compare_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reset_button)

        # タブ: 加工／切り抜き／出力
        self.tabs = QTabWidget()
        self.tabs.addTab(
            tab_page(filter_box, detail_box, self.reset_adjustments_button), TAB_ADJUST_TEXT
        )
        self.tabs.addTab(tab_page(frame_box, orient_box, crop_box), TAB_CROP_TEXT)
        self.tabs.addTab(tab_page(size_box, save_box), TAB_OUTPUT_TEXT)

        layout = QVBoxLayout(self)
        layout.setSpacing(PANEL_SPACING)
        # 左右はスタイルの既定値のまま（組み立て中に contentsMargins() を読むと、スタイルが
        # 決める値ではなく Qt の既定値 (11px) が返り、パネルの最小幅が広がってしまう）
        style = self.style()
        left = style.pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin) if style else 9
        right = style.pixelMetric(QStyle.PixelMetric.PM_LayoutRightMargin) if style else 9
        layout.setContentsMargins(left, PANEL_MARGIN, right, PANEL_MARGIN)
        layout.addWidget(self.tabs, 1)
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
        for button, op in zip(self._orient_buttons(), OrientOp, strict=True):
            button.clicked.connect(lambda _, op=op: self.apply_orientation(op))
        self.tabs.currentChanged.connect(self.tab_changed)
        for slider, label in (
            (self.sharpen_slider, self.sharpen_value_label),
            (self.blur_slider, self.blur_value_label),
            (self.denoise_slider, self.denoise_value_label),
        ):
            slider.valueChanged.connect(
                lambda value, label=label: self._on_detail_changed(label, value)
            )
        self.quality_slider.valueChanged.connect(self._on_quality_changed)
        self.keep_exif_check.toggled.connect(lambda _: self._on_save_options_changed())
        self.keep_gps_check.toggled.connect(lambda _: self._on_save_options_changed())
        self.text_button.clicked.connect(self.text_dialog_requested)
        self.save_button.clicked.connect(self.save_requested)
        self.reset_button.clicked.connect(self.reset_requested)
        self.compare_button.pressed.connect(lambda: self.compare_toggled.emit(True))
        self.compare_button.released.connect(lambda: self.compare_toggled.emit(False))

        self.set_image_size(None)

    # --- 公開 API -------------------------------------------------------------

    def set_image_size(self, size: tuple[int, int] | None) -> None:
        """画像のサイズを設定し、すべての設定を初期状態に戻す。None で未読込状態にする。"""
        # _image_size は回転・反転した後の大きさ（トリミング範囲の座標系）
        self._image_size = size
        self._orientation = Orientation()
        self._committed_crop = None
        self._size_edited = False
        self._last_edited = "width"
        with self._block():
            self._show_blank(size is None)
            self._set_crop_limits(size or (MIN_SIZE, MIN_SIZE))
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
            self._text = TextSettings()
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
        self._update_gps_enabled()
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
            orientation=self._orientation,
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
            sharpen=self.sharpen_slider.value(),
            blur=self.blur_slider.value(),
            denoise=self.denoise_slider.value(),
            frame=self.frame(),
            shape=self.shape(),
            corner_radius=self.corner_slider.value(),
            text=self._text,
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

    def save_options(self) -> SaveOptions:
        """保存の設定（JPEG 品質・EXIF・位置情報）を返す。"""
        return SaveOptions(
            quality=self.quality_slider.value(),
            keep_exif=self.keep_exif_check.isChecked(),
            keep_gps=self.keep_gps_check.isChecked(),
        )

    def set_save_options(self, options: SaveOptions) -> None:
        """保存の設定を表示に反映する（save_options_changed は発行しない）。"""
        with self._block():
            quality = min(max(options.quality, JPEG_QUALITY_MIN), JPEG_QUALITY_MAX)
            self.quality_slider.setValue(quality)
            self.quality_value_label.setText(str(quality))
            self.keep_exif_check.setChecked(options.keep_exif)
            self.keep_gps_check.setChecked(options.keep_gps)
        self._update_gps_enabled()

    def current_tab(self) -> int:
        """開いているタブの番号（0: 加工、1: 切り抜き、2: 出力）を返す。"""
        return self.tabs.currentIndex()

    def set_current_tab(self, index: int) -> None:
        """タブを開く（範囲外の番号は無視する）。"""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

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
        self.temperature_value_label.setText(kelvin_text(self.temperature_kelvin()))
        self._emit_changed()

    def _on_saturation_changed(self, value: int) -> None:
        self.saturation_value_label.setText(signed_text(value))
        self._emit_changed()

    def _on_brightness_changed(self, value: int) -> None:
        self.brightness_value_label.setText(signed_text(value))
        self._emit_changed()

    def exposure_ev(self) -> float:
        """露出スライダーの値を EV で返す（0.1 刻み）。"""
        return self.exposure_slider.value() / round(1 / EXPOSURE_STEP)

    def _on_exposure_changed(self, _value: int) -> None:
        self.exposure_value_label.setText(ev_text(self.exposure_ev()))
        self._emit_changed()

    def _on_contrast_changed(self, value: int) -> None:
        self.contrast_value_label.setText(signed_text(value))
        self._emit_changed()

    def _on_shape_changed(self) -> None:
        self._update_corner_enabled()
        self._on_aspect_source_changed()

    def _on_corner_changed(self, value: int) -> None:
        self.corner_value_label.setText(percent_text(value))
        self._emit_changed()

    def _update_corner_enabled(self) -> None:
        """角丸のスライダーは、画像があって形が角丸のときだけ操作できる。"""
        enabled = self._image_size is not None and self.shape() is ShapeType.ROUNDED
        self.corner_slider.setEnabled(enabled)
        self.corner_value_label.setEnabled(enabled)

    def _on_quality_changed(self, value: int) -> None:
        self.quality_value_label.setText(str(value))
        self._on_save_options_changed()

    def _on_detail_changed(self, label: QLabel, value: int) -> None:
        label.setText(str(value))
        self._emit_changed()

    def _on_save_options_changed(self) -> None:
        self._update_gps_enabled()
        if not self._updating:
            self.save_options_changed.emit(self.save_options())

    def _update_gps_enabled(self) -> None:
        """位置情報は、画像があって EXIF を残すときだけ選べる。"""
        enabled = self._image_size is not None and self.keep_exif_check.isChecked()
        self.keep_gps_check.setEnabled(enabled)

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
            self.sharpen_slider,
            self.blur_slider,
            self.denoise_slider,
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in self.findChildren(QWidget):
            # メニューは開くボタンの有効・無効で決まるので触らない（QMenu を有効にすると、
            # 項目ごとに決めたサブメニューの有効・無効が上書きされてしまう）。タブは画像が
            # なくても切り替えられるようにする
            if not isinstance(widget, QMenu | QTabWidget | QTabBar):
                widget.setEnabled(enabled)

    def _emit_changed(self) -> None:
        if not self._updating:
            self._update_trim_button()
            self.settings_changed.emit(self.settings())

    def _block(self) -> "Updating":
        return Updating(self)
