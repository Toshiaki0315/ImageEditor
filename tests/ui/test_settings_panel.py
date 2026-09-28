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
    assert labels == ["なし", "セピア", "モノトーン", "ハイトーン", "ポラロイド風"]


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
        ("preview_button", "preview_requested"),
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
    assert not panel.preview_button.isEnabled()

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
