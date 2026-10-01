import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from image_editor.core.io import (
    MAX_EXIF_BYTES,
    SAVABLE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    LoadedImage,
    SaveOptions,
    UnsupportedImageError,
    default_save_path,
    edited_names,
    flatten_alpha,
    format_for_path,
    is_savable,
    is_supported,
    load_image,
    normalize_mode,
    pasted_image,
    pasted_save_path,
    path_key,
    prepare_exif,
    save_edited,
    save_image,
    save_suffix,
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
    "name",
    [
        "a.png",
        "a.jpg",
        "a.jpeg",
        "a.gif",
        "a.tif",
        "a.tiff",
        "a.bmp",
        "A.PNG",
        "b.JpEg",
        "a.heic",
        "IMG_0001.HEIC",
        "a.heif",
    ],
)
def test_is_supported(name):
    assert is_supported(name)


@pytest.mark.parametrize("name", ["a.webp", "a.txt", "noext", "png"])
def test_is_not_supported(name):
    assert not is_supported(name)


def test_supported_extensions():
    assert {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp"} == SAVABLE_EXTENSIONS
    assert SAVABLE_EXTENSIONS | {".heic", ".heif"} == SUPPORTED_EXTENSIONS


@pytest.mark.parametrize(
    ("name", "savable"), [("a.jpg", True), ("a.HEIC", False), ("a.heif", False)]
)
def test_is_savable(name, savable):
    assert is_savable(name) is savable


def test_save_suffix():
    assert save_suffix("a.PNG") == ".PNG"
    assert save_suffix("IMG_0001.HEIC") == ".jpg"


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


# --- JPEG 品質・EXIF -------------------------------------------------------------

TAG_ORIENTATION = 0x0112
TAG_MAKE = 0x010F
TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825
TAG_DATETIME_ORIGINAL = 0x9003
TAG_PIXEL_X = 0xA002
TAG_PIXEL_Y = 0xA003
TAKEN_AT = "2026:01:02 03:04:05"


def make_exif(orientation: int = 6) -> Image.Exif:
    """撮影日時・カメラ・向き・位置情報を持つ EXIF。"""
    exif = Image.Exif()
    exif[TAG_ORIENTATION] = orientation
    exif[TAG_MAKE] = "TestCamera"
    exif_ifd = exif.get_ifd(TAG_EXIF_IFD)
    exif_ifd[TAG_DATETIME_ORIGINAL] = TAKEN_AT
    exif_ifd[TAG_PIXEL_X] = 40
    exif_ifd[TAG_PIXEL_Y] = 20
    exif.get_ifd(TAG_GPS_IFD)[1] = "N"  # GPSLatitudeRef
    return exif


def read_exif(path) -> tuple[Image.Exif, dict]:
    """保存したファイルの EXIF と Exif IFD を返す（TIFF はファイルを開いている間に読む）。"""
    with Image.open(path) as image:
        exif = image.getexif()
        return exif, dict(exif.get_ifd(TAG_EXIF_IFD))


def test_save_options_defaults():
    options = SaveOptions()
    assert options.quality == 90
    assert options.keep_exif
    assert not options.keep_gps


@pytest.mark.parametrize("quality", [0, 101])
def test_save_quality_out_of_range(tmp_path, quality):
    with pytest.raises(ValueError):
        save_image(make_sample(), tmp_path / "x.jpg", quality=quality)


def test_load_keeps_exif(tmp_path):
    path = tmp_path / "rotated.jpg"
    make_sample().save(path, exif=make_exif(orientation=6))

    loaded = load_image(path)

    # 向きは補正済み（6 = 時計回りに 90° 回して見る）で、EXIF は元のまま持つ
    assert loaded.image.size == (20, 40)
    assert loaded.exif is not None
    exif = Image.Exif()
    exif.load(loaded.exif)
    assert exif[TAG_ORIENTATION] == 6
    assert exif.get_ifd(TAG_EXIF_IFD)[TAG_DATETIME_ORIGINAL] == TAKEN_AT


def test_load_without_exif(tmp_path):
    path = tmp_path / "plain.png"
    make_sample().save(path)
    assert load_image(path).exif is None


def test_load_with_broken_exif_still_loads(tmp_path, monkeypatch):
    path = tmp_path / "plain.png"
    make_sample().save(path)

    def broken(self, *args, **kwargs):
        raise SyntaxError("broken exif")

    # EXIF を書き出せない（壊れている）場合
    monkeypatch.setattr(Image.Exif, "tobytes", broken)

    loaded = load_image(path)

    assert loaded.exif is None
    assert loaded.image.size == (40, 20)


def test_prepare_exif():
    source = make_exif(orientation=6).tobytes()

    prepared = Image.Exif()
    prepared.load(prepare_exif(source, (300, 200)))

    assert prepared[TAG_ORIENTATION] == 1  # 補正済みなので「そのまま」
    assert prepared[TAG_MAKE] == "TestCamera"
    exif_ifd = prepared.get_ifd(TAG_EXIF_IFD)
    assert exif_ifd[TAG_DATETIME_ORIGINAL] == TAKEN_AT
    assert (exif_ifd[TAG_PIXEL_X], exif_ifd[TAG_PIXEL_Y]) == (300, 200)
    assert TAG_GPS_IFD not in prepared  # 位置情報は既定で外す


def test_prepare_exif_keep_gps():
    prepared = Image.Exif()
    prepared.load(prepare_exif(make_exif().tobytes(), (10, 10), keep_gps=True))
    assert prepared.get_ifd(TAG_GPS_IFD)[1] == "N"


def test_prepare_exif_does_not_modify_source():
    source = make_exif().tobytes()
    before = bytes(source)
    prepare_exif(source, (1, 1))
    assert source == before


@pytest.mark.parametrize("suffix", [".jpg", ".png", ".tif"])
def test_save_with_exif(tmp_path, suffix):
    path = tmp_path / f"out{suffix}"
    exif = prepare_exif(make_exif(orientation=6).tobytes(), (40, 20))

    save_image(make_sample(), path, exif=exif)

    saved, exif_ifd = read_exif(path)
    assert saved[TAG_ORIENTATION] == 1
    assert exif_ifd[TAG_DATETIME_ORIGINAL] == TAKEN_AT
    # 他のアプリでも回転せずに、保存したとおりの向きで表示される
    loaded = load_image(path)
    assert loaded.image.size == (40, 20)
    assert _close(loaded.image.getpixel((5, 10)), RED)


@pytest.mark.parametrize("suffix", [".bmp", ".gif"])
def test_exif_is_ignored_for_other_formats(tmp_path, suffix):
    path = tmp_path / f"out{suffix}"
    save_image(make_sample(), path, exif=make_exif().tobytes())
    assert load_image(path).image.size == (40, 20)


def test_save_without_exif(tmp_path):
    path = tmp_path / "out.jpg"
    save_image(make_sample(), path)
    assert len(read_exif(path)[0]) == 0


# --- HEIC / HEIF（読み込みのみ） -------------------------------------------------


def make_heic(path, size=(60, 40), orientation=None):
    """HEIC ファイルを作る（pillow-heif で書く）。左半分が赤、右半分が青。"""
    image = Image.new("RGB", size, BLUE)
    image.paste(RED, (0, 0, size[0] // 2, size[1]))
    exif = Image.Exif()
    exif[0x0132] = "2026:01:02 03:04:05"
    if orientation is not None:
        exif[0x0112] = orientation
    image.save(path, format="HEIF", exif=exif.tobytes(), quality=95)
    return path


def test_load_heic(tmp_path):
    loaded = load_image(make_heic(tmp_path / "IMG_0001.HEIC"))

    assert loaded.format == "HEIF"
    assert loaded.image.mode == "RGB"
    assert loaded.image.size == (60, 40)
    assert _close(loaded.image.getpixel((5, 20)), RED, tolerance=30)
    assert _close(loaded.image.getpixel((55, 20)), BLUE, tolerance=30)
    exif = Image.Exif()
    exif.load(loaded.exif)
    assert exif[0x0132] == "2026:01:02 03:04:05"  # 撮影日時を残す


def test_load_heic_applies_orientation(tmp_path):
    # 向き 6（時計回りに 90° 回して見る）は読み込み時に補正する
    loaded = load_image(make_heic(tmp_path / "rotated.heic", orientation=6))
    assert loaded.image.size == (40, 60)


def test_heic_cannot_be_saved(tmp_path):
    with pytest.raises(UnsupportedImageError):
        save_image(make_sample(), tmp_path / "x.heic")


def test_default_save_path_for_heic_is_jpeg(tmp_path):
    assert default_save_path(tmp_path / "IMG_0001.HEIC") == tmp_path / "IMG_0001_edited.jpg"


def test_edited_names_numbers_and_suffix(tmp_path):
    names = edited_names(tmp_path / "IMG_1.HEIC", tmp_path / "out")
    assert [next(names).name for _ in range(3)] == [
        "IMG_1_edited.jpg",
        "IMG_1_edited_2.jpg",
        "IMG_1_edited_3.jpg",
    ]
    assert next(edited_names(Path("a/b.png"), tmp_path)) == tmp_path / "b_edited.png"


def test_path_key_ignores_case(tmp_path):
    assert path_key(tmp_path / "Photo.JPG") == path_key(tmp_path / "photo.jpg")
    assert path_key(tmp_path / "a.jpg") != path_key(tmp_path / "b.jpg")


def _exif_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x0132] = "2026:10:02 10:00:00"
    exif[0x0112] = 6
    exif.get_ifd(0x8825)[1] = "N"
    return exif.tobytes()


def test_save_edited_follows_options(tmp_path):
    image = Image.new("RGB", (8, 6), RED)
    source_exif = _exif_with_gps()

    kept = tmp_path / "kept.jpg"
    save_edited(image, kept, SaveOptions(keep_exif=True, keep_gps=False), source_exif)
    with Image.open(kept) as saved:
        exif = saved.getexif()
        assert exif[0x0132] == "2026:10:02 10:00:00"
        assert exif[0x0112] == 1
        assert 0x8825 not in exif

    dropped = tmp_path / "dropped.jpg"
    save_edited(image, dropped, SaveOptions(keep_exif=False), source_exif)
    with Image.open(dropped) as saved:
        assert len(saved.getexif()) == 0

    no_source = tmp_path / "none.png"
    save_edited(image, no_source, SaveOptions(), None)
    assert no_source.exists()


def test_load_keeps_raw_exif(tmp_path):
    exif = Image.Exif()
    exif[0x010F] = "RawMaker"
    path = tmp_path / "raw.jpg"
    Image.new("RGB", (4, 4)).save(path, exif=exif.tobytes())

    loaded = load_image(path)

    assert loaded.raw_exif is not None
    assert loaded.raw_exif.startswith(b"Exif\0\0")
    assert b"RawMaker" in loaded.raw_exif

    plain = tmp_path / "plain.png"
    Image.new("RGB", (4, 4)).save(plain)
    assert load_image(plain).raw_exif is None


# --- MakerNote を保つ (#107) ------------------------------------------------------------


def canon_exif(exif_samples, **kwargs) -> bytes:
    note = exif_samples.canon_note(
        [(0x0006, "Canon EOS R5 IMAGE TYPE"), (0x0007, "Firmware Version 1.8.1")]
    )
    return exif_samples.build_exif(
        make="Canon",
        exif=[(0xA002, ("long", [40])), (0xA003, ("long", [20]))],
        maker_note=note,
        **kwargs,
    )


def maker_note_values(path) -> dict[str, str]:
    from image_editor.core.exif_info import ExifGroup, exif_info_of

    info = exif_info_of(load_image(path))
    return {e.tag: e.value for e in info.entries if e.group is ExifGroup.MAKERNOTE}


@pytest.mark.parametrize("suffix", [".jpg", ".png"])
def test_saved_maker_note_is_readable(tmp_path, exif_samples, suffix):
    source = tmp_path / "source.jpg"
    make_sample().save(source, exif=canon_exif(exif_samples))
    loaded = load_image(source)
    assert maker_note_values(source)["ImageType"] == "Canon EOS R5 IMAGE TYPE"

    out = tmp_path / f"out{suffix}"
    save_edited(loaded.image.resize((20, 10)), out, SaveOptions(), loaded.exif)

    values = maker_note_values(out)
    assert values["ImageType"] == "Canon EOS R5 IMAGE TYPE"
    assert values["FirmwareVersion"] == "Firmware Version 1.8.1"
    _, exif_ifd = read_exif(out)
    assert (exif_ifd[TAG_PIXEL_X], exif_ifd[TAG_PIXEL_Y]) == (20, 10)


def test_tiff_output_drops_maker_note(tmp_path, exif_samples):
    # TIFF は Pillow が EXIF を書き直す（MakerNote の中の位置がずれる）ので残さない
    source = tmp_path / "source.jpg"
    make_sample().save(source, exif=canon_exif(exif_samples))
    loaded = load_image(source)

    out = tmp_path / "out.tif"
    save_edited(loaded.image, out, SaveOptions(), loaded.exif)

    assert maker_note_values(out) == {}
    _, exif_ifd = read_exif(out)
    assert exif_ifd[TAG_PIXEL_X] == 40


def test_prepare_exif_drops_maker_note_when_too_large(exif_samples):
    note = exif_samples.pentax_note([(0x0229, "1234567"), (0x03FE, bytes(MAX_EXIF_BYTES))])
    source = exif_samples.build_exif(make="PENTAX", maker_note=note)

    prepared = prepare_exif(source, (10, 10))

    assert len(prepared) <= MAX_EXIF_BYTES
    exif = Image.Exif()
    exif.load(prepared)
    assert 0x927C not in exif.get_ifd(TAG_EXIF_IFD)
    assert exif[TAG_MAKE] == "PENTAX"


def test_prepare_exif_keep_maker_note_false(exif_samples):
    exif = Image.Exif()
    exif.load(prepare_exif(canon_exif(exif_samples), (10, 10), keep_maker_note=False))
    assert 0x927C not in exif.get_ifd(TAG_EXIF_IFD)


def test_prepare_exif_falls_back_to_pillow_for_unknown_layout(monkeypatch):
    # 形を読めない EXIF は Pillow で整える（MakerNote は外す）
    import image_editor.core.io as io_module

    def broken(_data):
        raise ValueError("読めない")

    monkeypatch.setattr(io_module.ExifBlock, "parse", broken)
    prepared = Image.Exif()
    prepared.load(prepare_exif(make_exif(orientation=6).tobytes(), (30, 20)))
    assert prepared[TAG_ORIENTATION] == 1
    assert prepared.get_ifd(TAG_EXIF_IFD)[TAG_PIXEL_X] == 30


def test_load_uses_raw_exif_for_saving(tmp_path, exif_samples):
    path = tmp_path / "raw.jpg"
    make_sample().save(path, exif=canon_exif(exif_samples))
    loaded = load_image(path)
    assert loaded.exif == loaded.raw_exif  # 元のバイト列から保存する


def test_load_tiff_exif_has_no_maker_note(tmp_path):
    # 元のバイト列がない TIFF は Pillow で読み直すので、位置のずれる MakerNote は外しておく
    exif = Image.Exif()
    exif[TAG_MAKE] = "TIFFMaker"
    exif.get_ifd(TAG_EXIF_IFD)[0x927C] = b"\x00" * 20
    path = tmp_path / "with_note.tif"
    make_sample().save(path, exif=exif.tobytes())

    loaded = load_image(path)

    restored = Image.Exif()
    restored.load(loaded.exif)
    assert restored[TAG_MAKE] == "TIFFMaker"
    assert 0x927C not in restored.get_ifd(TAG_EXIF_IFD)


# --- クリップボードから貼り付けた画像 (#109) -------------------------------------------


def test_pasted_image_has_no_file():
    source = Image.new("LA", (6, 4))
    loaded = pasted_image(source)
    assert loaded.path is None
    assert loaded.name == "クリップボードの画像"
    assert loaded.format == "PNG"
    assert loaded.image.mode == "RGBA"  # RGB / RGBA にそろえる
    assert loaded.image is not source
    assert loaded.exif is None and loaded.raw_exif is None


def test_loaded_name_is_file_name(tmp_path):
    path = tmp_path / "photo.png"
    make_sample().save(path)
    assert load_image(path).name == "photo.png"


def test_pasted_save_path(tmp_path):
    from datetime import datetime

    now = datetime(2026, 10, 2, 6, 45, 0)
    first = pasted_save_path(now, tmp_path)
    assert first == tmp_path / "クリップボード_20261002-064500.png"
    first.touch()
    assert pasted_save_path(now, tmp_path) == tmp_path / "クリップボード_20261002-064500_2.png"


def test_pasted_save_path_default_folder(tmp_path, monkeypatch):
    import image_editor.core.io as io_module

    monkeypatch.setattr(io_module, "PICTURES_DIR", tmp_path / "Pictures")
    monkeypatch.setattr(io_module.Path, "home", lambda: tmp_path)
    assert pasted_save_path().parent == tmp_path  # ピクチャフォルダがなければホーム
    (tmp_path / "Pictures").mkdir()
    assert pasted_save_path().parent == tmp_path / "Pictures"
