import subprocess
import sys

import pytest
from PIL import Image, ImageDraw, ImageStat

from image_editor.core.diorama import (
    DIORAMA_TRANSITION,
    DioramaDirection,
    DioramaSettings,
    diorama,
    diorama_band,
)

VERTICAL = DioramaDirection.VERTICAL


def stripes(size: tuple[int, int] = (200, 200), vertical_lines: bool = False) -> Image.Image:
    """細い白黒の縞（ぼかすと灰色に近づくので、ぼけ具合が測りやすい）。"""
    image = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i in range(0, size[0] if not vertical_lines else size[1], 4):
        if vertical_lines:
            draw.line((0, i, size[0], i), fill=(255, 255, 255), width=2)
        else:
            draw.line((i, 0, i, size[1]), fill=(255, 255, 255), width=2)
    return image


def contrast_of(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    """範囲の明るさのばらつき（くっきりしているほど大きい）。"""
    return ImageStat.Stat(image.crop(box).convert("L")).stddev[0]


def test_off_returns_copy():
    image = stripes()
    result = diorama(image, DioramaSettings(blur=0, vivid=100))
    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_band_stays_sharp_and_outside_blurs():
    image = stripes()
    result = diorama(image, DioramaSettings(blur=100, position=50, width=20, vivid=0))

    band = (0, 90, 200, 110)  # 帯の中（上から 40〜60%）
    top = (0, 0, 200, 10)  # 帯から遠い上端
    assert contrast_of(result, band) == pytest.approx(contrast_of(image, band))
    assert contrast_of(result, top) < contrast_of(image, top) * 0.3


def test_blur_grows_away_from_band():
    image = stripes((200, 400))
    result = diorama(image, DioramaSettings(blur=60, position=50, width=10, vivid=0))
    # 帯（180〜220）から離れるほどぼける
    near = contrast_of(result, (0, 150, 200, 160))
    middle = contrast_of(result, (0, 120, 200, 130))
    far = contrast_of(result, (0, 0, 200, 10))
    assert near > middle > far


def test_position_moves_band():
    image = stripes()
    result = diorama(image, DioramaSettings(blur=100, position=10, width=10, vivid=0))
    assert contrast_of(result, (0, 15, 200, 25)) > contrast_of(result, (0, 175, 200, 185)) * 3


def test_vertical_band_blurs_left_and_right():
    image = stripes(vertical_lines=True)
    result = diorama(image, DioramaSettings(blur=100, direction=VERTICAL, vivid=0))
    center = (90, 0, 110, 200)
    left = (0, 0, 10, 200)
    assert contrast_of(result, center) == pytest.approx(contrast_of(image, center))
    assert contrast_of(result, left) < contrast_of(image, left) * 0.3


def test_vivid_raises_saturation():
    image = Image.new("RGB", (100, 100), (150, 110, 90))
    plain = diorama(image, DioramaSettings(blur=10, vivid=0))
    vivid = diorama(image, DioramaSettings(blur=10, vivid=100))
    red, green, blue = vivid.getpixel((50, 50))
    assert plain.getpixel((50, 50)) == (150, 110, 90)
    assert red - blue > 150 - 90


def test_keeps_alpha_and_input():
    image = stripes().convert("RGBA")
    image.putalpha(128)
    before = image.tobytes()

    result = diorama(image, DioramaSettings(blur=50))

    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema() == (128, 128)
    assert image.tobytes() == before


def test_area_positions_band_on_photo():
    # area（写真の範囲）の中央に帯が来る。area の外側にも帯は続く
    image = stripes((200, 400))
    area = (0, 200, 200, 400)  # 下半分が写真
    result = diorama(image, DioramaSettings(blur=100, position=50, width=10, vivid=0), area=area)
    photo_center = (0, 295, 200, 305)
    assert contrast_of(result, photo_center) == pytest.approx(contrast_of(image, photo_center))
    assert contrast_of(result, (0, 0, 200, 10)) < contrast_of(image, (0, 0, 200, 10)) * 0.3


def test_same_look_on_preview_and_full_size():
    # 半径は短辺に比例するので、縮小してからかけても、かけてから縮小しても同じように見える
    big = stripes((800, 800))
    settings = DioramaSettings(blur=80, width=10, vivid=50)
    full_then_small = diorama(big, settings).resize((200, 200), Image.Resampling.BOX)
    small_then = diorama(big.resize((200, 200), Image.Resampling.BOX), settings)
    for box in ((0, 0, 200, 20), (0, 95, 200, 105)):
        assert contrast_of(small_then, box) == pytest.approx(
            contrast_of(full_then_small, box), abs=8
        )


def test_band_values():
    band = diorama_band(DioramaSettings(position=30, width=20))
    assert band.sharp_start == pytest.approx(0.2)
    assert band.sharp_end == pytest.approx(0.4)
    assert band.blur_start == pytest.approx(0.2 - DIORAMA_TRANSITION)
    assert band.blur_end == pytest.approx(0.4 + DIORAMA_TRANSITION)


@pytest.mark.parametrize(
    "settings",
    [
        DioramaSettings(blur=101),
        DioramaSettings(blur=-1),
        DioramaSettings(blur=10, position=101),
        DioramaSettings(blur=10, width=-1),
        DioramaSettings(blur=10, vivid=101),
    ],
)
def test_out_of_range(settings):
    with pytest.raises(ValueError):
        diorama(Image.new("RGB", (10, 10)), settings)


def test_core_diorama_does_not_import_qt():
    code = (
        "import sys, image_editor.core.diorama; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
