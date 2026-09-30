import subprocess
import sys

import pytest
from PIL import Image, ImageChops

from image_editor.core.frames import FrameType, frame_margins, margin_box
from image_editor.core.pipeline import EditSettings, apply_edits, make_preview, render_preview
from image_editor.core.presets import Preset, load_presets, save_presets
from image_editor.core.text import (
    TextFont,
    TextPosition,
    TextSettings,
    draw_text,
    load_font,
    text_size_px,
)
from image_editor.core.transform import CropRect

BLACK = (0, 0, 0)
RED = (255, 0, 0)


def text_bounds(before: Image.Image, after: Image.Image) -> tuple[int, int, int, int] | None:
    """描いた文字の範囲（変わった画素の範囲）。"""
    return ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox()


def test_empty_text_draws_nothing():
    image = Image.new("RGB", (200, 100), BLACK)
    for text in ("", "   \n "):
        result = draw_text(image, TextSettings(text=text))
        assert result is not image
        assert result.tobytes() == image.tobytes()


def test_all_fonts_can_be_loaded():
    for font in TextFont:
        assert font.path.exists()
        assert load_font(font, 20) is not None


def test_missing_font_falls_back(monkeypatch):
    monkeypatch.setattr("image_editor.core.text.FONT_DIR", __import__("pathlib").Path("/none"))
    from image_editor.core import text as module

    module._load_font.cache_clear()
    try:
        image = Image.new("RGB", (200, 100), BLACK)
        result = draw_text(image, TextSettings(text="abc", opacity=100))
        assert text_bounds(image, result) is not None
    finally:
        module._load_font.cache_clear()


def test_text_size_is_percent_of_reference():
    assert text_size_px(TextSettings(size=5), 1000) == 50
    assert text_size_px(TextSettings(size=100), 1000) == 300  # 上限 30%
    assert text_size_px(TextSettings(size=0.1), 1000) == 10  # 下限 1%


@pytest.mark.parametrize(
    ("position", "check"),
    [
        (TextPosition.TOP_LEFT, lambda b: b[0] < 40 and b[1] < 40),
        (TextPosition.TOP_RIGHT, lambda b: b[2] > 360 and b[1] < 40),
        (TextPosition.BOTTOM_LEFT, lambda b: b[0] < 40 and b[3] > 260),
        (TextPosition.BOTTOM_RIGHT, lambda b: b[2] > 360 and b[3] > 260),
        (TextPosition.CENTER, lambda b: abs((b[0] + b[2]) / 2 - 200) < 10),
    ],
)
def test_positions(position, check):
    image = Image.new("RGB", (400, 300), BLACK)
    result = draw_text(image, TextSettings(text="Sample", position=position, opacity=100))
    bounds = text_bounds(image, result)
    assert bounds is not None and check(bounds)
    # 端から短辺の 3% (9px) 以上内側
    assert bounds[0] >= 8 and bounds[1] >= 8 and bounds[2] <= 392 and bounds[3] <= 292


def test_color_and_opacity():
    image = Image.new("RGB", (400, 300), BLACK)
    solid = draw_text(image, TextSettings(text="■", color=RED, opacity=100, size=20))
    half = draw_text(image, TextSettings(text="■", color=RED, opacity=50, size=20))
    assert solid.getchannel("R").getextrema()[1] == 255
    assert 120 <= half.getchannel("R").getextrema()[1] <= 135
    assert solid.getchannel("G").getextrema()[1] == 0


def test_text_is_shrunk_to_fit():
    image = Image.new("RGB", (100, 60), BLACK)
    result = draw_text(image, TextSettings(text="とても長い文字列です" * 3, size=30, opacity=100))
    bounds = text_bounds(image, result)
    assert bounds is not None
    assert bounds[0] >= 0 and bounds[2] <= 100


def test_box_limits_text():
    image = Image.new("RGB", (400, 300), BLACK)
    result = draw_text(image, TextSettings(text="X", opacity=100), box=(200, 100, 300, 200))
    bounds = text_bounds(image, result)
    assert bounds is not None
    assert bounds[0] >= 200 and bounds[2] <= 300 and bounds[1] >= 100 and bounds[3] <= 200


def test_keeps_alpha_and_input():
    image = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    before = image.tobytes()
    settings = TextSettings(text="A", opacity=100, size=30, position=TextPosition.CENTER)
    result = draw_text(image, settings)
    assert image.tobytes() == before
    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema() == (0, 255)  # 文字は透明な上にも見える


def test_multiline():
    image = Image.new("RGB", (400, 300), BLACK)
    one = text_bounds(image, draw_text(image, TextSettings(text="abc", opacity=100)))
    two = text_bounds(image, draw_text(image, TextSettings(text="abc\ndef", opacity=100)))
    assert one is not None and two is not None
    assert (two[3] - two[1]) > (one[3] - one[1]) * 1.5


# --- パイプライン ---------------------------------------------------------------


def test_apply_edits_draws_text_on_resized_photo():
    image = Image.new("RGB", (800, 600), BLACK)
    settings = EditSettings(width=400, text=TextSettings(text="Hi", opacity=100, size=10))
    result = apply_edits(image, settings)
    bounds = text_bounds(Image.new("RGB", result.size, BLACK), result)
    assert result.size == (400, 300)
    assert bounds is not None
    # 大きさは写真（リサイズ後）の短辺 300 の 10% = 30px 前後
    assert 15 <= bounds[3] - bounds[1] <= 36


def test_text_on_frame_margin():
    image = Image.new("RGB", (400, 400), BLACK)
    text = TextSettings(text="memo", color=RED, opacity=100, position=TextPosition.FRAME_MARGIN)
    settings = EditSettings(frame=FrameType.POLAROID, text=text)

    result = apply_edits(image, settings)

    box = margin_box((400, 400), FrameType.POLAROID)
    reds = Image.new("RGB", result.size, (255, 255, 255))
    reds.paste(result.crop(box), box[:2])
    bounds = text_bounds(Image.new("RGB", result.size, (255, 255, 255)), reds)
    assert bounds is not None
    left, top, _, _ = frame_margins(FrameType.POLAROID, (400, 400))
    assert bounds[1] >= top + 400  # 写真の下の余白
    # 写真の上には描かない
    assert result.crop((left, top, left + 400, top + 400)).getcolors() == [(400 * 400, BLACK)]


def test_frame_margin_without_frame_goes_bottom():
    image = Image.new("RGB", (400, 300), BLACK)
    text = TextSettings(text="memo", opacity=100, position=TextPosition.FRAME_MARGIN)
    result = apply_edits(image, EditSettings(text=text))
    bounds = text_bounds(image, result)
    assert bounds is not None
    assert bounds[3] > 250 and abs((bounds[0] + bounds[2]) / 2 - 200) < 10


def test_margin_box_landscape_instax_is_right():
    box = margin_box((620, 460), FrameType.INSTAX_MINI)
    left, top, right, _ = frame_margins(FrameType.INSTAX_MINI, (620, 460))
    assert box == (left + 620, top, left + 620 + right, top + 460)
    assert margin_box((10, 10), FrameType.NONE) is None


@pytest.mark.parametrize(
    "position", [TextPosition.BOTTOM_RIGHT, TextPosition.CENTER, TextPosition.FRAME_MARGIN]
)
@pytest.mark.parametrize("crop", [None, CropRect(400, 300, 2400, 1800)])
def test_preview_matches_saved_result(position, crop):
    # 切り抜き表示のプレビューと保存結果（縮小して比べる）で、文字の位置・大きさがそろう
    original = Image.new("RGB", (4000, 3000), BLACK)
    # フレームの余白（白）でも見えるよう赤で描く
    text = TextSettings(text="Sample 2026", color=RED, opacity=100, size=6, position=position)
    settings = EditSettings(crop=crop, width=1000, frame=FrameType.POLAROID, text=text)
    preview, factor = make_preview(original)

    saved = apply_edits(original, settings)
    shown = render_preview(preview, settings, factor, trimmed=True)
    saved_small = saved.resize(shown.size)
    plain = EditSettings(crop=crop, width=1000, frame=FrameType.POLAROID)
    saved_bounds = text_bounds(apply_edits(original, plain).resize(shown.size), saved_small)
    shown_bounds = text_bounds(render_preview(preview, plain, factor, trimmed=True), shown)

    assert saved_bounds is not None and shown_bounds is not None
    for a, b in zip(saved_bounds, shown_bounds, strict=True):
        assert abs(a - b) <= max(3, shown.width * 0.02)


def test_whole_view_draws_text_in_crop_range():
    original = Image.new("RGB", (400, 300), BLACK)
    text = TextSettings(text="X", opacity=100, position=TextPosition.TOP_LEFT)
    settings = EditSettings(crop=CropRect(200, 150, 200, 150), text=text)
    bounds = text_bounds(original, render_preview(original, settings))
    assert bounds is not None
    assert bounds[0] >= 200 and bounds[1] >= 150


# --- プリセット -----------------------------------------------------------------


def test_preset_keeps_text(tmp_path):
    text = TextSettings(
        text="© 透かし\n2 行目",
        font=TextFont.MINCHO,
        size=7.5,
        color=(10, 20, 30),
        opacity=55,
        position=TextPosition.FRAME_MARGIN,
    )
    path = tmp_path / "presets.json"
    save_presets(path, [Preset(name="透かし", text=text)])
    assert load_presets(path)[0].text == text


def test_preset_with_broken_text_is_skipped(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(
        '{"presets": [{"name": "a", "text": {"font": "UNKNOWN"}}, {"name": "b", "text": 3},'
        ' {"name": "c", "text": {"text": "ok", "color": [1, 2]}}, {"name": "d"}]}',
        encoding="utf-8",
    )
    assert [p.name for p in load_presets(path)] == ["d"]


def test_core_text_does_not_import_qt():
    code = (
        "import sys, image_editor.core.text; print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
