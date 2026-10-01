"""テスト用に EXIF（TIFF の形）を組み立てる。MakerNote の形式を試すのに使う。

値の型: str は ASCII、bytes は UNDEFINED、("short", [...])・("long", [...])・
("rational", [(分子, 分母), ...]) は数、Pointer はほかの場所を指す値。
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

ASCII, SHORT, LONG, RATIONAL, UNDEFINED = 2, 3, 4, 5, 7
EXIF_IFD_AT = 1000
GPS_IFD_AT = 2000
MAKERNOTE_AT = 3000


@dataclass(frozen=True)
class Pointer:
    """値をほかの場所（offset）に置いた項目（MakerNote 用）。"""

    type: int
    count: int
    offset: int


Entry = tuple[int, Any]  # (タグ番号, 値)


def _encode(value: Any, order: str) -> tuple[int, int, bytes]:
    if isinstance(value, str):
        raw = value.encode() + b"\0"
        return ASCII, len(raw), raw
    if isinstance(value, bytes):
        return UNDEFINED, len(value), value
    kind, numbers = value
    if kind == "short":
        return SHORT, len(numbers), struct.pack(f"{order}{len(numbers)}H", *numbers)
    if kind == "long":
        return LONG, len(numbers), struct.pack(f"{order}{len(numbers)}I", *numbers)
    if kind == "rational":
        flat = [n for pair in numbers for n in pair]
        return RATIONAL, len(numbers), struct.pack(f"{order}{len(flat)}I", *flat)
    raise ValueError(kind)


def write_ifd(entries: Sequence[Entry], start: int, order: str = "<") -> bytes:
    """位置の基準から start の場所に置く IFD を作る（4 バイトを超える値は IFD のすぐ後ろ）。"""
    entries = sorted(entries, key=lambda e: e[0])
    data_at = start + 2 + 12 * len(entries) + 4
    head = struct.pack(order + "H", len(entries))
    data = b""
    for tag, value in entries:
        if isinstance(value, Pointer):
            field = struct.pack(order + "I", value.offset)
            head += struct.pack(order + "HHI", tag, value.type, value.count) + field
            continue
        type_, count, raw = _encode(value, order)
        if len(raw) <= 4:
            field = raw.ljust(4, b"\0")
        else:
            field = struct.pack(order + "I", data_at + len(data))
            data += raw + (b"\0" if len(raw) % 2 else b"")
        head += struct.pack(order + "HHI", tag, type_, count) + field
    return head + struct.pack(order + "I", 0) + data


def build_exif(
    make: str = "TestMaker",
    model: str = "TestModel",
    exif: Sequence[Entry] = (),
    gps: Sequence[Entry] | None = None,
    maker_note: bytes | Callable[[int], bytes] | None = None,
    order: str = "<",
    prefix: bool = True,
) -> bytes:
    """EXIF を組み立てる。maker_note に関数を渡すと、置く位置（TIFF の先頭から）を渡して呼ぶ。

    prefix が True なら先頭に "Exif\\0\\0" を付ける（JPEG の APP1 と同じ形）。
    """
    mark = b"II" if order == "<" else b"MM"
    ifd0: list[Entry] = [(0x010F, make), (0x0110, model), (0x8769, ("long", [EXIF_IFD_AT]))]
    if gps is not None:
        ifd0.append((0x8825, ("long", [GPS_IFD_AT])))
    exif_entries = list(exif)
    note = b""
    if maker_note is not None:
        note = maker_note(MAKERNOTE_AT) if callable(maker_note) else maker_note
        exif_entries.append((0x927C, Pointer(UNDEFINED, len(note), MAKERNOTE_AT)))
    data = bytearray(MAKERNOTE_AT + len(note))
    data[:8] = mark + struct.pack(order + "HI", 42, 8)
    parts = [
        (8, write_ifd(ifd0, 8, order)),
        (EXIF_IFD_AT, write_ifd(exif_entries, EXIF_IFD_AT, order)),
    ]
    if gps is not None:
        parts.append((GPS_IFD_AT, write_ifd(gps, GPS_IFD_AT, order)))
    for at, part in parts:
        data[at : at + len(part)] = part
    data[MAKERNOTE_AT:] = note
    return (b"Exif\0\0" if prefix else b"") + bytes(data)


# --- MakerNote の形式ごとの組み立て ---------------------------------------------------


def pentax_note(entries: Sequence[Entry], order: str = "<") -> bytes:
    """ "PENTAX \\0" 形式（位置は MakerNote の先頭が基準）。"""
    mark = b"II" if order == "<" else b"MM"
    return b"PENTAX \0" + mark + write_ifd(entries, 10, order)


def aoc_note(entries: Sequence[Entry], order: str = ">") -> bytes:
    """ "AOC\\0" 形式（古いペンタックス。位置は MakerNote の先頭が基準）。"""
    mark = b"II" if order == "<" else b"MM"
    return b"AOC\0" + mark + write_ifd(entries, 6, order)


def ricoh_pentax_note(entries: Sequence[Entry], order: str = "<") -> bytes:
    """ "RICOH\\0II" 形式（GR III など。ペンタックスと同じタグ）。"""
    mark = b"II" if order == "<" else b"MM"
    return b"RICOH\0" + mark + write_ifd(entries, 8, order)


def ricoh_note(entries: Sequence[Entry], order: str = ">") -> Callable[[int], bytes]:
    """ "Ricoh" で始まる古い形式（位置は TIFF の先頭が基準）。"""
    return lambda at: b"Ricoh\0\0\0" + write_ifd(entries, at + 8, order)


def samsung_note(entries: Sequence[Entry], order: str = "<") -> Callable[[int], bytes]:
    """Samsung Type2 形式（ヘッダーなし、位置は TIFF の先頭が基準）。"""
    return lambda at: write_ifd(entries, at, order)


def canon_note(entries: Sequence[Entry], order: str = "<") -> Callable[[int], bytes]:
    """Canon 形式（ヘッダーなし、位置は TIFF の先頭が基準）。exifread が読む。"""
    return lambda at: write_ifd(entries, at, order)


def apple_note(entries: Sequence[Entry]) -> bytes:
    """Apple (iPhone) 形式（"Apple iOS\\0" + 版 + "MM"、位置は MakerNote の先頭が基準）。"""
    return b"Apple iOS\0\0\x01MM" + write_ifd(entries, 14, ">")
