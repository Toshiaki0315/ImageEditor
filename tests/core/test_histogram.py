import subprocess
import sys

from PIL import Image

from image_editor.core.frames import FrameType
from image_editor.core.histogram import BINS, compute_histogram
from image_editor.core.pipeline import (
    EditSettings,
    render_preview,
    render_preview_with_histogram,
)
from image_editor.core.shapes import ShapeType
from image_editor.core.transform import CropRect


def test_compute_histogram_counts_each_channel():
    image = Image.new("RGB", (10, 10), (255, 0, 0))
    image.paste((0, 0, 255), (0, 0, 5, 10))  # 左半分が青

    histogram = compute_histogram(image)

    assert all(len(channel) == BINS for channel in histogram.channels())
    assert histogram.total() == 100
    assert (histogram.red[255], histogram.red[0]) == (50, 50)
    assert histogram.green[0] == 100
    assert (histogram.blue[255], histogram.blue[0]) == (50, 50)
    # 輝度は L 変換（赤 76、青 29）
    assert (histogram.luma[76], histogram.luma[29]) == (50, 50)


def test_transparent_pixels_are_not_counted():
    image = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
    image.paste((0, 0, 0, 255), (0, 0, 4, 10))
    histogram = compute_histogram(image)
    assert histogram.total() == 40
    assert histogram.luma[0] == 40


def test_mask_limits_counted_pixels():
    image = Image.new("RGB", (10, 10), (100, 100, 100))
    mask = Image.new("L", (10, 10), 0)
    mask.paste(255, (0, 0, 3, 10))
    assert compute_histogram(image, mask).total() == 30


def test_input_is_not_modified():
    image = Image.new("RGBA", (4, 4), (1, 2, 3, 4))
    before = image.tobytes()
    compute_histogram(image)
    assert image.tobytes() == before


# --- プレビューと一緒に求めるヒストグラム ----------------------------------------


def sample() -> Image.Image:
    """400x300。左 200 が黒、右 200 が白。"""
    image = Image.new("RGB", (400, 300), (255, 255, 255))
    image.paste((0, 0, 0), (0, 0, 200, 300))
    return image


def test_render_preview_is_same_image():
    settings = EditSettings(exposure=0.5, crop=CropRect(0, 0, 100, 100))
    image, _ = render_preview_with_histogram(sample(), settings)
    assert image.tobytes() == render_preview(sample(), settings).tobytes()


def test_histogram_counts_only_crop_range():
    # 全体表示でも、ヒストグラムは切り抜く範囲（黒い部分）だけを数える
    settings = EditSettings(crop=CropRect(0, 0, 100, 100))
    _, histogram = render_preview_with_histogram(sample(), settings)
    assert histogram.total() == 100 * 100
    assert histogram.luma[0] == 100 * 100


def test_histogram_follows_adjustments():
    _, before = render_preview_with_histogram(sample(), EditSettings())
    _, after = render_preview_with_histogram(sample(), EditSettings(brightness=-100))
    assert before.luma[255] == 200 * 300
    assert after.luma[255] == 200 * 300  # 白は白のまま（明るさは中間を動かす）
    gray = Image.new("RGB", (40, 30), (128, 128, 128))
    _, dark = render_preview_with_histogram(gray, EditSettings(exposure=-2.0))
    # 128 の灰色を -2.0 EV（光の量 1/4）にすると sRGB でおよそ 66 になる
    assert max(range(BINS), key=lambda v: dark.luma[v]) < 80


def test_histogram_excludes_frame_and_outside_shape():
    settings = EditSettings(frame=FrameType.POLAROID, shape=ShapeType.CIRCLE)
    _, histogram = render_preview_with_histogram(sample(), settings, trimmed=True)
    # 中央の正方形 300x300 の、円の中だけ（フレームの白・円の外は数えない）
    assert 300 * 300 * 0.75 < histogram.total() < 300 * 300 * 0.8


def test_histogram_with_scaled_preview():
    preview = sample().resize((200, 150))
    settings = EditSettings(crop=CropRect(0, 0, 200, 300))  # 原画像の座標
    _, histogram = render_preview_with_histogram(preview, settings, factor=0.5)
    assert histogram.total() == 100 * 150
    # 縮小で黒と白の境目の 1 列は灰色に混ざる
    assert histogram.luma[0] >= 99 * 150


def test_core_histogram_does_not_import_qt():
    code = (
        "import sys, image_editor.core.histogram; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
