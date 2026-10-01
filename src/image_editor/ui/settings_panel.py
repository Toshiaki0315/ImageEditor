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

from image_editor.core.diorama import (
    DIORAMA_BLUR_MAX,
    DIORAMA_BLUR_MIN,
    DIORAMA_POSITION_DEFAULT,
    DIORAMA_POSITION_MAX,
    DIORAMA_POSITION_MIN,
    DIORAMA_VIVID_DEFAULT,
    DIORAMA_VIVID_MAX,
    DIORAMA_VIVID_MIN,
    DIORAMA_WIDTH_DEFAULT,
    DIORAMA_WIDTH_MAX,
    DIORAMA_WIDTH_MIN,
    DioramaDirection,
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
    DIORAMA_NOTE_TEXT,
    EDIT_RANGE_TEXT,
    FOLLOW_FRAME_DATA,
    FOLLOW_FRAME_TEXT,
    PANEL_MARGIN,
    PANEL_SPACING,
    SLIDER_MIN_WIDTH,
    TAB_ADJUST_TEXT,
    TAB_CROP_TEXT,
    TAB_DIORAMA_TEXT,
    TAB_OUTPUT_TEXT,
    TRIM_TEXT,
    Adjustment,
    PanelState,
    ResettableSlider,
    Updating,
    adjustment,
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
        # 色の調整・ディテール・角丸のスライダー（ダブルクリックで既定値に戻る）。
        # 設定の項目との対応・値の換算・表示の書式は Adjustment にまとめて持つ
        # 露出は 0.1 EV 刻み。スライダーの値は「EV × 10」で持つ
        exposure, exposure_row = adjustment(
            "exposure",
            round(EXPOSURE_MIN / EXPOSURE_STEP),
            round(EXPOSURE_MAX / EXPOSURE_STEP),
            to_setting=lambda value: value / round(1 / EXPOSURE_STEP),
            to_slider=lambda ev: round(ev / EXPOSURE_STEP),
            text=ev_text,
        )
        brightness, brightness_row = adjustment(
            "brightness", BRIGHTNESS_MIN, BRIGHTNESS_MAX, text=signed_text
        )
        contrast, contrast_row = adjustment(
            "contrast", CONTRAST_MIN, CONTRAST_MAX, text=signed_text
        )
        # 色温度は 100K 刻み。スライダーの値は「ケルビン ÷ 100」で持つ
        temperature, temperature_row = adjustment(
            "temperature",
            TEMPERATURE_MIN // TEMPERATURE_STEP,
            TEMPERATURE_MAX // TEMPERATURE_STEP,
            default=TEMPERATURE_NEUTRAL // TEMPERATURE_STEP,
            to_setting=lambda value: value * TEMPERATURE_STEP,
            to_slider=lambda kelvin: kelvin // TEMPERATURE_STEP,
            text=kelvin_text,
            page_step=5,
        )
        saturation, saturation_row = adjustment(
            "saturation", SATURATION_MIN, SATURATION_MAX, text=signed_text
        )
        vignette, vignette_row = adjustment("vignette", VIGNETTE_MIN, VIGNETTE_MAX)
        aging, aging_row = adjustment("aging", AGING_MIN, AGING_MAX)
        sharpen, sharpen_row = adjustment("sharpen", DETAIL_MIN, DETAIL_MAX)
        blur, blur_row = adjustment("blur", DETAIL_MIN, DETAIL_MAX)
        denoise, denoise_row = adjustment("denoise", DETAIL_MIN, DETAIL_MAX)
        # 角丸の半径（短辺に対する %）。形が角丸のときだけ操作できる
        corner, corner_row = adjustment(
            "corner_radius",
            CORNER_RADIUS_MIN,
            CORNER_RADIUS_MAX,
            default=CORNER_RADIUS_DEFAULT,
            text=percent_text,
            page_step=5,
        )
        # 「加工をリセット」で戻す色・ディテールのスライダー
        self._color_adjustments = (
            exposure,
            brightness,
            contrast,
            temperature,
            saturation,
            vignette,
            aging,
            sharpen,
            blur,
            denoise,
        )
        # ジオラマ（ぼかし 0 = なし）。位置・幅は写真の高さ・幅に対する %
        diorama_blur, diorama_blur_row = adjustment(
            "diorama_blur", DIORAMA_BLUR_MIN, DIORAMA_BLUR_MAX
        )
        diorama_position, diorama_position_row = adjustment(
            "diorama_position",
            DIORAMA_POSITION_MIN,
            DIORAMA_POSITION_MAX,
            default=DIORAMA_POSITION_DEFAULT,
            text=percent_text,
        )
        diorama_width, diorama_width_row = adjustment(
            "diorama_width",
            DIORAMA_WIDTH_MIN,
            DIORAMA_WIDTH_MAX,
            default=DIORAMA_WIDTH_DEFAULT,
            text=percent_text,
        )
        diorama_vivid, diorama_vivid_row = adjustment(
            "diorama_vivid", DIORAMA_VIVID_MIN, DIORAMA_VIVID_MAX, default=DIORAMA_VIVID_DEFAULT
        )
        self._adjustments = (
            *self._color_adjustments,
            corner,
            diorama_blur,
            diorama_position,
            diorama_width,
            diorama_vivid,
        )
        self._adjustment_by_field = {item.field: item for item in self._adjustments}
        self.exposure_slider, self.exposure_value_label = exposure.slider, exposure.label
        self.brightness_slider, self.brightness_value_label = brightness.slider, brightness.label
        self.contrast_slider, self.contrast_value_label = contrast.slider, contrast.label
        self.temperature_slider = temperature.slider
        self.temperature_value_label = temperature.label
        self.saturation_slider, self.saturation_value_label = saturation.slider, saturation.label
        self.vignette_slider, self.vignette_value_label = vignette.slider, vignette.label
        self.aging_slider, self.aging_value_label = aging.slider, aging.label
        self.sharpen_slider, self.sharpen_value_label = sharpen.slider, sharpen.label
        self.blur_slider, self.blur_value_label = blur.slider, blur.label
        self.denoise_slider, self.denoise_value_label = denoise.slider, denoise.label
        self.corner_slider, self.corner_value_label = corner.slider, corner.label
        self.diorama_blur_slider = diorama_blur.slider
        self.diorama_blur_value_label = diorama_blur.label
        self.diorama_position_slider = diorama_position.slider
        self.diorama_position_value_label = diorama_position.label
        self.diorama_width_slider = diorama_width.slider
        self.diorama_width_value_label = diorama_width.label
        self.diorama_vivid_slider = diorama_vivid.slider
        self.diorama_vivid_value_label = diorama_vivid.label
        self.diorama_direction_combo = QComboBox()
        for direction in DioramaDirection:
            self.diorama_direction_combo.addItem(direction.label, direction)

        self.frame_combo = QComboBox()
        for frame_type in FrameType:
            self.frame_combo.addItem(frame_type.label, frame_type)
        self.shape_combo = QComboBox()
        for shape_type in ShapeType:
            self.shape_combo.addItem(shape_type.label, shape_type)
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
        # ジオラマ（ミニチュア風）。開いている間はプレビューにピントの帯のガイドを出す
        diorama_box = QGroupBox("ジオラマ（ミニチュア風）")
        diorama_form = QFormLayout(diorama_box)
        diorama_form.addRow("ぼかし", diorama_blur_row)
        diorama_form.addRow("帯の向き", self.diorama_direction_combo)
        diorama_form.addRow("ピントの位置", diorama_position_row)
        diorama_form.addRow("ピントの幅", diorama_width_row)
        diorama_form.addRow("鮮やかさ", diorama_vivid_row)
        diorama_note = QLabel(DIORAMA_NOTE_TEXT)
        diorama_note.setWordWrap(True)
        diorama_form.addRow(diorama_note)
        self._diorama_page = tab_page(diorama_box)
        self.tabs.addTab(self._diorama_page, TAB_DIORAMA_TEXT)

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
        self.diorama_direction_combo.currentIndexChanged.connect(lambda _: self._emit_changed())
        for name, spin in zip(("x", "y", "width", "height"), self._crop_spins(), strict=True):
            spin.valueChanged.connect(lambda _, name=name: self._on_crop_spin_edited(name))
        self.aspect_combo.currentIndexChanged.connect(lambda _: self._on_aspect_source_changed())
        self.portrait_check.toggled.connect(lambda _: self._on_aspect_source_changed())
        self.clear_crop_button.clicked.connect(self.clear_crop)
        self.trim_button.toggled.connect(self._on_trim_toggled)
        for item in self._adjustments:
            item.slider.valueChanged.connect(lambda _, item=item: self._on_adjustment_changed(item))
        self.reset_adjustments_button.clicked.connect(self.reset_adjustments)
        for button, op in zip(self._orient_buttons(), OrientOp, strict=True):
            button.clicked.connect(lambda _, op=op: self.apply_orientation(op))
        self.tabs.currentChanged.connect(self.tab_changed)
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
            self.diorama_direction_combo.setCurrentIndex(0)
            self._text = TextSettings()
            for item in self._adjustments:
                item.slider.reset()
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
            frame=self.frame(),
            shape=self.shape(),
            text=self._text,
            diorama_direction=self.diorama_direction_combo.currentData(),
            **{item.field: item.value() for item in self._adjustments},
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

    def is_diorama_tab(self) -> bool:
        """「ジオラマ」タブを開いているか（プレビューにピントの帯のガイドを出す）。"""
        return self.tabs.currentWidget() is self._diorama_page

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

    def temperature_kelvin(self) -> int:
        """色温度スライダーの値をケルビンで返す。"""
        return self._adjustment_by_field["temperature"].value()

    def exposure_ev(self) -> float:
        """露出スライダーの値を EV で返す（0.1 刻み）。"""
        return self._adjustment_by_field["exposure"].value()

    def _on_adjustment_changed(self, item: Adjustment) -> None:
        # 値の表示はプログラムから変えたときも合わせ、通知は _emit_changed が止める
        item.update_label()
        self._emit_changed()

    def _on_shape_changed(self) -> None:
        self._update_corner_enabled()
        self._on_aspect_source_changed()

    def _update_corner_enabled(self) -> None:
        """角丸のスライダーは、画像があって形が角丸のときだけ操作できる。"""
        enabled = self._image_size is not None and self.shape() is ShapeType.ROUNDED
        self.corner_slider.setEnabled(enabled)
        self.corner_value_label.setEnabled(enabled)

    def _on_quality_changed(self, value: int) -> None:
        self.quality_value_label.setText(str(value))
        self._on_save_options_changed()

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

    def _adjustment_sliders(self) -> tuple[ResettableSlider, ...]:
        """色・ディテールのスライダー（「加工をリセット」で戻すもの）。"""
        return tuple(item.slider for item in self._color_adjustments)

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
