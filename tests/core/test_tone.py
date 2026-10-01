import pytest
from PIL import Image

from image_editor.core.tone import (
    add_grain,
    apply_curve,
    clip_table,
    curve_table,
    map_rgb,
    s_curve,
    smoothstep,
)


def test_add_grain_strength():
    image = Image.new("RGB", (256, 256), (128, 128, 128))

    result = add_grain(image, 10, seed=1)

    low, high = result.getchannel("G").getextrema()
    assert 118 <= low < 128 < high <= 138
    assert add_grain(image, 0, seed=1).tobytes() == image.tobytes()


def test_clip_table_rounds_and_clips():
    assert clip_table([-3.0, 0.4, 0.5, 254.6, 300.0]) == [0, 0, 1, 255, 255]


def test_curve_table_identity_and_inverse():
    assert curve_table(lambda x: x) == list(range(256))
    assert curve_table(lambda x: 1 - x) == list(range(255, -1, -1))


@pytest.mark.parametrize("x", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_s_curve_mixes_line_and_smoothstep(x):
    assert s_curve(x, 0.0) == pytest.approx(x)
    assert s_curve(x, 1.0) == pytest.approx(smoothstep(x))
    assert s_curve(x, 0.3) == pytest.approx(0.7 * x + 0.3 * smoothstep(x))


def test_smoothstep_ends_and_middle():
    assert (smoothstep(0.0), smoothstep(0.5), smoothstep(1.0)) == (0.0, 0.5, 1.0)


def test_map_rgb_keeps_alpha_and_does_not_change_input():
    image = Image.new("RGBA", (4, 4), (10, 20, 30, 77))
    before = image.tobytes()

    result = map_rgb(image, lambda rgb: Image.new("RGB", rgb.size, (1, 2, 3)))

    assert result.mode == "RGBA"
    assert result.getpixel((0, 0)) == (1, 2, 3, 77)
    assert image.tobytes() == before


def test_map_rgb_passes_rgb_image():
    seen = []

    def process(rgb: Image.Image) -> Image.Image:
        seen.append(rgb.mode)
        return rgb

    assert map_rgb(Image.new("RGB", (2, 2)), process).mode == "RGB"
    map_rgb(Image.new("RGBA", (2, 2)), process)
    assert seen == ["RGB", "RGB"]


def test_apply_curve_same_on_all_channels():
    image = Image.new("RGBA", (2, 2), (0, 128, 255, 200))

    result = apply_curve(image, lambda x: 1 - x)

    assert result.getpixel((0, 0)) == (255, 127, 0, 200)
