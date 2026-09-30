import subprocess
import sys

import pytest
from PIL import Image

from image_editor.core.frames import (
    FRAME_SPECS,
    FrameType,
    add_frame,
    frame_margins,
    frame_spec,
    framed_size,
    window_aspect,
)

WHITE = (255, 255, 255)


def test_frame_labels():
    assert [f.label for f in FrameType] == ["なし", "ポラロイド", "チェキ"]


@pytest.mark.parametrize(
    ("frame", "card"),
    [(FrameType.POLAROID, (88, 107)), (FrameType.INSTAX_MINI, (54, 86))],
)
def test_specs_match_real_card_size(frame, card):
    spec = FRAME_SPECS[frame]
    left, top, right, bottom = spec.margins
    assert (spec.window[0] + left + right, spec.window[1] + top + bottom) == card
    # 下の余白が一番広い
    assert bottom > max(left, top, right)


def test_window_aspect():
    assert window_aspect(FrameType.NONE, (400, 300)) is None
    assert window_aspect(FrameType.POLAROID, (400, 300)) == (79, 79)
    assert window_aspect(FrameType.INSTAX_MINI, (300, 400)) == (46, 62)
    assert window_aspect(FrameType.INSTAX_MINI, (300, 300)) == (46, 62)


def test_instax_landscape_rotates_card_with_wide_margin_on_right():
    spec = frame_spec(FrameType.INSTAX_MINI, (620, 460))
    assert spec is not None
    assert spec.window == (62, 46)
    # 縦向き (左 4, 上 6.5, 右 4, 下 17.5) を反時計回りに 90° 回す
    assert spec.margins == (6.5, 4, 17.5, 4)


def test_polaroid_landscape_is_not_rotated():
    assert frame_spec(FrameType.POLAROID, (400, 300)) == FRAME_SPECS[FrameType.POLAROID]


def test_frame_margins_scale_with_window():
    # 写真部分 460x620 は 46x62mm の 10 倍
    assert frame_margins(FrameType.INSTAX_MINI, (460, 620)) == (40, 65, 40, 175)
    assert framed_size((460, 620), FrameType.INSTAX_MINI) == (540, 860)


def test_frame_margins_min_1px():
    assert frame_margins(FrameType.POLAROID, (2, 2)) == (1, 1, 1, 1)


def test_frame_margins_none():
    assert frame_margins(FrameType.NONE, (100, 100)) == (0, 0, 0, 0)
    assert framed_size((100, 100), FrameType.NONE) == (100, 100)


def test_frame_margins_use_fitting_scale_for_other_aspect():
    # 写真部分と比率が違う（リサイズで縦横比を変えた）ときは、収まる側の縮尺に合わせる
    assert frame_margins(FrameType.POLAROID, (790, 395)) == frame_margins(
        FrameType.POLAROID, (395, 395)
    )


@pytest.mark.parametrize("frame", [FrameType.POLAROID, FrameType.INSTAX_MINI])
def test_add_frame(frame):
    image = Image.new("RGB", (460, 620), (255, 0, 0))

    result = add_frame(image, frame)

    left, top, right, bottom = frame_margins(frame, image.size)
    assert result.mode == "RGB"
    assert result.size == (460 + left + right, 620 + top + bottom)
    assert result.getpixel((0, 0)) == WHITE
    assert result.getpixel((result.width - 1, result.height - 1)) == WHITE
    assert result.getpixel((left, top)) == (255, 0, 0)
    assert result.getpixel((left + 459, top + 619)) == (255, 0, 0)


def test_add_frame_keeps_alpha_and_frame_is_opaque():
    image = Image.new("RGBA", (100, 100), (255, 0, 0, 0))

    result = add_frame(image, FrameType.POLAROID)

    left, top, _, _ = frame_margins(FrameType.POLAROID, image.size)
    assert result.mode == "RGBA"
    assert result.getpixel((0, 0)) == (*WHITE, 255)
    assert result.getpixel((50, result.height - 1)) == (*WHITE, 255)
    assert result.getpixel((left + 50, top + 50))[3] == 0


def test_add_frame_none_returns_copy():
    image = Image.new("RGB", (10, 10), (1, 2, 3))
    result = add_frame(image, FrameType.NONE)
    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_add_frame_does_not_modify_input():
    image = Image.new("RGBA", (50, 40), (1, 2, 3, 4))
    before = (image.mode, image.size, image.tobytes())
    add_frame(image, FrameType.INSTAX_MINI)
    assert (image.mode, image.size, image.tobytes()) == before


def test_core_frames_does_not_import_qt():
    code = (
        "import sys, image_editor.core.frames; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
