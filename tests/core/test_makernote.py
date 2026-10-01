import subprocess
import sys

import pytest

from image_editor.core.makernote import (
    MAX_VALUES_SHOWN,
    PENTAX_TAGS,
    format_value,
    read_maker_note,
)


def tiff(exif_samples, **kwargs) -> bytes:
    return exif_samples.build_exif(prefix=False, **kwargs)


def tags_of(result) -> dict[str, str]:
    return {tag.name: tag.value for tag in result.tags}


def test_no_maker_note(exif_samples):
    assert read_maker_note(tiff(exif_samples)) is None


def test_not_tiff():
    assert read_maker_note(b"not a tiff at all") is None


@pytest.mark.parametrize("order", ["<", ">"])
def test_pentax_type5(exif_samples, order):
    note = exif_samples.pentax_note(
        [(0x0229, "1234567"), (0x0014, ("short", [100])), (0x0230, "1.40")], order=order
    )
    result = read_maker_note(tiff(exif_samples, make="PENTAX", maker_note=note))
    assert result.format == "Pentax"
    assert tags_of(result) == {"SerialNumber": "1234567", "ISO": "100", "FirmwareVersion": "1.40"}


def test_pentax_aoc(exif_samples):
    note = exif_samples.aoc_note([(0x0008, ("short", [2])), (0x0006, b"\x07\xe6\x0a\x02")])
    result = read_maker_note(tiff(exif_samples, make="PENTAX Corporation", maker_note=note))
    assert result.format == "Pentax"
    assert tags_of(result) == {"Quality": "2", "Date": "07 e6 0a 02"}


def test_ricoh_pentax_format(exif_samples):
    note = exif_samples.ricoh_pentax_note([(0x0229, "GR3SERIAL")])
    result = read_maker_note(tiff(exif_samples, make="RICOH IMAGING", maker_note=note))
    assert result.format == "Ricoh（Pentax 形式）"
    assert tags_of(result) == {"SerialNumber": "GR3SERIAL"}


def test_ricoh_old_format_with_absolute_offsets(exif_samples):
    note = exif_samples.ricoh_note([(0x0001, "Rev0101"), (0x1003, ("short", [1]))])
    result = read_maker_note(tiff(exif_samples, make="RICOH", maker_note=note))
    assert result.format == "Ricoh"
    assert tags_of(result) == {"MakerNoteType": "Rev0101", "Sharpness": "1"}


def test_samsung_type2(exif_samples):
    note = exif_samples.samsung_note(
        [(0x0001, b"0100"), (0x0002, ("long", [0x12000])), (0xA002, "R3CW12345")]
    )
    result = read_maker_note(tiff(exif_samples, make="samsung", maker_note=note))
    assert result.format == "Samsung"
    assert tags_of(result) == {
        "MakerNoteVersion": "0100",
        "DeviceType": str(0x12000),
        "SerialNumber": "R3CW12345",
    }


def test_unknown_tags_use_numbers(exif_samples):
    note = exif_samples.pentax_note([(0x7777, ("short", [5]))])
    result = read_maker_note(tiff(exif_samples, make="PENTAX", maker_note=note))
    assert tags_of(result) == {"Tag 0x7777": "5"}
    assert 0x7777 not in PENTAX_TAGS


def test_unknown_maker_with_ifd(exif_samples):
    note = exif_samples.samsung_note([(0x0010, "hello")])  # ヘッダーのない IFD
    result = read_maker_note(tiff(exif_samples, make="SomePhone", maker_note=note))
    assert result.format == "不明な形式"
    assert tags_of(result) == {"Tag 0x0010": "hello"}


@pytest.mark.parametrize(
    ("make", "note", "name"),
    [
        ("Google", b"HDRP\x02" + bytes(40), "Google HDR+"),
        ("Xiaomi", b"\xff" * 50, "不明な形式"),
        ("PENTAX", b"PENTAX \0II" + b"\xff" * 30, "Pentax"),  # 壊れた IFD
    ],
)
def test_undecodable(exif_samples, make, note, name):
    result = read_maker_note(tiff(exif_samples, make=make, maker_note=note))
    assert result.format == name
    assert not result.is_decoded()
    assert result.size == len(note)


def test_value_offsets_outside_are_skipped(exif_samples):
    # 値の位置がデータの外を指す項目は読み飛ばし、ほかの項目は読む
    note = bytearray(exif_samples.pentax_note([(0x0229, "1234567"), (0x0014, ("short", [100]))]))
    # 1 つ目の項目（0x0014、値は 4 バイト以下）はそのまま、2 つ目（0x0229）の位置を壊す
    entry = 10 + 2 + 12  # ヘッダー 10 + 項目数 2 + 1 つ目の項目 12
    note[entry + 8 : entry + 12] = (0xFFFFFF).to_bytes(4, "little")
    result = read_maker_note(tiff(exif_samples, make="PENTAX", maker_note=bytes(note)))
    assert tags_of(result) == {"ISO": "100"}


def test_format_value():
    assert format_value(2, b"abc\0\0") == "abc"
    assert format_value(7, b"0230") == "0230"
    assert format_value(7, b"\x00\x01\xff") == "00 01 ff"
    assert format_value(3, (300).to_bytes(2, "little")) == "300"
    assert format_value(3, (300).to_bytes(2, "big"), ">") == "300"
    assert format_value(5, (1).to_bytes(4, "little") + (125).to_bytes(4, "little")) == "1/125"
    assert format_value(9, (-5).to_bytes(4, "little", signed=True)) == "-5"
    many = b"".join(i.to_bytes(2, "little") for i in range(MAX_VALUES_SHOWN + 4))
    text = format_value(3, many)
    assert text.startswith("[0, 1, 2") and text.endswith(f"（全 {MAX_VALUES_SHOWN + 4} 個）")


def test_core_makernote_does_not_import_qt():
    code = (
        "import sys, image_editor.core.makernote, image_editor.core.exif_info; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
