import json
import subprocess
import sys

import pytest

from image_editor.core.diorama import DioramaDirection
from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType
from image_editor.core.pipeline import EditSettings
from image_editor.core.presets import (
    PRESET_FIELDS,
    Preset,
    PresetError,
    apply_preset,
    load_presets,
    normalize_name,
    preset_from_settings,
    remove_preset,
    save_presets,
    upsert_preset,
)
from image_editor.core.shapes import ShapeType
from image_editor.core.transform import CropRect, Orientation

LOOK = EditSettings(
    filter=FilterType.CINEMATIC,
    exposure=0.7,
    brightness=12,
    contrast=-20,
    temperature=5200,
    saturation=30,
    vignette=40,
    aging=15,
    frame=FrameType.INSTAX_MINI,
    shape=ShapeType.ROUNDED,
    corner_radius=25,
    diorama_blur=60,
    diorama_direction=DioramaDirection.VERTICAL,
    diorama_position=35,
    diorama_width=15,
    diorama_vivid=70,
)


def test_preset_fields_match_edit_settings():
    # プリセットの項目はすべて EditSettings にある（名前がずれていない）
    settings_fields = set(EditSettings.__dataclass_fields__)
    assert set(PRESET_FIELDS) <= settings_fields
    # 画像ごとの設定は含めない
    for key in ("crop", "width", "height", "keep_aspect", "orientation"):
        assert key not in PRESET_FIELDS


def test_preset_from_settings_and_apply():
    preset = preset_from_settings("映画風", LOOK)
    target = EditSettings(
        orientation=Orientation(90, True),
        crop=CropRect(1, 2, 30, 40),
        width=100,
        keep_aspect=False,
    )

    applied = apply_preset(target, preset)

    for key in PRESET_FIELDS:
        assert getattr(applied, key) == getattr(LOOK, key)
    # サイズ・範囲・向きはそのまま
    assert applied.orientation == Orientation(90, True)
    assert applied.crop == CropRect(1, 2, 30, 40)
    assert (applied.width, applied.keep_aspect) == (100, False)


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "nested" / "presets.json"  # フォルダがなければ作る
    presets = [preset_from_settings("映画風", LOOK), Preset(name="何もしない")]

    save_presets(path, presets)

    assert load_presets(path) == presets
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["presets"][0]["name"] == "映画風"  # 日本語のまま書く
    assert data["presets"][0]["filter"] == "cinematic"
    assert not (tmp_path / "nested" / "presets.json.tmp").exists()


def test_load_missing_file_is_empty(tmp_path):
    assert load_presets(tmp_path / "none.json") == []


@pytest.mark.parametrize("text", ["{", "[]", '{"presets": 3}', '{"version": 1}'])
def test_load_broken_file(tmp_path, text):
    path = tmp_path / "presets.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(PresetError):
        load_presets(path)


def test_load_skips_broken_items(tmp_path):
    path = tmp_path / "presets.json"
    items = [
        {"name": "ok", "filter": "sepia", "brightness": 10},
        {"name": "知らないテイスト", "filter": "unknown"},
        {"name": "文字の値", "brightness": "abc"},
        {"name": "真偽値", "contrast": True},
        {"name": "   "},
        {"filter": "sepia"},
        "文字列",
        {"name": "ok", "filter": "noir"},  # 同じ名前は先のものを残す
        {"name": "  前後に空白  "},
    ]
    path.write_text(json.dumps({"version": 1, "presets": items}), encoding="utf-8")

    presets = load_presets(path)

    assert [p.name for p in presets] == ["ok", "前後に空白"]
    assert presets[0] == Preset(name="ok", filter=FilterType.SEPIA, brightness=10)


def test_load_uses_defaults_for_missing_fields(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text('{"presets": [{"name": "少しだけ", "exposure": 1}]}', encoding="utf-8")

    (preset,) = load_presets(path)

    assert preset.exposure == 1.0
    assert preset.temperature == 6500
    assert preset.corner_radius == 10
    assert preset.diorama_blur == 0
    assert preset.diorama_direction is DioramaDirection.HORIZONTAL


def test_diorama_round_trip_and_broken_direction(tmp_path):
    path = tmp_path / "presets.json"
    save_presets(path, [preset_from_settings("ミニチュア", LOOK)])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["presets"][0]["diorama_direction"] == "vertical"
    assert data["presets"][0]["diorama_blur"] == 60

    data["presets"].append({"name": "壊れた向き", "diorama_direction": "diagonal"})
    path.write_text(json.dumps(data), encoding="utf-8")

    assert [p.name for p in load_presets(path)] == ["ミニチュア"]


def test_save_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(PresetError):
        save_presets(blocker / "presets.json", [Preset(name="a")])


def test_upsert_and_remove():
    a, b = Preset(name="a"), Preset(name="b", brightness=5)
    presets = upsert_preset([a], b)
    assert presets == [a, b]

    replaced = upsert_preset(presets, Preset(name="a", contrast=9))
    assert [p.name for p in replaced] == ["a", "b"]  # 順番は変えない
    assert replaced[0].contrast == 9

    assert remove_preset(replaced, "a") == [b]
    assert remove_preset(replaced, "none") == replaced


def test_normalize_name():
    assert normalize_name("  夏らしい  ") == "夏らしい"
    assert len(normalize_name("あ" * 80)) == 50


def test_core_presets_does_not_import_qt():
    code = (
        "import sys, image_editor.core.presets; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
