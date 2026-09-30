import subprocess
import sys

import pytest
from PIL import Image

from image_editor.core.batch import (
    BatchOptions,
    batch_settings,
    collect_images,
    output_path,
    process_image,
    run_batch,
)
from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType, framed_size
from image_editor.core.io import SaveOptions, load_image
from image_editor.core.presets import Preset
from image_editor.core.shapes import ShapeType

RED = (220, 60, 30)
PLAIN = Preset(name="なし")
MONO = Preset(name="白黒", saturation=-100)


def make_image(path, size=(400, 300), color=RED, exif=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color)
    if exif is not None:
        image.save(path, exif=exif)
    else:
        image.save(path)
    return path


# --- batch_settings -------------------------------------------------------------


def test_batch_settings_without_resize():
    settings = batch_settings(BatchOptions(look=MONO), (400, 300))
    assert settings.saturation == -100
    assert (settings.width, settings.height, settings.crop) == (None, None, None)


@pytest.mark.parametrize(
    ("size", "expected"),
    [((400, 300), (1000, None)), ((300, 400), (None, 1000)), ((500, 500), (1000, None))],
)
def test_batch_settings_long_side(size, expected):
    settings = batch_settings(BatchOptions(look=PLAIN, long_side=1000), size)
    assert (settings.width, settings.height) == expected
    assert settings.keep_aspect


def test_batch_settings_long_side_uses_frame_window():
    # 横長の画像でも、ポラロイドの写真部分（正方形）に切り抜いてから長辺を決める
    look = Preset(name="ポラ", frame=FrameType.POLAROID)
    settings = batch_settings(BatchOptions(look=look, long_side=500), (400, 300))
    assert (settings.width, settings.height) == (500, None)


@pytest.mark.parametrize("long_side", [0, 20001])
def test_batch_settings_invalid_long_side(long_side):
    with pytest.raises(ValueError):
        batch_settings(BatchOptions(look=PLAIN, long_side=long_side), (10, 10))


# --- output_path ----------------------------------------------------------------


def test_output_path_uses_same_name(tmp_path):
    source = make_image(tmp_path / "in" / "photo.JPG")
    assert output_path(source, tmp_path / "out") == tmp_path / "out" / "photo.JPG"


def test_output_path_avoids_existing(tmp_path):
    source = make_image(tmp_path / "in" / "photo.png")
    out = tmp_path / "out"
    make_image(out / "photo.png")
    make_image(out / "photo_edited.png")

    assert output_path(source, out) == out / "photo_edited_2.png"


def test_output_path_never_overwrites_source(tmp_path):
    # 保存先が元のフォルダでも、元のファイルには書かない
    source = make_image(tmp_path / "photo.png")
    assert output_path(source, tmp_path) == tmp_path / "photo_edited.png"


# --- process_image / run_batch ----------------------------------------------------


def test_process_image(tmp_path):
    exif = Image.Exif()
    exif[0x0132] = "2026:01:02 03:04:05"
    source = make_image(tmp_path / "in" / "a.jpg", size=(800, 600), exif=exif)
    before = source.read_bytes()
    options = BatchOptions(look=MONO, long_side=200, save=SaveOptions(quality=80))

    path = process_image(source, tmp_path / "out", options)

    assert path == tmp_path / "out" / "a.jpg"
    saved = load_image(path)
    assert saved.image.size == (200, 150)
    r, g, b = saved.image.getpixel((100, 75))
    assert abs(r - g) <= 3 and abs(g - b) <= 3  # 白黒
    assert saved.exif is not None  # 「保存の設定」どおり EXIF を残す
    assert source.read_bytes() == before  # 元の画像は変えない


def test_process_image_with_frame_and_shape(tmp_path):
    source = make_image(tmp_path / "a.png", size=(400, 300))
    look = Preset(name="チェキ", frame=FrameType.INSTAX_MINI, shape=ShapeType.CIRCLE)

    path = process_image(source, tmp_path / "out", BatchOptions(look=look))

    saved = load_image(path).image
    # 横長なので横向きのチェキ（写真部分 62:46 に中央で切り抜き）
    assert saved.size == framed_size((400, 297), FrameType.INSTAX_MINI)
    assert saved.getpixel((5, 5)) == (255, 255, 255)


def test_run_batch_reports_progress_and_errors(tmp_path):
    good = [make_image(tmp_path / "in" / f"{i}.png") for i in range(3)]
    broken = tmp_path / "in" / "broken.png"
    broken.write_bytes(b"not an image")
    seen = []

    results = run_batch(
        [good[0], broken, *good[1:]],
        tmp_path / "out",
        BatchOptions(look=Preset(name="セピア", filter=FilterType.SEPIA)),
        progress=lambda done, source: seen.append((done, source.name)),
    )

    assert seen == [(0, "0.png"), (1, "broken.png"), (2, "1.png"), (3, "2.png")]
    assert [r.output is not None for r in results] == [True, False, True, True]
    assert results[1].error and "UnsupportedImageError" in results[1].error
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["0.png", "1.png", "2.png"]


def test_run_batch_cancel(tmp_path):
    sources = [make_image(tmp_path / "in" / f"{i}.png") for i in range(5)]
    done = []

    results = run_batch(
        sources,
        tmp_path / "out",
        BatchOptions(look=PLAIN),
        progress=lambda index, source: done.append(index),
        cancelled=lambda: len(done) >= 2,  # 2 枚目を処理したら中止
    )

    assert len(results) == 2
    assert len(list((tmp_path / "out").iterdir())) == 2


# --- collect_images ---------------------------------------------------------------


def test_collect_images(tmp_path):
    folder = tmp_path / "folder"
    b = make_image(folder / "b.PNG")
    a = make_image(folder / "a.jpg")
    make_image(folder / ".hidden.png")
    (folder / "note.txt").write_text("x")
    make_image(folder / "sub" / "deep.png")  # サブフォルダは見ない
    single = make_image(tmp_path / "single.png")

    images = collect_images([folder, single, a, tmp_path / "missing.png", tmp_path / "x.txt"])

    assert images == [a, b, single]


def test_core_batch_does_not_import_qt():
    code = (
        "import sys, image_editor.core.batch; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
