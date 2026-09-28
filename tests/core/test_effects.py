import subprocess
import sys

import pytest
from PIL import Image, ImageStat

from image_editor.core.effects import (
    aging,
    brightness,
    color_temperature,
    kelvin_to_rgb,
    saturation,
    temperature_multipliers,
    vignette,
)

GRAY = (200, 200, 200)


def pixel_value(image, x, y):
    return image.getpixel((x, y))[0]


def test_zero_is_unchanged_copy():
    image = Image.new("RGB", (100, 80), GRAY)

    result = vignette(image, 0)

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_corners_get_darker_center_stays():
    image = Image.new("RGB", (200, 100), GRAY)

    result = vignette(image, 100)

    assert result.size == image.size
    assert pixel_value(result, 100, 50) == 200  # 中心は変わらない
    assert pixel_value(result, 0, 0) <= 200 * (1 - 0.8) + 2  # 四隅は最大 8 割暗く
    assert pixel_value(result, 0, 50) < pixel_value(result, 50, 50) < 200  # 外側ほど暗い


def test_strength_is_monotonic():
    image = Image.new("RGB", (100, 100), GRAY)
    corners = [pixel_value(vignette(image, amount), 0, 0) for amount in (0, 25, 50, 75, 100)]
    assert corners == sorted(corners, reverse=True)
    assert len(set(corners)) == 5


def test_follows_aspect_ratio():
    # 横長の画像では左右の端と上下の端が同じくらい暗くなる（楕円状）
    result = vignette(Image.new("RGB", (400, 100), GRAY), 100)
    assert abs(pixel_value(result, 0, 50) - pixel_value(result, 200, 0)) <= 3


def test_keeps_alpha():
    image = Image.new("RGBA", (100, 100), (200, 200, 200, 77))

    result = vignette(image, 80)

    assert result.mode == "RGBA"
    assert result.getpixel((0, 0))[3] == 77
    assert result.getpixel((0, 0))[0] < 200


def test_does_not_modify_input():
    image = Image.new("RGB", (50, 50), GRAY)
    before = image.tobytes()
    vignette(image, 100)
    assert image.tobytes() == before


@pytest.mark.parametrize("amount", [-1, 101])
def test_out_of_range(amount):
    with pytest.raises(ValueError):
        vignette(Image.new("RGB", (10, 10)), amount)


def test_core_effects_does_not_import_qt():
    code = (
        "import sys, image_editor.core.effects; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# --- 経年劣化 -----------------------------------------------------------------


def colorful() -> Image.Image:
    """4 色の帯と黒・白を持つ 240x80 画像。"""
    image = Image.new("RGB", (240, 80))
    colors = [(220, 40, 40), (40, 180, 60), (40, 60, 220), (240, 200, 40), (0, 0, 0), (255,) * 3]
    for i, color in enumerate(colors):
        image.paste(color, (i * 40, 0, (i + 1) * 40, 80))
    return image


def band_mean(image: Image.Image, index: int) -> list[float]:
    return ImageStat.Stat(image.crop((index * 40, 0, (index + 1) * 40, 80))).mean


def mean_saturation(image: Image.Image) -> float:
    """色の帯（左 4 本）の平均彩度。黒・白の帯は黄ばみで彩度が出るので含めない。"""
    return ImageStat.Stat(image.crop((0, 0, 160, 80)).convert("HSV")).mean[1]


def test_aging_zero_is_unchanged_copy():
    image = colorful()

    result = aging(image, 0)

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_aging_reduces_saturation_as_amount_grows():
    image = colorful()
    values = [mean_saturation(aging(image, amount)) for amount in (0, 25, 50, 75, 100)]
    assert values == sorted(values, reverse=True)
    assert values[-1] < values[0] * 0.6


def test_aging_fades_blacks_and_whites():
    black = [band_mean(aging(colorful(), a), 4)[1] for a in (0, 50, 100)]
    white = [band_mean(aging(colorful(), a), 5)[1] for a in (0, 50, 100)]

    assert black[0] < black[1] < black[2]  # 黒が浮く
    assert black[2] > 30
    assert white[0] > white[1] > white[2]  # 白が抑えられる
    assert white[2] < 240


def test_aging_turns_yellowish():
    gray = Image.new("RGB", (64, 64), (160, 160, 160))

    r, g, b = ImageStat.Stat(aging(gray, 100)).mean

    assert r > g > b
    assert r - b > 40


def test_aging_grain_grows_with_amount():
    gray = Image.new("RGB", (128, 128), (128, 128, 128))
    stddev = [ImageStat.Stat(aging(gray, a)).stddev[1] for a in (0, 30, 100)]
    assert stddev[0] == 0
    assert 0 < stddev[1] < stddev[2]


def test_aging_is_deterministic():
    image = colorful()
    assert aging(image, 70).tobytes() == aging(image, 70).tobytes()


def test_aging_keeps_alpha_and_size():
    image = colorful().convert("RGBA")
    image.putalpha(90)

    result = aging(image, 80)

    assert result.mode == "RGBA"
    assert result.size == image.size
    assert result.getchannel("A").getextrema() == (90, 90)


def test_aging_does_not_modify_input():
    image = colorful()
    before = image.tobytes()
    aging(image, 100)
    assert image.tobytes() == before


@pytest.mark.parametrize("amount", [-1, 101])
def test_aging_out_of_range(amount):
    with pytest.raises(ValueError):
        aging(Image.new("RGB", (10, 10)), amount)


# --- 色温度 -------------------------------------------------------------------


def luma(image: Image.Image) -> float:
    return ImageStat.Stat(image.convert("L")).mean[0]


def test_temperature_neutral_is_unchanged_copy():
    image = colorful()

    result = color_temperature(image, 6500)

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_low_kelvin_is_warm():
    r, g, b = ImageStat.Stat(color_temperature(Image.new("RGB", (8, 8), (150,) * 3), 3000)).mean
    assert r > g > b


def test_high_kelvin_is_cool():
    r, _, b = ImageStat.Stat(color_temperature(Image.new("RGB", (8, 8), (150,) * 3), 10000)).mean
    assert b > r


def test_warmth_is_monotonic():
    gray = Image.new("RGB", (8, 8), (150,) * 3)
    warmth = []
    for kelvin in (2000, 3000, 4500, 6500, 8000, 10000):
        r, _, b = color_temperature(gray, kelvin).getpixel((0, 0))
        warmth.append(r - b)
    assert warmth == sorted(warmth, reverse=True)
    assert warmth[3] == 0


@pytest.mark.parametrize("kelvin", [2000, 3000, 10000])
def test_temperature_keeps_brightness(kelvin):
    gray = Image.new("RGB", (8, 8), (128,) * 3)
    assert abs(luma(color_temperature(gray, kelvin)) - 128) <= 6


def test_multipliers_are_neutral_at_6500():
    assert temperature_multipliers(6500) == pytest.approx((1.0, 1.0, 1.0))


def test_kelvin_to_rgb_reference_points():
    red, _, blue = kelvin_to_rgb(2000)
    assert red == 255 and blue < 50  # 暖色
    red, _, blue = kelvin_to_rgb(10000)
    assert blue == 255 and red < 220  # 青み


def test_temperature_keeps_alpha():
    image = colorful().convert("RGBA")
    image.putalpha(33)

    result = color_temperature(image, 3000)

    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema() == (33, 33)


def test_temperature_does_not_modify_input():
    image = colorful()
    before = image.tobytes()
    color_temperature(image, 2500)
    assert image.tobytes() == before


@pytest.mark.parametrize("kelvin", [1999, 10001])
def test_temperature_out_of_range(kelvin):
    with pytest.raises(ValueError):
        color_temperature(Image.new("RGB", (10, 10)), kelvin)


# --- 彩度 ---------------------------------------------------------------------


def test_saturation_zero_is_unchanged_copy():
    image = colorful()

    result = saturation(image, 0)

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_saturation_minus_100_is_grayscale():
    result = saturation(colorful(), -100)
    for x in range(0, 240, 40):
        r, g, b = result.getpixel((x + 5, 5))
        assert max(r, g, b) - min(r, g, b) <= 1


def test_saturation_is_monotonic():
    image = colorful()
    values = [
        ImageStat.Stat(saturation(image, a).crop((0, 0, 160, 80)).convert("HSV")).mean[1]
        for a in (-100, -50, 0, 50, 100)
    ]
    assert values == sorted(values)
    assert values[0] < 5


def test_saturation_keeps_gray_and_brightness():
    gray = Image.new("RGB", (8, 8), (120, 120, 120))
    assert saturation(gray, 100).getpixel((0, 0)) == (120, 120, 120)
    assert saturation(gray, -100).getpixel((0, 0)) == (120, 120, 120)


def test_saturation_keeps_alpha():
    image = colorful().convert("RGBA")
    image.putalpha(12)

    result = saturation(image, 60)

    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema() == (12, 12)


def test_saturation_does_not_modify_input():
    image = colorful()
    before = image.tobytes()
    saturation(image, -70)
    assert image.tobytes() == before


@pytest.mark.parametrize("amount", [-101, 101])
def test_saturation_out_of_range(amount):
    with pytest.raises(ValueError):
        saturation(Image.new("RGB", (10, 10)), amount)


# --- 明るさ -------------------------------------------------------------------


def test_brightness_zero_is_unchanged_copy():
    image = colorful()

    result = brightness(image, 0)

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_brightness_raises_and_lowers_midtones():
    gray = Image.new("RGB", (8, 8), (128, 128, 128))
    values = [brightness(gray, a).getpixel((0, 0))[0] for a in (-100, -50, 0, 50, 100)]
    assert values == sorted(values)
    assert values[2] == 128
    assert values[0] < 40 and values[-1] > 200


def test_brightness_keeps_black_and_white():
    image = colorful()  # 黒と白の帯を含む
    for amount in (-100, 100):
        result = brightness(image, amount)
        assert result.getpixel((165, 5)) == (0, 0, 0)
        assert result.getpixel((205, 5)) == (255, 255, 255)


def test_brightness_keeps_alpha():
    image = colorful().convert("RGBA")
    image.putalpha(99)

    result = brightness(image, 40)

    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema() == (99, 99)


def test_brightness_does_not_modify_input():
    image = colorful()
    before = image.tobytes()
    brightness(image, -60)
    assert image.tobytes() == before


@pytest.mark.parametrize("amount", [-101, 101])
def test_brightness_out_of_range(amount):
    with pytest.raises(ValueError):
        brightness(Image.new("RGB", (10, 10)), amount)
