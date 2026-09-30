import pytest

from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType
from image_editor.core.pipeline import EditSettings
from image_editor.core.shapes import CORNER_RADIUS_DEFAULT, ShapeType
from image_editor.core.transform import AspectRatio, CropRect
from image_editor.ui.settings_panel import SettingsPanel


@pytest.fixture
def panel(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    widget.set_image_size((400, 300))
    return widget


# --- 初期状態 -----------------------------------------------------------------


def test_disabled_without_image(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)

    assert not widget.width_spin.isEnabled()
    assert not widget.save_button.isEnabled()
    assert widget.settings() == EditSettings()


def test_initial_values_are_original_size(panel):
    assert (panel.width_spin.value(), panel.height_spin.value()) == (400, 300)
    assert panel.keep_aspect_check.isChecked()
    assert panel.filter_combo.currentData() is FilterType.NONE
    assert panel.width_spin.isEnabled()
    # 初期値のままならリサイズもトリミングもしない
    assert panel.settings() == EditSettings()


def test_filter_combo_has_labels(panel):
    labels = [panel.filter_combo.itemText(i) for i in range(panel.filter_combo.count())]
    assert labels == [f.label for f in FilterType]
    assert labels[-11:] == [
        "シネマティック",
        "ノワール",
        "ブリーチバイパス",
        "パステル",
        "クロスプロセス",
        "青写真",
        "夏らしい",
        "秋らしい",
        "ソフトフォーカス",
        "HDR 風",
        "赤外線風",
    ]


def test_set_image_size_resets_everything(panel):
    panel.width_spin.setValue(100)
    panel.filter_combo.setCurrentIndex(2)
    panel.set_crop(CropRect(0, 0, 50, 50))

    panel.set_image_size((800, 600))

    assert panel.settings() == EditSettings()
    assert (panel.width_spin.value(), panel.height_spin.value()) == (800, 600)
    assert panel.crop_width_spin.maximum() == 800


# --- 縦横比の連動 -------------------------------------------------------------


def test_keep_aspect_width_updates_height(panel):
    panel.width_spin.setValue(200)

    assert panel.height_spin.value() == 150
    assert panel.settings() == EditSettings(width=200, keep_aspect=True)


def test_keep_aspect_height_updates_width(panel):
    panel.height_spin.setValue(100)

    assert panel.width_spin.value() == 133
    assert panel.settings() == EditSettings(height=100, keep_aspect=True)


def test_without_keep_aspect_sides_are_independent(panel):
    panel.keep_aspect_check.setChecked(False)
    panel.width_spin.setValue(200)
    panel.height_spin.setValue(50)

    assert panel.settings() == EditSettings(width=200, height=50, keep_aspect=False)


def test_turning_keep_aspect_on_resyncs(panel):
    panel.keep_aspect_check.setChecked(False)
    panel.width_spin.setValue(200)
    panel.height_spin.setValue(50)

    panel.keep_aspect_check.setChecked(True)

    # 最後に編集した高さを基準に幅を計算し直す
    assert (panel.width_spin.value(), panel.height_spin.value()) == (67, 50)


def test_linking_emits_once_per_edit(panel, qtbot):
    received: list[EditSettings] = []
    panel.settings_changed.connect(received.append)

    panel.width_spin.setValue(200)

    # 高さの自動更新でシグナルが連鎖しない
    assert received == [EditSettings(width=200)]


def test_size_back_to_base_means_no_resize(panel):
    panel.width_spin.setValue(200)
    panel.width_spin.setValue(400)

    assert panel.settings().width is None
    assert panel.settings().height is None


# --- 加工 ---------------------------------------------------------------------


def test_filter_selection(panel, qtbot):
    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.filter_combo.setCurrentIndex(1)

    assert blocker.args[0].filter is FilterType.SEPIA


# --- トリミング ---------------------------------------------------------------


def test_crop_updates_settings_and_size(panel):
    panel.set_crop(CropRect(10, 20, 200, 100))

    assert panel.settings().crop == CropRect(10, 20, 200, 100)
    # サイズを手で変えていなければ、幅・高さはトリミング後のサイズに追従する
    assert (panel.width_spin.value(), panel.height_spin.value()) == (200, 100)
    assert panel.settings().width is None


def test_crop_spins_emit_settings(panel):
    panel.crop_width_spin.setValue(100)
    panel.crop_height_spin.setValue(50)

    assert panel.settings().crop == CropRect(0, 0, 100, 50)
    assert panel.base_size() == (100, 50)


def test_crop_with_zero_size_is_no_crop(panel):
    panel.crop_width_spin.setValue(100)
    assert panel.settings().crop is None
    assert panel.base_size() == (400, 300)


def test_crop_out_of_image_uses_clamped_base_size(panel):
    panel.set_crop(CropRect(300, 200, 200, 200))
    assert panel.base_size() == (100, 100)


def test_edited_size_is_kept_when_crop_changes(panel):
    panel.width_spin.setValue(100)  # → 100x75

    panel.set_crop(CropRect(0, 0, 200, 50))

    # 手で変えた幅を基準に、新しい縦横比で高さを再計算する
    assert (panel.width_spin.value(), panel.height_spin.value()) == (100, 25)
    assert panel.settings() == EditSettings(crop=CropRect(0, 0, 200, 50), width=100)


def test_clear_crop(panel):
    panel.set_crop(CropRect(10, 10, 100, 100))

    panel.clear_crop_button.click()

    assert panel.settings().crop is None
    assert (panel.width_spin.value(), panel.height_spin.value()) == (400, 300)


# --- ボタン -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("button", "signal"),
    [
        ("save_button", "save_requested"),
        ("reset_button", "reset_requested"),
    ],
)
def test_buttons_emit_signals(panel, qtbot, button, signal):
    with qtbot.waitSignal(getattr(panel, signal)):
        getattr(panel, button).click()


def test_set_busy_disables_buttons(panel):
    panel.set_busy(True)
    assert not panel.save_button.isEnabled()
    assert not panel.reset_button.isEnabled()

    panel.set_busy(False)
    assert panel.save_button.isEnabled()


# --- 未読込時の空欄表示 ---------------------------------------------------------


def all_spins(panel):
    return [
        panel.width_spin,
        panel.height_spin,
        panel.crop_x_spin,
        panel.crop_y_spin,
        panel.crop_width_spin,
        panel.crop_height_spin,
    ]


def test_fields_are_blank_without_image(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)

    assert [spin.text().strip() for spin in all_spins(widget)] == [""] * 6
    assert widget.settings() == EditSettings()


def test_fields_show_values_after_load(panel):
    texts = [spin.text() for spin in all_spins(panel)]
    assert texts == ["400 px", "300 px", "0 px", "0 px", "0 px", "0 px"]


def test_one_px_is_shown_after_load(panel):
    panel.keep_aspect_check.setChecked(False)
    panel.width_spin.setValue(1)

    assert panel.width_spin.text() == "1 px"
    assert panel.width_spin.minimum() == 1
    assert panel.settings().width == 1


def test_fields_are_blank_again_after_reset(panel):
    panel.width_spin.setValue(100)
    panel.set_crop(CropRect(10, 10, 50, 50))

    panel.set_image_size(None)

    assert [spin.text().strip() for spin in all_spins(panel)] == [""] * 6
    assert panel.settings() == EditSettings()


# --- 周辺減光 -----------------------------------------------------------------


def test_vignette_slider(panel, qtbot):
    assert panel.vignette_slider.value() == 0
    assert (panel.vignette_slider.minimum(), panel.vignette_slider.maximum()) == (0, 100)

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.vignette_slider.setValue(40)

    assert blocker.args[0].vignette == 40
    assert panel.vignette_value_label.text() == "40"
    assert panel.settings() == EditSettings(vignette=40)


def test_vignette_is_reset_on_new_image(panel):
    panel.vignette_slider.setValue(70)

    panel.set_image_size((100, 100))

    assert panel.vignette_slider.value() == 0
    assert panel.vignette_value_label.text() == "0"


# --- トリミング実行 -------------------------------------------------------------


def test_trim_button_needs_crop(panel):
    assert not panel.trim_button.isEnabled()

    panel.set_crop(CropRect(10, 10, 100, 100))

    assert panel.trim_button.isEnabled()
    assert panel.trim_button.text() == "トリミング実行"


def test_trim_button_toggles_view(panel, qtbot):
    panel.set_crop(CropRect(10, 10, 100, 100))

    with qtbot.waitSignal(panel.trim_view_toggled) as blocker:
        panel.trim_button.click()

    assert blocker.args == [True]
    assert panel.is_trim_view()
    assert panel.trim_button.text() == "範囲を編集"

    with qtbot.waitSignal(panel.trim_view_toggled) as blocker:
        panel.trim_button.click()

    assert blocker.args == [False]
    assert panel.trim_button.text() == "トリミング実行"


def test_clearing_crop_leaves_trim_view(panel, qtbot):
    panel.set_crop(CropRect(10, 10, 100, 100))
    panel.set_trim_view(True)

    with qtbot.waitSignal(panel.trim_view_toggled) as blocker:
        panel.clear_crop_button.click()

    assert blocker.args == [False]
    assert not panel.is_trim_view()
    assert not panel.trim_button.isEnabled()


def test_new_image_leaves_trim_view_without_signal(panel, qtbot):
    panel.set_crop(CropRect(10, 10, 100, 100))
    panel.set_trim_view(True)

    with qtbot.assertNotEmitted(panel.trim_view_toggled):
        panel.set_image_size((200, 200))

    assert not panel.is_trim_view()
    assert panel.trim_button.text() == "トリミング実行"


def test_trim_view_does_not_change_settings(panel):
    panel.set_crop(CropRect(10, 10, 100, 100))
    before = panel.settings()

    panel.set_trim_view(True)

    assert panel.settings() == before


def test_set_trim_view_ignored_without_crop(panel):
    panel.set_trim_view(True)
    assert not panel.is_trim_view()


# --- フレーム -----------------------------------------------------------------


def select_frame(panel: SettingsPanel, frame: FrameType) -> None:
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(frame))


def test_frame_combo_has_labels(panel):
    labels = [panel.frame_combo.itemText(i) for i in range(panel.frame_combo.count())]
    assert labels == ["なし", "ポラロイド", "チェキ"]
    assert panel.settings().frame is FrameType.NONE


def test_frame_selection_emits_settings(panel, qtbot):
    with qtbot.waitSignal(panel.settings_changed) as blocker:
        select_frame(panel, FrameType.INSTAX_MINI)

    assert blocker.args[0].frame is FrameType.INSTAX_MINI
    assert panel.settings().filter is FilterType.NONE  # テイストとは別の設定


def test_frame_updates_base_size(panel):
    # 400x300 はポラロイドの写真部分（正方形）に合わせて 300x300 に切り抜く
    select_frame(panel, FrameType.POLAROID)

    assert panel.base_size() == (300, 300)
    assert (panel.width_spin.value(), panel.height_spin.value()) == (300, 300)
    assert panel.settings().width is None  # 初期値のままならリサイズしない

    select_frame(panel, FrameType.INSTAX_MINI)
    assert panel.base_size() == (400, 297)  # 横向きのチェキ 62:46（上下を削る）

    select_frame(panel, FrameType.NONE)
    assert panel.base_size() == (400, 300)


def test_frame_uses_crop_range(panel):
    panel.set_crop(CropRect(0, 0, 200, 100))
    select_frame(panel, FrameType.POLAROID)
    assert panel.base_size() == (100, 100)


def test_frame_keeps_aspect_of_edited_size(panel):
    panel.width_spin.setValue(200)
    select_frame(panel, FrameType.POLAROID)
    assert (panel.width_spin.value(), panel.height_spin.value()) == (200, 200)


def test_trim_button_is_enabled_by_frame(panel):
    select_frame(panel, FrameType.POLAROID)
    assert panel.trim_button.isEnabled()

    panel.set_trim_view(True)
    select_frame(panel, FrameType.NONE)

    assert not panel.trim_button.isEnabled()
    assert not panel.is_trim_view()


def test_frame_is_reset_on_new_image(panel):
    select_frame(panel, FrameType.POLAROID)
    panel.set_image_size((200, 200))
    assert panel.frame_combo.currentIndex() == 0
    assert panel.settings().frame is FrameType.NONE


# --- 経年劣化 -----------------------------------------------------------------


def test_aging_slider(panel, qtbot):
    assert panel.aging_slider.value() == 0
    assert (panel.aging_slider.minimum(), panel.aging_slider.maximum()) == (0, 100)

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.aging_slider.setValue(65)

    assert blocker.args[0].aging == 65
    assert panel.aging_value_label.text() == "65"
    assert panel.settings() == EditSettings(aging=65)


def test_aging_is_reset_on_new_image(panel):
    panel.aging_slider.setValue(80)

    panel.set_image_size((100, 100))

    assert panel.aging_slider.value() == 0
    assert panel.aging_value_label.text() == "0"


# --- 色温度 -------------------------------------------------------------------


def test_temperature_slider(panel, qtbot):
    assert panel.temperature_kelvin() == 6500
    assert panel.temperature_value_label.text() == "6500 K"
    assert panel.settings() == EditSettings()

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.temperature_slider.setValue(32)

    assert blocker.args[0].temperature == 3200
    assert panel.temperature_value_label.text() == "3200 K"


def test_temperature_slider_range(panel):
    panel.temperature_slider.setValue(0)
    assert panel.temperature_kelvin() == 2000
    panel.temperature_slider.setValue(1000)
    assert panel.temperature_kelvin() == 10000


def test_temperature_is_reset_on_new_image(panel):
    panel.temperature_slider.setValue(40)

    panel.set_image_size((100, 100))

    assert panel.temperature_kelvin() == 6500
    assert panel.temperature_value_label.text() == "6500 K"


# --- 彩度 ---------------------------------------------------------------------


def test_saturation_slider(panel, qtbot):
    assert panel.saturation_slider.value() == 0
    assert panel.saturation_value_label.text() == "0"
    assert (panel.saturation_slider.minimum(), panel.saturation_slider.maximum()) == (-100, 100)

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.saturation_slider.setValue(30)

    assert blocker.args[0].saturation == 30
    assert panel.saturation_value_label.text() == "+30"

    panel.saturation_slider.setValue(-50)
    assert panel.saturation_value_label.text() == "-50"
    assert panel.settings() == EditSettings(saturation=-50)


def test_saturation_is_reset_on_new_image(panel):
    panel.saturation_slider.setValue(-80)

    panel.set_image_size((100, 100))

    assert panel.saturation_slider.value() == 0
    assert panel.saturation_value_label.text() == "0"


# --- 明るさ -------------------------------------------------------------------


def test_brightness_slider(panel, qtbot):
    assert panel.brightness_slider.value() == 0
    assert panel.brightness_value_label.text() == "0"

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.brightness_slider.setValue(25)

    assert blocker.args[0].brightness == 25
    assert panel.brightness_value_label.text() == "+25"
    assert panel.settings() == EditSettings(brightness=25)


def test_brightness_is_reset_on_new_image(panel):
    panel.brightness_slider.setValue(-30)

    panel.set_image_size((100, 100))

    assert panel.brightness_slider.value() == 0
    assert panel.brightness_value_label.text() == "0"


# --- スライダーの長さ ---------------------------------------------------------


def test_sliders_are_long_enough_and_aligned(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    widget.set_image_size((100, 100))
    widget.show()
    qtbot.waitExposed(widget)

    sliders = [
        widget.brightness_slider,
        widget.temperature_slider,
        widget.saturation_slider,
        widget.vignette_slider,
        widget.aging_slider,
    ]
    widths = {slider.width() for slider in sliders}
    assert len(widths) == 1  # 長さがそろっている
    assert widths.pop() >= 225  # 以前 (150px) の 1.5 倍以上


# --- コントラスト -------------------------------------------------------------


def test_contrast_slider(panel, qtbot):
    assert panel.contrast_slider.value() == 0
    assert panel.contrast_value_label.text() == "0"

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.contrast_slider.setValue(-35)

    assert blocker.args[0].contrast == -35
    assert panel.contrast_value_label.text() == "-35"
    assert panel.settings() == EditSettings(contrast=-35)


def test_contrast_is_reset_on_new_image(panel):
    panel.contrast_slider.setValue(60)

    panel.set_image_size((100, 100))

    assert panel.contrast_slider.value() == 0
    assert panel.contrast_value_label.text() == "0"


def test_contrast_slider_is_as_long_as_others(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    assert widget.contrast_slider.width() == widget.brightness_slider.width() >= 225


# --- 露出 ---------------------------------------------------------------------


def test_exposure_slider(panel, qtbot):
    assert panel.exposure_ev() == 0.0
    assert panel.exposure_value_label.text() == "0.0 EV"
    assert (panel.exposure_slider.minimum(), panel.exposure_slider.maximum()) == (-50, 50)

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.exposure_slider.setValue(13)

    assert blocker.args[0].exposure == pytest.approx(1.3)
    assert panel.exposure_value_label.text() == "+1.3 EV"

    panel.exposure_slider.setValue(-50)
    assert panel.exposure_value_label.text() == "-5.0 EV"
    assert panel.settings().exposure == pytest.approx(-5.0)


def test_exposure_is_reset_on_new_image(panel):
    panel.exposure_slider.setValue(20)

    panel.set_image_size((100, 100))

    assert panel.exposure_ev() == 0.0
    assert panel.exposure_value_label.text() == "0.0 EV"


# --- 形 -----------------------------------------------------------------------


def select_shape(panel: SettingsPanel, shape: ShapeType) -> None:
    panel.shape_combo.setCurrentIndex(panel.shape_combo.findData(shape))


def test_shape_combo_has_labels(panel):
    labels = [panel.shape_combo.itemText(i) for i in range(panel.shape_combo.count())]
    assert labels == ["矩形", "角丸", "円"]
    settings = panel.settings()
    assert settings.shape is ShapeType.RECTANGLE
    assert settings.corner_radius == CORNER_RADIUS_DEFAULT
    assert settings == EditSettings(width=None, height=None)  # 既定値は変更なし扱い


def test_corner_slider_only_for_rounded(panel):
    assert not panel.corner_slider.isEnabled()

    select_shape(panel, ShapeType.ROUNDED)
    assert panel.corner_slider.isEnabled()

    select_shape(panel, ShapeType.CIRCLE)
    assert not panel.corner_slider.isEnabled()


def test_corner_slider(panel, qtbot):
    select_shape(panel, ShapeType.ROUNDED)
    assert panel.corner_value_label.text() == f"{CORNER_RADIUS_DEFAULT}%"
    assert (panel.corner_slider.minimum(), panel.corner_slider.maximum()) == (0, 50)

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        panel.corner_slider.setValue(35)

    assert blocker.args[0].shape is ShapeType.ROUNDED
    assert blocker.args[0].corner_radius == 35
    assert panel.corner_value_label.text() == "35%"


def test_circle_updates_base_size(panel):
    select_shape(panel, ShapeType.CIRCLE)
    assert panel.base_size() == (300, 300)
    assert (panel.width_spin.value(), panel.height_spin.value()) == (300, 300)

    select_shape(panel, ShapeType.ROUNDED)
    assert panel.base_size() == (400, 300)


def test_circle_with_frame_uses_frame_window(panel):
    select_frame(panel, FrameType.INSTAX_MINI)
    select_shape(panel, ShapeType.CIRCLE)
    assert panel.base_size() == (400, 297)


def test_trim_button_is_enabled_by_shape(panel):
    select_shape(panel, ShapeType.ROUNDED)
    assert panel.trim_button.isEnabled()

    panel.set_trim_view(True)
    select_shape(panel, ShapeType.RECTANGLE)

    assert not panel.trim_button.isEnabled()
    assert not panel.is_trim_view()


def test_shape_is_reset_on_new_image(panel):
    select_shape(panel, ShapeType.ROUNDED)
    panel.corner_slider.setValue(40)

    panel.set_image_size((200, 200))

    assert panel.settings().shape is ShapeType.RECTANGLE
    assert panel.corner_slider.value() == CORNER_RADIUS_DEFAULT
    assert panel.corner_value_label.text() == f"{CORNER_RADIUS_DEFAULT}%"
    assert not panel.corner_slider.isEnabled()


def test_corner_slider_disabled_without_image(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    select_shape(widget, ShapeType.ROUNDED)
    assert not widget.corner_slider.isEnabled()


# --- トリミングの縦横比 ---------------------------------------------------------


def select_aspect(panel: SettingsPanel, aspect: AspectRatio) -> None:
    panel.aspect_combo.setCurrentIndex(panel.aspect_combo.findData(aspect))


def crop_values(panel: SettingsPanel) -> tuple[int, int, int, int]:
    return (
        panel.crop_x_spin.value(),
        panel.crop_y_spin.value(),
        panel.crop_width_spin.value(),
        panel.crop_height_spin.value(),
    )


def test_aspect_combo_items(panel):
    labels = [panel.aspect_combo.itemText(i) for i in range(panel.aspect_combo.count())]
    assert labels == ["自由", "1:1", "4:3", "3:2", "16:9", "フレーム・円に合わせる"]
    assert panel.aspect_combo.currentText() == "自由"
    assert panel.crop_aspect() == (None, False)
    # 「フレーム・円に合わせる」はユーザーが選べない
    follow = panel.aspect_combo.model().item(panel.aspect_combo.count() - 1)
    assert not follow.isEnabled()


def test_portrait_check_only_for_oriented_ratio(panel):
    assert not panel.portrait_check.isEnabled()  # 自由
    select_aspect(panel, AspectRatio.SQUARE)
    assert not panel.portrait_check.isEnabled()
    select_aspect(panel, AspectRatio.RATIO_4_3)
    assert panel.portrait_check.isEnabled()


def test_crop_aspect_follows_selection(panel):
    select_aspect(panel, AspectRatio.RATIO_16_9)
    assert panel.crop_aspect() == ((16, 9), False)

    panel.portrait_check.setChecked(True)
    assert panel.crop_aspect() == ((9, 16), False)


def test_selecting_aspect_fits_existing_range(panel, qtbot):
    panel.set_crop(CropRect(0, 0, 400, 200))

    with qtbot.waitSignal(panel.settings_changed) as blocker:
        select_aspect(panel, AspectRatio.SQUARE)

    # 範囲の中央を 1:1 に直す
    assert blocker.args[0].crop == CropRect(100, 0, 200, 200)
    assert crop_values(panel) == (100, 0, 200, 200)


def test_portrait_toggle_fits_range(panel):
    panel.set_crop(CropRect(0, 0, 400, 300))
    select_aspect(panel, AspectRatio.RATIO_4_3)
    assert crop_values(panel) == (0, 0, 400, 300)

    panel.portrait_check.setChecked(True)

    assert crop_values(panel) == (87, 0, 225, 300)  # 中央 ((400 - 225) // 2)


def test_selecting_aspect_without_range_does_nothing(panel):
    select_aspect(panel, AspectRatio.SQUARE)
    assert panel.settings().crop is None


def test_width_input_keeps_aspect(panel):
    select_aspect(panel, AspectRatio.RATIO_4_3)
    panel.set_crop(CropRect(0, 0, 200, 150))

    panel.crop_width_spin.setValue(100)

    assert crop_values(panel) == (0, 0, 100, 75)


def test_height_input_keeps_aspect(panel):
    select_aspect(panel, AspectRatio.RATIO_16_9)
    panel.set_crop(CropRect(0, 0, 160, 90))

    panel.crop_height_spin.setValue(180)

    assert crop_values(panel) == (0, 0, 320, 180)


def test_size_input_at_image_edge_keeps_aspect(panel):
    # 400x300 の画像で (200, 0) から幅 400 → 右端で収まるよう縮める
    select_aspect(panel, AspectRatio.SQUARE)
    panel.set_crop(CropRect(200, 0, 100, 100))

    panel.crop_width_spin.setValue(400)

    assert crop_values(panel) == (200, 0, 200, 200)


def test_position_input_keeps_size(panel):
    select_aspect(panel, AspectRatio.SQUARE)
    panel.set_crop(CropRect(0, 0, 200, 200))

    panel.crop_x_spin.setValue(350)  # はみ出す分だけ戻す

    assert crop_values(panel) == (200, 0, 200, 200)


def test_set_crop_is_fitted_to_aspect(panel):
    select_aspect(panel, AspectRatio.SQUARE)
    panel.set_crop(CropRect(10, 10, 300, 100))
    assert crop_values(panel) == (10, 10, 100, 100)


def test_free_aspect_keeps_input(panel):
    panel.set_crop(CropRect(10, 10, 300, 100))
    panel.crop_width_spin.setValue(50)
    assert crop_values(panel) == (10, 10, 50, 100)


def test_frame_locks_aspect(panel):
    select_aspect(panel, AspectRatio.RATIO_16_9)
    panel.set_crop(CropRect(0, 0, 400, 300))

    select_frame(panel, FrameType.POLAROID)

    assert panel.aspect_combo.currentText() == "フレーム・円に合わせる"
    assert not panel.aspect_combo.isEnabled()
    assert not panel.portrait_check.isEnabled()
    assert panel.crop_aspect() == ((79, 79), False)
    # 16:9 に直った範囲 (0, 0, 400, 225) の中央を、写真部分の比 (正方形) に直す
    assert crop_values(panel) == (87, 0, 225, 225)

    select_frame(panel, FrameType.NONE)

    # 固定を解くと元の選択に戻る
    assert panel.aspect_combo.currentText() == "16:9"
    assert panel.aspect_combo.isEnabled()


def test_instax_aspect_follows_range_orientation(panel):
    select_frame(panel, FrameType.INSTAX_MINI)
    # 範囲がなければ画像（横長）に合わせる。向きはドラッグで自由に選べる
    assert panel.crop_aspect() == ((62, 46), True)

    panel.set_crop(CropRect(0, 0, 100, 250))

    aspect, free = panel.crop_aspect()
    assert aspect == (46, 62)
    assert free
    width, height = crop_values(panel)[2:]
    assert abs(height - width * 62 / 46) <= 1


def test_circle_locks_aspect(panel):
    select_shape(panel, ShapeType.CIRCLE)
    assert panel.crop_aspect() == ((1, 1), False)
    assert not panel.aspect_combo.isEnabled()

    select_shape(panel, ShapeType.ROUNDED)
    assert panel.crop_aspect() == (None, False)
    assert panel.aspect_combo.isEnabled()


def test_aspect_is_reset_on_new_image(panel):
    select_aspect(panel, AspectRatio.RATIO_4_3)
    panel.portrait_check.setChecked(True)

    panel.set_image_size((200, 200))

    assert panel.aspect_combo.currentText() == "自由"
    assert not panel.portrait_check.isChecked()
    assert panel.aspect_combo.isEnabled()


def test_aspect_controls_disabled_without_image(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    assert not widget.aspect_combo.isEnabled()
    assert not widget.portrait_check.isEnabled()


def test_aspect_does_not_count_as_change(panel):
    select_aspect(panel, AspectRatio.RATIO_4_3)
    assert panel.settings() == EditSettings()
