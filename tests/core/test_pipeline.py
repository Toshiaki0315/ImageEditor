import subprocess
import sys

import pytest
from PIL import Image, ImageChops, ImageFilter, ImageStat

from image_editor.core import filters, pipeline, transform
from image_editor.core.filters import FilterType
from image_editor.core.pipeline import (
    EditSettings,
    apply_edits,
    make_preview,
    output_size,
    render_preview,
    scale_settings,
)
from image_editor.core.transform import CropRect

RED = (255, 0, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)


def make_sample(mode: str = "RGB") -> Image.Image:
    """400x300。左上 200x100 が赤、それ以外が青。"""
    image = Image.new("RGB", (400, 300), BLUE)
    image.paste(RED, (0, 0, 200, 100))
    return image.convert(mode)


# --- EditSettings -------------------------------------------------------------


def test_default_settings_do_nothing():
    image = make_sample()

    result = apply_edits(image, EditSettings())

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_settings_are_frozen():
    settings = EditSettings()
    with pytest.raises(AttributeError):
        settings.width = 10  # type: ignore[misc]


# --- 処理順序 -----------------------------------------------------------------


class _Recorder:
    """モジュールの指定関数だけ呼び出しを記録し、他はそのまま委譲するプロキシ。"""

    def __init__(self, module, names, calls):
        self._module = module
        for name in names:
            setattr(self, name, self._wrap(name, getattr(module, name), calls))

    @staticmethod
    def _wrap(name, func, calls):
        def wrapper(*args, **kwargs):
            calls.append(name)
            return func(*args, **kwargs)

        return wrapper

    def __getattr__(self, item):
        return getattr(self._module, item)


def test_steps_are_called_in_order(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "transform", _Recorder(transform, ["crop", "resize"], calls))
    monkeypatch.setattr(pipeline, "filters", _Recorder(filters, ["apply_filter"], calls))

    settings = EditSettings(crop=CropRect(0, 0, 200, 100), width=100, filter=FilterType.SEPIA)
    apply_edits(make_sample(), settings)

    assert calls == ["crop", "resize", "apply_filter"]


def test_crop_before_resize():
    # 赤い領域 (200x100) を切り抜いてから幅 100 に縮小 → 100x50 の赤一色
    settings = EditSettings(crop=CropRect(0, 0, 200, 100), width=100)

    result = apply_edits(make_sample(), settings)

    assert result.size == (100, 50)
    assert result.getcolors() == [(100 * 50, RED)]


def test_resize_uses_cropped_size_for_aspect():
    settings = EditSettings(crop=CropRect(0, 0, 200, 50), height=100)
    assert apply_edits(make_sample(), settings).size == (400, 100)


def test_filter_after_resize():
    # ポラロイドの枠はリサイズ後のサイズ基準で付く（枠自体は縮小されない）
    settings = EditSettings(width=100, height=100, keep_aspect=False, filter=FilterType.POLAROID)

    result = apply_edits(make_sample(), settings)

    assert result.size == (100 + 5 * 2, 100 + 5 + 20)
    assert result.getpixel((0, 0)) == WHITE
    assert result.getpixel((50, result.height - 1)) == WHITE


def test_crop_out_of_image_is_clamped():
    settings = EditSettings(crop=CropRect(300, 200, 500, 500))
    assert apply_edits(make_sample(), settings).size == (100, 100)


def test_empty_crop_is_ignored():
    settings = EditSettings(crop=CropRect(10, 10, 0, 0))
    assert apply_edits(make_sample(), settings).size == (400, 300)


# --- output_size --------------------------------------------------------------

SETTINGS_CASES = [
    EditSettings(),
    EditSettings(width=123),
    EditSettings(height=77),
    EditSettings(width=120, height=500),
    EditSettings(width=120, height=500, keep_aspect=False),
    EditSettings(crop=CropRect(10, 20, 150, 90)),
    EditSettings(crop=CropRect(10, 20, 150, 90), width=333),
    EditSettings(crop=CropRect(-50, -50, 1000, 1000), height=1),
    EditSettings(crop=CropRect(5, 5, 0, 10), width=1),
    EditSettings(width=20000, keep_aspect=False),
]


@pytest.mark.parametrize("filter_type", list(FilterType))
@pytest.mark.parametrize("settings", SETTINGS_CASES)
def test_output_size_matches_apply_edits(settings, filter_type):
    settings = EditSettings(
        crop=settings.crop,
        width=settings.width,
        height=settings.height,
        keep_aspect=settings.keep_aspect,
        filter=filter_type,
    )
    original = make_sample()

    assert output_size(original.size, settings) == apply_edits(original, settings).size


# --- 非破壊 -------------------------------------------------------------------


@pytest.mark.parametrize("filter_type", list(FilterType))
@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_original_is_not_modified(filter_type, mode):
    original = make_sample(mode)
    before = (original.mode, original.size, original.tobytes())
    settings = EditSettings(crop=CropRect(10, 10, 100, 100), width=50, filter=filter_type)

    apply_edits(original, settings)
    apply_edits(original, settings)

    assert (original.mode, original.size, original.tobytes()) == before


def test_repeated_apply_gives_same_result():
    # 原画像から毎回処理し直すので、何度適用しても結果は同じ (FR-PRC-01)
    original = make_sample()
    settings = EditSettings(filter=FilterType.HIGH_TONE)

    first = apply_edits(original, settings)
    second = apply_edits(original, settings)

    assert first.tobytes() == second.tobytes()


def test_alpha_is_preserved():
    original = make_sample("RGBA")
    original.putalpha(128)
    settings = EditSettings(crop=CropRect(0, 0, 200, 100), width=50, filter=FilterType.SEPIA)

    result = apply_edits(original, settings)

    assert result.mode == "RGBA"
    assert result.getpixel((25, 12))[3] == 128


# --- scale_settings -----------------------------------------------------------


def test_scale_settings():
    settings = EditSettings(
        crop=CropRect(100, 40, 800, 600),
        width=400,
        height=None,
        keep_aspect=True,
        filter=FilterType.POLAROID,
    )

    scaled = scale_settings(settings, 0.25)

    assert scaled == EditSettings(
        crop=CropRect(25, 10, 200, 150),
        width=100,
        height=None,
        keep_aspect=True,
        filter=FilterType.POLAROID,
    )
    assert settings.crop == CropRect(100, 40, 800, 600)  # 元の設定は変わらない


def test_scale_settings_keeps_edges_aligned():
    # 右端 (1 + 3 = 4) を換算すると 2 → 幅 1。幅だけ換算すると 1.5 → 2 で右端が 3 にずれる
    scaled = scale_settings(EditSettings(crop=CropRect(1, 0, 3, 4)), 0.5)
    assert scaled.crop == CropRect(1, 0, 1, 2)


def test_scale_settings_min_1px():
    settings = EditSettings(crop=CropRect(0, 0, 2, 2), width=2, height=1)

    scaled = scale_settings(settings, 0.1)

    assert scaled.crop == CropRect(0, 0, 1, 1)
    assert (scaled.width, scaled.height) == (1, 1)


def test_scale_settings_keeps_empty_crop_empty():
    settings = EditSettings(crop=CropRect(10, 10, 0, 50))
    assert scale_settings(settings, 0.5).crop == CropRect(5, 5, 0, 25)


def test_scale_settings_without_crop_and_size():
    assert scale_settings(EditSettings(), 0.5) == EditSettings()


@pytest.mark.parametrize("factor", [0, -1])
def test_scale_settings_invalid_factor(factor):
    with pytest.raises(ValueError):
        scale_settings(EditSettings(), factor)


def test_scaled_preview_matches_full_size():
    # 縮小プレビューの出力は、原寸出力をほぼ factor 倍したサイズになる
    original = make_sample()
    settings = EditSettings(crop=CropRect(40, 20, 320, 240), width=160)
    factor = 0.5
    preview = original.resize((200, 150))

    full = apply_edits(original, settings)
    scaled = apply_edits(preview, scale_settings(settings, factor))

    assert full.size == (160, 120)
    assert scaled.size == (80, 60)


# --- 設計ルール ---------------------------------------------------------------


def test_core_pipeline_does_not_import_qt():
    code = (
        "import sys, image_editor.core.pipeline; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# --- make_preview -------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "expected_size"),
    [
        ((4000, 3000), (1600, 1200)),
        ((3000, 4000), (1200, 1600)),
        ((3201, 100), (1600, 50)),
    ],
)
def test_make_preview_shrinks_long_side(size, expected_size):
    original = Image.new("RGB", size, (10, 20, 30))

    preview, factor = make_preview(original)

    assert preview.size == expected_size
    assert factor == pytest.approx(1600 / max(size))
    assert preview.getpixel((0, 0)) == (10, 20, 30)
    assert original.size == size


@pytest.mark.parametrize("size", [(1600, 1200), (800, 600), (1, 1)])
def test_make_preview_keeps_small_image(size):
    original = Image.new("RGB", size)

    preview, factor = make_preview(original)

    assert preview is original
    assert factor == 1.0


def test_make_preview_keeps_alpha():
    preview, _ = make_preview(Image.new("RGBA", (3200, 100), (100, 150, 200, 128)))
    assert preview.mode == "RGBA"
    pixel = preview.getpixel((10, 10))
    assert pixel[3] == 128
    assert all(abs(a - b) <= 2 for a, b in zip(pixel[:3], (100, 150, 200), strict=True))


@pytest.mark.parametrize("filter_type", list(FilterType))
def test_preview_looks_like_full_result(filter_type):
    # 縮小版に換算した設定を適用した結果が、原寸の結果を縮小したものとほぼ一致する
    original = Image.linear_gradient("L").resize((3200, 2400)).convert("RGB")
    original.paste((200, 50, 50), (400, 400, 1600, 1200))
    settings = EditSettings(crop=CropRect(200, 200, 2400, 1800), width=1200, filter=filter_type)

    preview, factor = make_preview(original)
    small = apply_edits(preview, scale_settings(settings, factor))
    full = apply_edits(original, settings).resize(small.size, Image.Resampling.LANCZOS)

    assert abs(small.width - full.width) <= 1 and abs(small.height - full.height) <= 1
    if filter_type is FilterType.RETRO_CAMERA:
        # 粒子の模様は解像度ごとに異なるので、ぼかして色の傾向だけを比べる
        small, full = (im.filter(ImageFilter.GaussianBlur(3)) for im in (small, full))
    diff = ImageChops.difference(small, full)
    mean = sum(ImageStat.Stat(diff).mean) / 3
    assert mean < 3


# --- render_preview -----------------------------------------------------------


@pytest.mark.parametrize("filter_type", list(FilterType))
def test_render_preview_keeps_whole_frame(filter_type):
    image = make_sample()
    settings = EditSettings(crop=CropRect(10, 10, 50, 50), width=20, filter=filter_type)

    result = render_preview(image, settings)

    # トリミング・リサイズ・白枠は適用しない
    assert result.size == image.size
    assert result is not image


def test_render_preview_applies_filter_color():
    result = render_preview(make_sample(), EditSettings(filter=FilterType.MONOTONE))
    r, g, b = result.getpixel((300, 200))
    assert r == g == b


def test_render_preview_does_not_modify_input():
    image = make_sample()
    before = image.tobytes()
    render_preview(image, EditSettings(filter=FilterType.SEPIA))
    assert image.tobytes() == before


# --- 周辺減光 -----------------------------------------------------------------


def test_vignette_darkens_output_corners():
    image = Image.new("RGB", (400, 300), (200, 200, 200))

    result = apply_edits(image, EditSettings(vignette=100))

    assert result.getpixel((200, 150)) == (200, 200, 200)
    assert result.getpixel((0, 0))[0] < 60


def test_vignette_is_relative_to_crop():
    image = Image.new("RGB", (400, 300), (200, 200, 200))
    settings = EditSettings(crop=CropRect(100, 100, 200, 100), vignette=100)

    result = apply_edits(image, settings)

    # 切り抜いた範囲の中心は明るく、四隅は暗い
    assert result.size == (200, 100)
    assert result.getpixel((100, 50))[0] == 200
    assert result.getpixel((0, 0))[0] < 60


def test_vignette_is_not_applied_to_polaroid_border():
    image = Image.new("RGB", (200, 200), (200, 200, 200))
    settings = EditSettings(vignette=100, filter=FilterType.POLAROID)

    result = apply_edits(image, settings)

    # 白枠（上・左・右 10px、下 40px）は白のまま、写真部分の四隅は暗い
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert result.getpixel((110, result.height - 5)) == (255, 255, 255)
    assert result.getpixel((10, 10))[0] < 80


def test_polaroid_without_vignette_is_unchanged():
    image = make_sample()
    settings = EditSettings(filter=FilterType.POLAROID)
    expected = filters.apply_filter(image, FilterType.POLAROID)
    assert apply_edits(image, settings).tobytes() == expected.tobytes()


def test_vignette_does_not_change_output_size():
    settings = EditSettings(width=100, vignette=50, filter=FilterType.POLAROID)
    assert output_size((400, 300), settings) == apply_edits(make_sample(), settings).size


def test_scale_settings_keeps_vignette():
    assert scale_settings(EditSettings(vignette=40), 0.5).vignette == 40


# --- render_preview（周辺減光・切り抜き表示） ---------------------------------------


def test_render_preview_vignette_relative_to_crop():
    image = Image.new("RGB", (400, 300), (200, 200, 200))
    settings = EditSettings(crop=CropRect(200, 100, 200, 100), vignette=100)

    result = render_preview(image, settings)

    assert result.size == (400, 300)  # 全体表示のまま
    assert result.getpixel((300, 150))[0] == 200  # 範囲の中心
    assert result.getpixel((200, 100))[0] < 60  # 範囲の左上
    assert result.getpixel((50, 250))[0] == 200  # 範囲外は暗くしない（マスクで表示）


def test_render_preview_uses_scaled_crop():
    # 縮小率 0.5 のプレビューでは、原画像座標の範囲を半分に換算して扱う
    image = Image.new("RGB", (200, 150), (200, 200, 200))
    settings = EditSettings(crop=CropRect(200, 100, 200, 100), vignette=100)

    result = render_preview(image, settings, factor=0.5)

    assert result.getpixel((150, 75))[0] == 200
    assert result.getpixel((100, 50))[0] < 60


def test_render_preview_trimmed():
    image = make_sample()
    settings = EditSettings(crop=CropRect(0, 0, 200, 100), width=50, filter=FilterType.SEPIA)

    result = render_preview(image, settings, trimmed=True)

    # 切り抜いた範囲だけ（リサイズはしない）
    assert result.size == (200, 100)
    r, g, b = result.getpixel((100, 50))
    assert r >= g >= b


def test_render_preview_trimmed_with_scaled_crop():
    image = Image.new("RGB", (200, 150))
    settings = EditSettings(crop=CropRect(100, 50, 200, 100))
    assert render_preview(image, settings, factor=0.5, trimmed=True).size == (100, 50)


def test_render_preview_trimmed_without_crop_shows_whole():
    image = make_sample()
    assert render_preview(image, EditSettings(), trimmed=True).size == image.size
