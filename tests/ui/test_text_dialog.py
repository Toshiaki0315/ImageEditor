from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog

from image_editor.core.text import TextFont, TextPosition, TextSettings
from image_editor.ui.text_dialog import TextDialog


def test_defaults(qtbot):
    dialog = TextDialog()
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "文字・透かし"
    assert dialog.settings() == TextSettings()
    assert dialog.opacity_label.text() == "80%"
    fonts = [dialog.font_combo.itemText(i) for i in range(dialog.font_combo.count())]
    assert fonts[0] == "ヒラギノ角ゴシック" and len(fonts) == len(TextFont)
    positions = [dialog.position_combo.itemText(i) for i in range(dialog.position_combo.count())]
    assert positions[-1] == "フレームの余白" and len(positions) == 10


def test_changes_emit_settings(qtbot):
    dialog = TextDialog()
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog.settings_changed) as blocker:
        dialog.text_edit.setPlainText("© 2026")
    assert blocker.args[0].text == "© 2026"

    dialog.font_combo.setCurrentIndex(dialog.font_combo.findData(TextFont.MINCHO))
    dialog.size_spin.setValue(8.5)
    dialog.opacity_slider.setValue(40)
    dialog.position_combo.setCurrentIndex(dialog.position_combo.findData(TextPosition.TOP_LEFT))
    dialog.set_color((1, 2, 3))

    assert dialog.settings() == TextSettings(
        text="© 2026",
        font=TextFont.MINCHO,
        size=8.5,
        color=(1, 2, 3),
        opacity=40,
        position=TextPosition.TOP_LEFT,
    )
    assert dialog.opacity_label.text() == "40%"


def test_set_settings_does_not_emit(qtbot):
    dialog = TextDialog()
    qtbot.addWidget(dialog)
    settings = TextSettings(text="a\\nb", size=12, opacity=10, position=TextPosition.CENTER)

    with qtbot.assertNotEmitted(dialog.settings_changed):
        dialog.set_settings(settings)

    assert dialog.settings() == settings


def test_color_button_uses_color_dialog(qtbot, monkeypatch):
    dialog = TextDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor(10, 20, 30))

    with qtbot.waitSignal(dialog.settings_changed) as blocker:
        dialog.color_button.click()

    assert blocker.args[0].color == (10, 20, 30)
    assert dialog.color_button.toolTip() == "#0A141E"


def test_clear_button(qtbot):
    dialog = TextDialog()
    qtbot.addWidget(dialog)
    dialog.set_settings(TextSettings(text="消す"))

    with qtbot.waitSignal(dialog.settings_changed) as blocker:
        dialog.clear_button.click()

    assert blocker.args[0].text == ""
