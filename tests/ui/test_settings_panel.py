import pytest

from image_editor.core.filters import FilterType
from image_editor.core.pipeline import EditSettings
from image_editor.core.transform import CropRect
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
