import pytest
from PIL import Image

from image_editor.core.exif_info import (
    ExifEntry,
    ExifGroup,
    GpsPosition,
    exif_info_of,
    format_dms,
    read_exif_info,
    tiff_block,
)
from image_editor.core.io import load_image

GPS = [
    (1, "N"),
    (2, ("rational", [(35, 1), (39, 1), (2187, 100)])),
    (3, "E"),
    (4, ("rational", [(139, 1), (45, 1), (30, 1)])),
    (5, b"\x00"),
    (6, ("rational", [(123, 10)])),
]
EXIF = [
    (0x829A, ("rational", [(1, 125)])),  # ExposureTime
    (0x829D, ("rational", [(28, 10)])),  # FNumber
    (0x8827, ("short", [400])),  # ISOSpeedRatings
    (0x9003, "2026:10:02 09:30:00"),  # DateTimeOriginal
]


def entry(info, group: ExifGroup, tag: str) -> ExifEntry:
    (found,) = [e for e in info.entries if e.group is group and e.tag == tag]
    return found


def test_reads_all_groups_with_japanese_labels(exif_samples):
    data = exif_samples.build_exif(make="Canon", model="Canon EOS R5", exif=EXIF, gps=GPS)
    info = read_exif_info(data)

    assert not info.is_empty()
    assert [group for group, _ in info.groups()] == [
        ExifGroup.IMAGE,
        ExifGroup.EXIF,
        ExifGroup.GPS,
    ]
    make = entry(info, ExifGroup.IMAGE, "Make")
    assert (make.label, make.value) == ("Make（メーカー）", "Canon")
    exposure = entry(info, ExifGroup.EXIF, "ExposureTime")
    assert (exposure.label, exposure.value) == ("ExposureTime（露出時間）", "1/125")
    assert entry(info, ExifGroup.EXIF, "ISOSpeedRatings").value == "400"
    assert entry(info, ExifGroup.EXIF, "DateTimeOriginal").label == "DateTimeOriginal（撮影日時）"
    # ほかの IFD を指すだけのタグは出さない
    assert not [e for e in info.entries if e.tag in ("ExifOffset", "GPSInfo")]


def test_label_without_translation():
    assert ExifEntry(ExifGroup.MAKERNOTE, "Tag 0x7777", "1").label == "Tag 0x7777"


def test_gps_is_readable(exif_samples):
    info = read_exif_info(exif_samples.build_exif(gps=GPS))

    assert info.gps == GpsPosition(pytest.approx(35.656075), pytest.approx(139.758333, abs=1e-6))
    latitude = entry(info, ExifGroup.GPS, "GPSLatitude").value
    assert latitude == "35° 39′ 21.87″ N（35.656075）"
    assert entry(info, ExifGroup.GPS, "GPSLongitude").value.startswith("139° 45′ 30.00″ E")
    assert entry(info, ExifGroup.GPS, "GPSAltitude").value == "海抜 12.3 m"


def test_gps_south_west(exif_samples):
    gps = [(1, "S"), GPS[1], (3, "W"), GPS[3]]
    info = read_exif_info(exif_samples.build_exif(gps=gps))
    assert info.gps.latitude < 0 and info.gps.longitude < 0
    assert entry(info, ExifGroup.GPS, "GPSLatitude").value.startswith("35° 39′ 21.87″ S")
    assert entry(info, ExifGroup.GPS, "GPSLongitude").value.endswith("（-139.758333）")


def test_map_url():
    url = GpsPosition(35.656075, -139.75).map_url()
    assert url == "maps://?ll=35.656075,-139.750000&q=35.656075,-139.750000"


@pytest.mark.parametrize(
    ("degrees", "text"),
    [
        (35.656075, "35° 39′ 21.87″ N"),
        (-0.5, "0° 30′ 0.00″ S"),
        (10.999999, "11° 0′ 0.00″ N"),  # 60.00″ に繰り上がらない
    ],
)
def test_format_dms(degrees, text):
    assert format_dms(degrees, "N", "S") == text


def test_maker_note_by_exifread(exif_samples):
    note = exif_samples.canon_note([(0x0006, "Canon EOS R5 IMG"), (0x000C, ("long", [123456]))])
    info = read_exif_info(exif_samples.build_exif(make="Canon", maker_note=note))
    assert info.maker_note == "Canon"
    serial = entry(info, ExifGroup.MAKERNOTE, "SerialNumber")
    assert (serial.label, serial.value) == ("SerialNumber（シリアル番号）", "123456")
    assert not [e for e in info.entries if e.tag == "MakerNote"]  # 中身を読めたら塊は出さない


def test_maker_note_apple(exif_samples):
    note = exif_samples.apple_note([(0x0001, ("long", [14]))])
    data = exif_samples.build_exif(make="Apple", model="iPhone 15 Pro", order=">", maker_note=note)
    info = read_exif_info(data)
    assert info.maker_note == "Apple"
    assert entry(info, ExifGroup.MAKERNOTE, "MakerNoteVersion").value == "14"


@pytest.mark.parametrize(
    ("make", "builder", "name"),
    [
        ("PENTAX", "pentax_note", "Pentax"),
        ("RICOH IMAGING", "ricoh_pentax_note", "Ricoh（Pentax 形式）"),
        ("samsung", "samsung_note", "Samsung"),
    ],
)
def test_maker_note_by_own_reader(exif_samples, make, builder, name):
    note = getattr(exif_samples, builder)([(0x0229, "SERIAL-1"), (0xA002, "SERIAL-2")])
    info = read_exif_info(exif_samples.build_exif(make=make, maker_note=note))
    assert info.maker_note == name
    values = {e.value for e in info.entries if e.group is ExifGroup.MAKERNOTE}
    assert {"SERIAL-1", "SERIAL-2"} <= values


def test_undecodable_maker_note_is_summarized(exif_samples):
    data = exif_samples.build_exif(make="Xiaomi", maker_note=b"\xff" * 50)
    info = read_exif_info(data)
    assert info.maker_note == "不明な形式（解読できない形式）"
    summary = entry(info, ExifGroup.MAKERNOTE, "MakerNote")
    assert summary.value == "解読できない形式（50 バイト）"


def test_broken_maker_note_keeps_other_tags(exif_samples):
    # exifread が MakerNote の読み取りで失敗しても、ほかのタグは出す
    note = b"Nikon\0\x02\x10\0\0" + bytes(30)
    info = read_exif_info(exif_samples.build_exif(make="NIKON CORPORATION", maker_note=note))
    assert entry(info, ExifGroup.IMAGE, "Make").value == "NIKON CORPORATION"


@pytest.mark.parametrize("raw", [None, b"", b"Exif\0\0", b"garbage"])
def test_no_exif(raw):
    info = read_exif_info(raw)
    assert info.is_empty()
    assert info.groups() == []
    assert info.gps is None


def test_tiff_block_strips_header():
    assert tiff_block(b"Exif\0\0II*\0rest") == b"II*\0rest"
    assert tiff_block(b"MM\0*rest") == b"MM\0*rest"
    assert tiff_block(b"Exif\0\0nope") is None


def test_structure_tags_alone_count_as_empty():
    info = read_exif_info(None)
    assert info.is_empty()
    only_structure = type(info)((ExifEntry(ExifGroup.IMAGE, "ImageWidth", "4"),))
    assert only_structure.is_empty()


def test_exif_info_of_jpeg_and_tiff(tmp_path, exif_samples):
    image = Image.new("RGB", (8, 8))
    jpeg = tmp_path / "a.jpg"
    image.save(jpeg, exif=exif_samples.build_exif(make="Canon", exif=EXIF))
    info = exif_info_of(load_image(jpeg))
    assert entry(info, ExifGroup.EXIF, "FNumber").value == "14/5"

    exif = Image.Exif()
    exif[0x010F] = "TIFFMaker"
    tiff = tmp_path / "a.tif"
    image.save(tiff, exif=exif.tobytes())
    info = exif_info_of(load_image(tiff))
    assert entry(info, ExifGroup.IMAGE, "Make").value == "TIFFMaker"

    plain = tmp_path / "plain.tif"
    image.save(plain)
    assert exif_info_of(load_image(plain)).is_empty()  # 画像の構造のタグしかない

    png = tmp_path / "a.png"
    image.save(png)
    assert exif_info_of(load_image(png)).is_empty()
