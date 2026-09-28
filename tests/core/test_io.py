import subprocess
import sys

import pytest
from PIL import Image

from image_editor.core.io import (
    SUPPORTED_EXTENSIONS,
    LoadedImage,
    UnsupportedImageError,
    flatten_alpha,
    format_for_path,
    is_supported,
    load_image,
    normalize_mode,
    save_image,
)

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)


def make_sample(mode: str = "RGB") -> Image.Image:
    """左半分が赤、右半分が青の 40x20 画像。"""
    image = Image.new("RGB", (40, 20), BLUE)
    image.paste(RED, (0, 0, 20, 20))
    return image.convert(mode)


# --- 拡張子 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["a.png", "a.jpg", "a.jpeg", "a.gif", "a.tif", "a.tiff", "a.bmp", "A.PNG", "b.JpEg"]
)
def test_is_supported(name):
    assert is_supported(name)


@pytest.mark.parametrize("name", ["a.webp", "a.heic", "a.txt", "noext", "png"])
def test_is_not_supported(name):
    assert not is_supported(name)


def test_supported_extensions():
    assert {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp"} == SUPPORTED_EXTENSIONS


def test_format_for_path():
    assert format_for_path("x.JPG") == "JPEG"
    assert format_for_path("x.tif") == "TIFF"
    with pytest.raises(UnsupportedImageError):
        format_for_path("x.webp")


# --- 往復 -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("suffix", "expected_format", "lossless"),
    [
        (".png", "PNG", True),
        (".jpg", "JPEG", False),
        (".jpeg", "JPEG", False),
        (".gif", "GIF", True),
        (".tif", "TIFF", True),
        (".tiff", "TIFF", True),
        (".bmp", "BMP", True),
        (".PNG", "PNG", True),
        (".JPG", "JPEG", False),
    ],
)
def test_round_trip(tmp_path, suffix, expected_format, lossless):
    original = make_sample()
    path = tmp_path / f"sample{suffix}"

    save_image(original, path)
    loaded = load_image(path)

    assert isinstance(loaded, LoadedImage)
    assert loaded.format == expected_format
    assert loaded.path == path
    assert not loaded.is_animated
    assert loaded.image.mode == "RGB"
    assert loaded.image.size == original.size
    if lossless:
        assert loaded.image.tobytes() == original.tobytes()
    else:
        assert _close(loaded.image.getpixel((5, 10)), RED)
        assert _close(loaded.image.getpixel((35, 10)), BLUE)


@pytest.mark.parametrize("suffix", [".png", ".tif"])
def test_round_trip_keeps_alpha(tmp_path, suffix):
    original = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
    path = tmp_path / f"alpha{suffix}"

    save_image(original, path)
    loaded = load_image(path)

    assert loaded.image.mode == "RGBA"
    assert loaded.image.getpixel((0, 0)) == (255, 0, 0, 128)


def test_jpeg_quality_is_used(tmp_path):
    noisy = Image.effect_noise((200, 200), 64).convert("RGB")
    low, high = tmp_path / "low.jpg", tmp_path / "high.jpg"

    save_image(noisy, low, quality=10)
    save_image(noisy, high)

    assert low.stat().st_size < high.stat().st_size


def test_save_unsupported_extension(tmp_path):
    with pytest.raises(UnsupportedImageError):
        save_image(make_sample(), tmp_path / "x.webp")


# --- 透過の白背景合成 ------------------------------------------------------


@pytest.mark.parametrize("suffix", [".jpg", ".bmp"])
def test_rgba_saved_to_opaque_format_becomes_white(tmp_path, suffix):
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (0, 0, 10, 20))
    path = tmp_path / f"transparent{suffix}"

    save_image(image, path)

    with Image.open(path) as saved:
        assert saved.mode == "RGB"
        assert _close(saved.getpixel((15, 10)), WHITE)
        assert _close(saved.getpixel((2, 10)), RED)


def test_save_does_not_modify_source(tmp_path):
    image = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    save_image(image, tmp_path / "x.jpg")
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0)) == (0, 0, 0, 0)


def test_flatten_alpha_half_transparent():
    image = Image.new("RGBA", (1, 1), (0, 0, 0, 128))
    assert _close(flatten_alpha(image).getpixel((0, 0)), (127, 127, 127))


def test_flatten_alpha_palette_transparency():
    image = Image.new("P", (2, 1), 0)
    image.putpalette([*RED, *GREEN])
    image.putpixel((1, 0), 1)
    image.info["transparency"] = 1

    flattened = flatten_alpha(image)

    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == RED
    assert flattened.getpixel((1, 0)) == WHITE


# --- EXIF 回転補正 ----------------------------------------------------------


def test_exif_orientation_6_is_rotated(tmp_path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # 時計回りに 90° 回転して表示
    make_sample().save(path, exif=exif.tobytes(), quality=95)

    loaded = load_image(path)

    assert loaded.image.size == (20, 40)
    # 元画像の左半分（赤）が上に来る
    assert _close(loaded.image.getpixel((10, 5)), RED)
    assert _close(loaded.image.getpixel((10, 35)), BLUE)


# --- モード正規化 -----------------------------------------------------------


def test_load_cmyk_becomes_rgb(tmp_path):
    path = tmp_path / "cmyk.tif"
    make_sample("CMYK").save(path)

    loaded = load_image(path)

    assert loaded.image.mode == "RGB"
    assert _close(loaded.image.getpixel((5, 10)), RED)


def test_load_16bit_becomes_rgb(tmp_path):
    path = tmp_path / "gray16.png"
    Image.new("I;16", (4, 4), 65535).save(path)

    loaded = load_image(path)

    assert loaded.image.mode == "RGB"
    assert loaded.image.getpixel((0, 0)) == (255, 255, 255)


def test_load_16bit_midtone(tmp_path):
    path = tmp_path / "gray16.tif"
    Image.new("I;16", (4, 4), 32768).save(path)

    loaded = load_image(path)

    assert loaded.image.getpixel((0, 0)) == (128, 128, 128)


def test_load_palette_with_transparency_becomes_rgba(tmp_path):
    image = Image.new("P", (2, 1), 0)
    image.putpalette([*RED, *GREEN])
    image.putpixel((1, 0), 1)
    path = tmp_path / "palette.png"
    image.save(path, transparency=1)

    loaded = load_image(path)

    assert loaded.image.mode == "RGBA"
    assert loaded.image.getpixel((0, 0)) == (*RED, 255)
    assert loaded.image.getpixel((1, 0))[3] == 0


def test_load_palette_without_transparency_becomes_rgb(tmp_path):
    path = tmp_path / "palette.png"
    make_sample("P").save(path)

    assert load_image(path).image.mode == "RGB"


@pytest.mark.parametrize(("mode", "expected"), [("LA", "RGBA"), ("L", "RGB"), ("1", "RGB")])
def test_load_gray_modes(tmp_path, mode, expected):
    path = tmp_path / "gray.png"
    Image.new(mode, (4, 4)).save(path)

    assert load_image(path).image.mode == expected


def test_normalize_mode_keeps_rgb_as_is():
    image = make_sample()
    assert normalize_mode(image) is image


# --- 複数フレーム -----------------------------------------------------------


def test_animated_gif_uses_first_frame(tmp_path):
    path = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (8, 8), RED), Image.new("RGB", (8, 8), GREEN)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)

    loaded = load_image(path)

    assert loaded.is_animated
    assert loaded.format == "GIF"
    assert loaded.image.convert("RGB").getpixel((0, 0)) == RED


def test_multipage_tiff_uses_first_page(tmp_path):
    path = tmp_path / "pages.tif"
    pages = [Image.new("RGB", (8, 8), RED), Image.new("RGB", (16, 16), GREEN)]
    pages[0].save(path, save_all=True, append_images=pages[1:])

    loaded = load_image(path)

    assert loaded.is_animated
    assert loaded.image.size == (8, 8)
    assert loaded.image.getpixel((0, 0)) == RED


# --- 異常系 -----------------------------------------------------------------


def test_load_corrupt_file(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"this is not an image")

    with pytest.raises(UnsupportedImageError):
        load_image(path)


def test_load_truncated_file(tmp_path):
    path = tmp_path / "truncated.png"
    Image.effect_noise((200, 200), 64).save(path)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])

    with pytest.raises(UnsupportedImageError):
        load_image(path)


def test_load_unsupported_extension(tmp_path):
    path = tmp_path / "image.webp"
    make_sample().save(path, format="PNG")

    with pytest.raises(UnsupportedImageError):
        load_image(path)


def test_load_unsupported_content_with_supported_extension(tmp_path):
    path = tmp_path / "actually_webp.png"
    make_sample().save(path, format="WEBP")

    with pytest.raises(UnsupportedImageError):
        load_image(path)


def test_load_missing_file(tmp_path):
    with pytest.raises(UnsupportedImageError):
        load_image(tmp_path / "missing.png")


# --- 設計ルール -------------------------------------------------------------


def test_core_io_does_not_import_qt():
    code = (
        "import sys, image_editor.core.io; print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


def _close(actual, expected, tolerance: int = 10) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual[:3], expected, strict=True))
