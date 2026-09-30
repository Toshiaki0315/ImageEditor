import subprocess
import sys

import pytest
from PIL import Image

from image_editor.core.shapes import (
    CORNER_RADIUS_DEFAULT,
    ShapeType,
    apply_shape,
    shape_aspect,
    shape_mask,
)

WHITE = (255, 255, 255)
RED = (255, 0, 0)


def test_shape_labels():
    assert [s.label for s in ShapeType] == ["矩形", "角丸", "円"]


def test_default_corner_radius_is_in_range():
    assert 0 < CORNER_RADIUS_DEFAULT <= 50


def test_shape_aspect():
    assert shape_aspect(ShapeType.RECTANGLE) is None
    assert shape_aspect(ShapeType.ROUNDED) is None
    assert shape_aspect(ShapeType.CIRCLE) == (1, 1)


# --- マスク -------------------------------------------------------------------


def test_rectangle_has_no_mask():
    assert shape_mask((100, 50), ShapeType.RECTANGLE, 30) is None


def test_rounded_with_zero_radius_has_no_mask():
    assert shape_mask((100, 50), ShapeType.ROUNDED, 0) is None


def test_rounded_mask():
    # 短辺 100 の 20% = 半径 20
    mask = shape_mask((200, 100), ShapeType.ROUNDED, 20)

    assert mask is not None
    assert (mask.mode, mask.size) == ("L", (200, 100))
    for corner in [(0, 0), (199, 0), (0, 99), (199, 99)]:
        assert mask.getpixel(corner) == 0
    # 辺の中ほどと中央は内側
    for inside in [(100, 0), (0, 50), (199, 50), (100, 99), (100, 50), (20, 20)]:
        assert mask.getpixel(inside) == 255
    # 円弧の外側 (角から 5px) と内側 (中心から 45° 方向に半径の手前)
    assert mask.getpixel((4, 4)) == 0
    assert mask.getpixel((8, 8)) == 255


def test_rounded_max_radius_is_capsule():
    mask = shape_mask((200, 100), ShapeType.ROUNDED, 50)
    assert mask is not None
    # 両端が半円: 左端の中央は内側、左端の上下 1/4 は外側
    assert mask.getpixel((0, 50)) > 200
    assert mask.getpixel((5, 20)) == 0
    assert mask.getpixel((100, 0)) == 255


def test_rounded_radius_is_clamped():
    assert (
        shape_mask((200, 100), ShapeType.ROUNDED, 80).tobytes()
        == shape_mask((200, 100), ShapeType.ROUNDED, 50).tobytes()
    )


def test_circle_mask_is_centered_on_short_side():
    mask = shape_mask((300, 100), ShapeType.CIRCLE, CORNER_RADIUS_DEFAULT)

    assert mask is not None
    assert mask.size == (300, 100)
    assert mask.getpixel((150, 50)) == 255
    assert mask.getpixel((100, 50)) > 200  # 円の左端
    assert mask.getpixel((90, 50)) == 0  # 円の外（左右の余り）
    assert mask.getpixel((150, 0)) > 200  # 円の上端
    assert mask.getpixel((110, 10)) == 0  # 正方形の角は外


def test_circle_mask_is_symmetric():
    mask = shape_mask((101, 101), ShapeType.CIRCLE, 0)
    assert mask is not None
    assert mask.tobytes() == mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()
    assert mask.tobytes() == mask.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
    assert mask.tobytes() == mask.transpose(Image.Transpose.TRANSPOSE).tobytes()


def test_edge_is_antialiased():
    # 縁には 0 と 255 の間の値がある（ギザギザにならない）
    mask = shape_mask((200, 200), ShapeType.CIRCLE, 0)
    assert mask is not None
    partial_levels = [v for v, count in enumerate(mask.histogram()) if count and 0 < v < 255]
    assert len(partial_levels) > 20
    # 縁の幅は 1〜2px 程度（1 行あたりの中間値は左右それぞれ数 px まで）
    row = [mask.getpixel((x, 100)) for x in range(200)]
    assert sum(1 for v in row if 0 < v < 255) <= 4


@pytest.mark.parametrize("size", [(1, 1), (2, 3), (3, 2), (7, 7)])
def test_small_images(size):
    for shape in (ShapeType.ROUNDED, ShapeType.CIRCLE):
        mask = shape_mask(size, shape, 50)
        assert mask is not None
        assert mask.size == size


# --- apply_shape --------------------------------------------------------------


def test_apply_shape_makes_outside_transparent():
    image = Image.new("RGB", (100, 100), RED)

    result = apply_shape(image, ShapeType.CIRCLE, 0)

    assert result.mode == "RGBA"
    assert result.size == (100, 100)
    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((50, 50)) == (*RED, 255)


def test_apply_shape_keeps_existing_alpha():
    image = Image.new("RGBA", (100, 100), (*RED, 100))

    result = apply_shape(image, ShapeType.ROUNDED, 20)

    assert result.getpixel((50, 50))[3] == 100
    assert result.getpixel((0, 0))[3] == 0


def test_apply_shape_with_fill():
    image = Image.new("RGB", (100, 100), RED)

    result = apply_shape(image, ShapeType.CIRCLE, 0, fill=WHITE)

    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == WHITE
    assert result.getpixel((50, 50)) == RED


def test_apply_shape_with_fill_keeps_photo_alpha():
    # 形の外側は不透明な白、写真の透過はそのまま
    image = Image.new("RGBA", (100, 100), (*RED, 0))

    result = apply_shape(image, ShapeType.CIRCLE, 0, fill=WHITE)

    assert result.mode == "RGBA"
    assert result.getpixel((0, 0)) == (*WHITE, 255)
    assert result.getpixel((50, 50))[3] == 0


def test_apply_rectangle_returns_copy():
    image = Image.new("RGB", (10, 10), RED)
    result = apply_shape(image, ShapeType.RECTANGLE, 30)
    assert result is not image
    assert result.tobytes() == image.tobytes()


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
@pytest.mark.parametrize("fill", [None, WHITE])
def test_apply_shape_does_not_modify_input(mode, fill):
    image = Image.new(mode, (40, 30), RED)
    before = (image.mode, image.size, image.tobytes())
    apply_shape(image, ShapeType.CIRCLE, 0, fill)
    assert (image.mode, image.size, image.tobytes()) == before


def test_core_shapes_does_not_import_qt():
    code = (
        "import sys, image_editor.core.shapes; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
