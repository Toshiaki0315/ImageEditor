import subprocess
import sys

import pytest
from PIL import Image

from image_editor.core.transform import (
    AspectRatio,
    CropRect,
    aspect_drag_rect,
    clamp_crop,
    constrain_rect,
    crop,
    fit_aspect,
    fit_size,
    oriented,
    resize,
)

# --- clamp_crop ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("rect", "expected"),
    [
        # 画像内ならそのまま
        (CropRect(10, 20, 30, 40), CropRect(10, 20, 30, 40)),
        (CropRect(0, 0, 100, 80), CropRect(0, 0, 100, 80)),
        # 右・下へのはみ出し
        (CropRect(90, 70, 50, 50), CropRect(90, 70, 10, 10)),
        # 画像より大きい
        (CropRect(-10, -10, 500, 500), CropRect(0, 0, 100, 80)),
        # 負の座標
        (CropRect(-10, -5, 30, 20), CropRect(0, 0, 20, 15)),
        # 1px
        (CropRect(99, 79, 1, 1), CropRect(99, 79, 1, 1)),
    ],
)
def test_clamp_crop(rect, expected):
    assert clamp_crop(rect, (100, 80)) == expected


@pytest.mark.parametrize(
    "rect",
    [
        CropRect(10, 10, 0, 20),  # 幅 0
        CropRect(10, 10, 20, 0),  # 高さ 0
        CropRect(0, 0, 0, 0),
        CropRect(10, 10, -5, 20),  # 負の幅
        CropRect(100, 0, 10, 10),  # 右外
        CropRect(0, 80, 10, 10),  # 下外
        CropRect(-20, 0, 20, 10),  # 左外（右端がちょうど 0）
        CropRect(0, -30, 10, 10),  # 上外
    ],
)
def test_clamp_crop_returns_none(rect):
    assert clamp_crop(rect, (100, 80)) is None


# --- crop ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rect", "aspect", "expected"),
    [
        # 横長 → 正方形: 左右を均等に削る
        (CropRect(0, 0, 400, 300), (1, 1), CropRect(50, 0, 300, 300)),
        # 縦長 → 正方形: 上下を均等に削る
        (CropRect(10, 20, 100, 301), (1, 1), CropRect(10, 120, 100, 100)),
        # 位置はもとの範囲の中
        (CropRect(100, 50, 200, 100), (46, 62), CropRect(163, 50, 74, 100)),
        # すでに同じ比率なら変えない
        (CropRect(5, 5, 46, 62), (46, 62), CropRect(5, 5, 46, 62)),
        # 最小 1px
        (CropRect(0, 0, 1000, 1), (1, 1000), CropRect(499, 0, 1, 1)),
    ],
)
def test_fit_aspect(rect, aspect, expected):
    assert fit_aspect(rect, aspect) == expected


def test_crop_uses_original_coordinates():
    image = Image.new("RGB", (100, 80), (0, 0, 255))
    image.paste((255, 0, 0), (10, 20, 40, 60))

    cropped = crop(image, CropRect(10, 20, 30, 40))

    assert cropped.size == (30, 40)
    assert cropped.getcolors() == [(30 * 40, (255, 0, 0))]


def test_crop_does_not_modify_source():
    image = Image.new("RGB", (100, 80))
    crop(image, CropRect(0, 0, 10, 10))
    assert image.size == (100, 80)


def test_crop_keeps_alpha():
    image = Image.new("RGBA", (100, 80), (255, 0, 0, 64))

    cropped = crop(image, CropRect(5, 5, 20, 10))

    assert cropped.mode == "RGBA"
    assert cropped.getpixel((0, 0)) == (255, 0, 0, 64)


# --- fit_size -----------------------------------------------------------------


def test_fit_size_nothing_specified():
    assert fit_size((400, 300), None, None, keep_aspect=True) == (400, 300)
    assert fit_size((400, 300), None, None, keep_aspect=False) == (400, 300)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (200, None, (200, 150)),
        (None, 150, (200, 150)),
        (200, 100, (133, 100)),  # 高さ側で制限 → 幅は 133.33 → 133
        (100, 200, (100, 75)),  # 幅側で制限
        (800, 600, (800, 600)),  # 拡大
    ],
)
def test_fit_size_keep_aspect(width, height, expected):
    assert fit_size((400, 300), width, height, keep_aspect=True) == expected


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (200, None, (200, 300)),
        (None, 150, (400, 150)),
        (200, 100, (200, 100)),
    ],
)
def test_fit_size_free_aspect(width, height, expected):
    assert fit_size((400, 300), width, height, keep_aspect=False) == expected


def test_fit_size_rounds_half_up():
    assert fit_size((2, 3), 5, None, keep_aspect=True) == (5, 8)  # 7.5 → 8
    assert fit_size((2, 1), 5, None, keep_aspect=True) == (5, 3)  # 2.5 → 3（round() だと 2）
    assert fit_size((4, 3), 2, None, keep_aspect=True) == (2, 2)  # 1.5 → 2
    assert fit_size((3, 1), 2, None, keep_aspect=True) == (2, 1)  # 0.67 → 1


def test_fit_size_min_1px():
    assert fit_size((1000, 10), 1, None, keep_aspect=True) == (1, 1)
    assert fit_size((10, 1000), None, 1, keep_aspect=True) == (1, 1)
    assert fit_size((20000, 1), 100, None, keep_aspect=True) == (100, 1)


def test_fit_size_1px():
    assert fit_size((400, 300), 1, 1, keep_aspect=False) == (1, 1)
    assert fit_size((400, 300), 1, None, keep_aspect=True) == (1, 1)
    assert fit_size((1, 1), 1, 1, keep_aspect=True) == (1, 1)


def test_fit_size_20000px():
    assert fit_size((400, 300), 20000, None, keep_aspect=True) == (20000, 15000)
    assert fit_size((400, 300), None, 20000, keep_aspect=False) == (400, 20000)
    assert fit_size((1, 1), 20000, 20000, keep_aspect=True) == (20000, 20000)


@pytest.mark.parametrize(("width", "height"), [(0, None), (None, 0), (20001, None), (None, -1)])
def test_fit_size_out_of_range(width, height):
    with pytest.raises(ValueError):
        fit_size((400, 300), width, height, keep_aspect=True)


# --- resize -------------------------------------------------------------------


def test_resize():
    image = Image.new("RGB", (400, 300), (10, 20, 30))

    resized = resize(image, (200, 150))

    assert resized.size == (200, 150)
    assert resized.getpixel((100, 75)) == (10, 20, 30)
    assert image.size == (400, 300)


def test_resize_keeps_alpha():
    image = Image.new("RGBA", (400, 300), (255, 0, 0, 0))
    image.paste((255, 0, 0, 255), (0, 0, 200, 300))

    resized = resize(image, (40, 30))

    assert resized.mode == "RGBA"
    assert resized.getpixel((2, 15))[3] == 255
    assert resized.getpixel((37, 15))[3] == 0


def test_crop_then_resize_keeps_alpha():
    image = Image.new("RGBA", (100, 100), (0, 255, 0, 100))

    result = resize(crop(image, CropRect(10, 10, 50, 50)), (25, 25))

    assert result.mode == "RGBA"
    assert result.getpixel((12, 12)) == (0, 255, 0, 100)


# --- 設計ルール ---------------------------------------------------------------


def test_core_transform_does_not_import_qt():
    code = (
        "import sys, image_editor.core.transform; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# --- 縦横比 -------------------------------------------------------------------


def test_aspect_ratio_labels():
    assert [a.label for a in AspectRatio] == ["自由", "1:1", "4:3", "3:2", "16:9"]


def test_aspect_ratio_orientation():
    assert AspectRatio.FREE.ratio() is None
    assert AspectRatio.FREE.ratio(portrait=True) is None
    assert AspectRatio.RATIO_4_3.ratio() == (4, 3)
    assert AspectRatio.RATIO_4_3.ratio(portrait=True) == (3, 4)
    assert AspectRatio.RATIO_16_9.ratio(portrait=True) == (9, 16)
    assert AspectRatio.SQUARE.ratio(portrait=True) == (1, 1)


def test_oriented():
    assert oriented((46, 62), landscape=True) == (62, 46)
    assert oriented((46, 62), landscape=False) == (46, 62)
    assert oriented((16, 9), landscape=False) == (9, 16)


def keeps_ratio(rect: CropRect, aspect: tuple[float, float]) -> bool:
    """整数に丸めた範囲が、ほぼ（±1px）指定の比になっているか。"""
    aspect_width, aspect_height = aspect
    return (
        abs(rect.height - rect.width * aspect_height / aspect_width) <= 1
        or abs(rect.width - rect.height * aspect_width / aspect_height) <= 1
    )


@pytest.mark.parametrize(
    ("rect", "aspect", "expected"),
    [
        # 画像内で比が違う → 左上を固定して長い方を縮める
        (CropRect(10, 20, 400, 100), (1, 1), CropRect(10, 20, 100, 100)),
        (CropRect(10, 20, 160, 400), (16, 9), CropRect(10, 20, 160, 90)),
        # 画像の外にはみ出す → 画像内に収めてから比に合わせる
        (CropRect(900, 0, 400, 300), (4, 3), CropRect(900, 0, 100, 75)),
        # すでに比どおりならそのまま
        (CropRect(0, 0, 400, 300), (4, 3), CropRect(0, 0, 400, 300)),
    ],
)
def test_constrain_rect(rect, aspect, expected):
    assert constrain_rect(rect, aspect, (1000, 500)) == expected


def test_constrain_rect_outside_image():
    assert constrain_rect(CropRect(2000, 0, 10, 10), (1, 1), (1000, 500)) is None


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        # マウスまで届く大きさ（比に対して長い方の辺に合わせる）
        ((600, 400), CropRect(200, 100, 400, 300)),  # 400x300 はちょうど 4:3
        ((600, 200), CropRect(200, 100, 400, 300)),  # 横に長い → 幅 400 に合わせる
        ((300, 400), CropRect(200, 100, 400, 300)),  # 縦に長い → 高さ 300 に合わせる
        # 左上方向
        ((0, 0), CropRect(67, 0, 133, 100)),  # 高さが画像の端 (100) で止まる
    ],
)
def test_aspect_drag_rect(point, expected):
    result = aspect_drag_rect((200, 100), point, (4, 3), (1000, 500))
    assert result == expected
    assert keeps_ratio(result, (4, 3))


@pytest.mark.parametrize("point", [(1000, 500), (5000, 5000), (0, 500), (1000, 0), (0, 0)])
@pytest.mark.parametrize("aspect", [(1, 1), (4, 3), (3, 4), (16, 9), (46, 62)])
def test_aspect_drag_rect_stays_in_image(point, aspect):
    # 画像の端でも範囲が画像内に収まり、比が保たれる
    image_size = (1000, 500)
    result = aspect_drag_rect((700, 300), point, aspect, image_size)

    assert result.x >= 0 and result.y >= 0
    assert result.x + result.width <= 1000
    assert result.y + result.height <= 500
    assert result.width > 0 and result.height > 0
    assert keeps_ratio(result, aspect)


def test_aspect_drag_rect_click_is_empty():
    result = aspect_drag_rect((100, 100), (100, 100), (4, 3), (1000, 500))
    assert (result.width, result.height) == (0, 0)
