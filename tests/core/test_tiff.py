import struct

import pytest
from PIL import Image

from image_editor.core.makernote import read_maker_note
from image_editor.core.tiff import (
    TAG_EXIF_IFD,
    TAG_GPS_IFD,
    ExifBlock,
    order_of,
    read_ifd,
    tiff_block,
)

TAKEN = (0x9003, "2026:10:02 09:30:00")
GPS = [(1, "N"), (2, ("rational", [(35, 1), (39, 1), (2187, 100)]))]


def load(data: bytes) -> Image.Exif:
    exif = Image.Exif()
    exif.load(data)
    return exif


@pytest.mark.parametrize("order", ["<", ">"])
def test_round_trip_keeps_values(exif_samples, order):
    source = exif_samples.build_exif(
        make="Canon", model="EOS R5", exif=[TAKEN], gps=GPS, order=order
    )

    data = ExifBlock.parse(source).to_bytes()

    assert data.startswith(b"Exif\0\0" + (b"II" if order == "<" else b"MM"))
    exif = load(data)
    assert exif[0x010F] == "Canon"
    assert exif[0x0110] == "EOS R5"
    assert exif.get_ifd(TAG_EXIF_IFD)[0x9003] == "2026:10:02 09:30:00"
    assert exif.get_ifd(TAG_GPS_IFD)[1] == "N"


def test_maker_note_stays_at_original_offset(exif_samples):
    # Canon の MakerNote は TIFF の先頭からの位置で値を指すので、位置を変えると壊れる
    note = exif_samples.canon_note([(0x0006, "Canon EOS R5 IMAGE TYPE")])
    source = exif_samples.build_exif(make="Canon", exif=[TAKEN], maker_note=note)
    block = ExifBlock.parse(source)
    assert block.maker_note is not None
    at, body = block.maker_note
    assert at == exif_samples.MAKERNOTE_AT

    data = block.to_bytes()

    tiff = tiff_block(data)
    assert tiff[at : at + len(body)] == body
    order = order_of(tiff[:2])
    ifd0 = read_ifd(tiff, struct.unpack(order + "I", tiff[4:8])[0], order)
    assert ifd0[0].tag < ifd0[-1].tag  # タグ番号の小さい順
    assert struct.unpack(order + "I", tiff[4:8])[0] > at  # IFD は MakerNote の後ろに置く


def test_without_maker_note(exif_samples):
    note = exif_samples.canon_note([(0x0006, "Canon EOS R5 IMAGE TYPE")])
    source = exif_samples.build_exif(make="Canon", exif=[TAKEN], maker_note=note)

    data = ExifBlock.parse(source).to_bytes(keep_maker_note=False)

    assert read_maker_note(tiff_block(data)) is None
    assert load(data).get_ifd(TAG_EXIF_IFD)[0x9003] == "2026:10:02 09:30:00"
    assert len(data) < len(source)  # MakerNote の位置まで空けない


def test_thumbnail_and_location_tags_are_dropped(exif_samples):
    # サムネイル (IFD1) と、画像データの位置を指すタグは、保存する画像と合わないので書かない
    source = exif_samples.build_exif(
        exif=[TAKEN],
        thumbnail=True,
        ifd0_extra=[(0x0111, ("long", [1234])), (0x0117, ("long", [10]))],
    )

    data = ExifBlock.parse(source).to_bytes()

    tiff = tiff_block(data)
    order = order_of(tiff[:2])
    ifd0_at = struct.unpack(order + "I", tiff[4:8])[0]
    entries = read_ifd(tiff, ifd0_at, order)
    next_ifd = struct.unpack(order + "I", tiff[ifd0_at + 2 + 12 * len(entries) :][:4])[0]
    assert next_ifd == 0
    assert {entry.tag for entry in entries} == {0x010F, 0x0110, TAG_EXIF_IFD}


def test_no_exif_ifd(exif_samples):
    block = ExifBlock.parse(exif_samples.build_exif())
    block.exif = {}
    exif = load(block.to_bytes())
    assert TAG_EXIF_IFD not in exif
    assert exif[0x010F] == "TestMaker"


def test_set_values(exif_samples):
    block = ExifBlock.parse(exif_samples.build_exif(exif=[(0xA002, ("short", [100]))]))
    block.set_short(block.ifd0, 0x0112, 1)
    block.set_long(block.exif, 0xA002, 70000)  # SHORT に収まらない大きさ

    exif = load(block.to_bytes())

    assert exif[0x0112] == 1
    assert exif.get_ifd(TAG_EXIF_IFD)[0xA002] == 70000


@pytest.mark.parametrize("data", [b"", b"Exif\0\0", b"not exif", b"II*\0\xff\xff\xff\xff"])
def test_parse_rejects_broken(data):
    with pytest.raises(ValueError):
        ExifBlock.parse(data)
