import subprocess
import sys

import pytest
from PIL import Image

from image_editor.core.filters import (
    FilterType,
    apply_filter,
    output_size,
    polaroid_border_sizes,
)

WHITE = (255, 255, 255)


def make_sample(mode: str = "RGB") -> Image.Image:
    """4 色の帯を持つ 200x100 画像。"""
    image = Image.new("RGB", (200, 100))
    for i, color in enumerate([(200, 60, 40), (40, 160, 80), (50, 70, 210), (128, 128, 128)]):
        image.paste(color, (i * 50, 0, (i + 1) * 50, 100))
    return image.convert(mode)


def sample_points(image: Image.Image, offset: tuple[int, int] = (0, 0)):
    ox, oy = offset
    return [image.getpixel((ox + 25 + i * 50, oy + 50)) for i in range(4)]


# --- FilterType -------------------------------------------------------------


def test_filter_labels():
    assert [f.label for f in FilterType] == [
        "なし",
        "セピア",
        "モノトーン",
        "ハイトーン",
        "ポラロイド風",
    ]


# --- 各フィルター -------------------------------------------------------------


def test_none_returns_equal_copy():
    image = make_sample()

    result = apply_filter(image, FilterType.NONE)

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_sepia():
    image = make_sample()

    result = apply_filter(image, FilterType.SEPIA)

    assert result.mode == "RGB"
    assert result.size == image.size
    for r, g, b in sample_points(result):
        assert r >= g >= b
        assert r > b


def test_sepia_clips_to_255():
    result = apply_filter(Image.new("RGB", (4, 4), WHITE), FilterType.SEPIA)
    assert result.getpixel((0, 0)) == (255, 189, 110)


def test_monotone():
    image = make_sample()

    result = apply_filter(image, FilterType.MONOTONE)

    assert result.mode == "RGB"
    assert result.size == image.size
    points = sample_points(result)
    for r, g, b in points:
        assert r == g == b
    assert len(set(points)) > 1  # 階調が残っている


def test_high_tone_is_brighter():
    image = make_sample()

    result = apply_filter(image, FilterType.HIGH_TONE)

    assert result.mode == "RGB"
    assert result.size == image.size
    gray_before = image.getpixel((175, 50))
    gray_after = result.getpixel((175, 50))
    assert sum(gray_after) > sum(gray_before)


def test_polaroid():
    image = make_sample()
    border, bottom = polaroid_border_sizes(image.size)

    result = apply_filter(image, FilterType.POLAROID)

    assert (border, bottom) == (5, 20)  # 短辺 100 の 5% / 20%
    assert result.mode == "RGB"
    assert result.size == (200 + 5 * 2, 100 + 5 + 20)
    assert result.size == output_size(image.size, FilterType.POLAROID)
    assert bottom > border
    # 白枠
    assert result.getpixel((0, 0)) == WHITE
    assert result.getpixel((result.width - 1, 50)) == WHITE
    assert result.getpixel((100, result.height - 1)) == WHITE
    assert result.getpixel((100, 100 + 5 + 10)) == WHITE
    # 中身は黄みがかる（グレーの R > B）
    r, _, b = result.getpixel((5 + 175, 5 + 50))
    assert r > b


def test_polaroid_portrait_uses_short_side():
    assert polaroid_border_sizes((100, 400)) == (5, 20)


def test_polaroid_border_min_1px():
    assert polaroid_border_sizes((4, 4)) == (1, 1)


@pytest.mark.parametrize("filter_type", [f for f in FilterType if f is not FilterType.POLAROID])
def test_output_size_unchanged(filter_type):
    assert output_size((200, 100), filter_type) == (200, 100)


# --- アルファ ----------------------------------------------------------------


@pytest.mark.parametrize("filter_type", list(FilterType))
def test_alpha_is_preserved(filter_type):
    image = make_sample("RGBA")
    alpha = Image.new("L", image.size, 0)
    alpha.paste(200, (0, 0, 100, 100))
    image.putalpha(alpha)

    result = apply_filter(image, filter_type)

    assert result.mode == "RGBA"
    offset = (5, 5) if filter_type is FilterType.POLAROID else (0, 0)
    alphas = [p[3] for p in sample_points(result, offset)]
    assert alphas == [200, 200, 0, 0]


def test_polaroid_border_is_opaque():
    image = Image.new("RGBA", (100, 100), (255, 0, 0, 0))

    result = apply_filter(image, FilterType.POLAROID)

    assert result.getpixel((0, 0)) == (*WHITE, 255)
    assert result.getpixel((50, result.height - 1)) == (*WHITE, 255)
    assert result.getpixel((50, 50))[3] == 0


@pytest.mark.parametrize("mode", ["L", "P", "LA"])
def test_other_modes_are_normalized(mode):
    result = apply_filter(make_sample(mode), FilterType.SEPIA)
    assert result.mode in ("RGB", "RGBA")


# --- 非破壊 -------------------------------------------------------------------


@pytest.mark.parametrize("filter_type", list(FilterType))
@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_input_is_not_modified(filter_type, mode):
    image = make_sample(mode)
    before = (image.mode, image.size, image.tobytes())

    apply_filter(image, filter_type)

    assert (image.mode, image.size, image.tobytes()) == before


# --- 設計ルール ---------------------------------------------------------------


def test_core_filters_does_not_import_qt():
    code = (
        "import sys, image_editor.core.filters; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
