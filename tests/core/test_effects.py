import subprocess
import sys

import pytest
from PIL import Image

from image_editor.core.effects import vignette

GRAY = (200, 200, 200)


def brightness(image, x, y):
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
    assert brightness(result, 100, 50) == 200  # 中心は変わらない
    assert brightness(result, 0, 0) <= 200 * (1 - 0.8) + 2  # 四隅は最大 8 割暗く
    assert brightness(result, 0, 50) < brightness(result, 50, 50) < 200  # 外側ほど暗い


def test_strength_is_monotonic():
    image = Image.new("RGB", (100, 100), GRAY)
    corners = [brightness(vignette(image, amount), 0, 0) for amount in (0, 25, 50, 75, 100)]
    assert corners == sorted(corners, reverse=True)
    assert len(set(corners)) == 5


def test_follows_aspect_ratio():
    # 横長の画像では左右の端と上下の端が同じくらい暗くなる（楕円状）
    result = vignette(Image.new("RGB", (400, 100), GRAY), 100)
    assert abs(brightness(result, 0, 50) - brightness(result, 200, 0)) <= 3


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
