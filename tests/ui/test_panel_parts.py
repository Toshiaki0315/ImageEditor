from dataclasses import fields

import pytest

from image_editor.core.pipeline import EditSettings
from image_editor.ui.panel_parts import adjustment, signed_text
from image_editor.ui.settings_panel import SettingsPanel


def test_adjustment_converts_and_formats(qtbot):
    item, _row = adjustment(
        "exposure",
        -50,
        50,
        to_setting=lambda value: value / 10,
        to_slider=lambda ev: round(ev * 10),
        text=lambda ev: f"{ev:+.1f}",
    )
    qtbot.addWidget(item.slider)
    assert item.label.text() == "+0.0"

    item.set_value(1.3)
    assert item.slider.value() == 13
    assert item.value() == 1.3
    item.update_label()
    assert item.label.text() == "+1.3"


def test_adjustment_default_and_page_step(qtbot):
    item, _row = adjustment("contrast", -100, 100, default=20, text=signed_text, page_step=5)
    qtbot.addWidget(item.slider)
    assert item.value() == 20
    assert item.label.text() == "+20"
    assert item.slider.pageStep() == 5
    item.slider.setValue(-30)
    item.slider.reset()
    assert item.value() == 20


def test_panel_adjustments_are_edit_settings_fields(qtbot):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    names = {f.name for f in fields(EditSettings)}
    assert {item.field for item in panel._adjustments} <= names


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exposure", -2.3),
        ("brightness", 40),
        ("contrast", -15),
        ("temperature", 3400),
        ("saturation", 70),
        ("vignette", 55),
        ("aging", 12),
        ("sharpen", 80),
        ("blur", 9),
        ("denoise", 33),
        ("corner_radius", 42),
    ],
)
def test_panel_adjustment_round_trip(qtbot, field, value):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_image_size((400, 300))

    item = panel._adjustment_by_field[field]
    item.set_value(value)

    assert getattr(panel.settings(), field) == value
    assert item.label.text() == item.text(value)
