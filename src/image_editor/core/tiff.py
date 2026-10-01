"""EXIF の TIFF ブロック（IFD の並び）の読み書き。

EXIF は TIFF と同じ形で、IFD（タグ番号・型・個数・値の並び）がいくつかつながっている。
値は 4 バイト以下なら IFD の中に、それより大きければ「TIFF の先頭からの位置」で別の場所に
書く。MakerNote（メーカー独自の情報）の中にも、この位置で値を指すものがあるので、
保存するときは MakerNote を元と同じ位置に置き直す（ExifBlock.to_bytes）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

EXIF_HEADER = b"Exif\0\0"
# IFD として正しそうか確かめるときの、1 つの IFD の項目数の上限
MAX_IFD_ENTRIES = 1000

TAG_ORIENTATION = 0x0112
TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825
TAG_INTEROP_IFD = 0xA005
TAG_MAKERNOTE = 0x927C
TAG_PIXEL_X = 0xA002  # Exif IFD の画像の幅
TAG_PIXEL_Y = 0xA003  # Exif IFD の画像の高さ
# 画像データなどの位置を指すタグ。保存する画像のデータとは合わないので書き写さない
_LOCATION_TAGS = frozenset({0x0111, 0x0117, 0x0144, 0x0145, 0x014A, 0x0201, 0x0202})

SHORT, LONG, UNDEFINED = 3, 4, 7
# TIFF の型ごとの 1 個の大きさ（バイト）
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}


@dataclass(frozen=True)
class IfdEntry:
    """IFD の 1 項目。raw は値そのもの（4 バイト以下）か、値の位置（4 バイト）。"""

    tag: int
    type: int
    count: int
    raw: bytes


@dataclass(frozen=True)
class Value:
    """書き出す値（data はその EXIF のバイト順で並べたもの）。"""

    type: int
    count: int
    data: bytes


def order_of(mark: bytes) -> str | None:
    """バイト順の目印 (II / MM) を struct の書式に。目印でなければ None。"""
    return {b"II": "<", b"MM": ">"}.get(mark)


def tiff_block(raw_exif: bytes | None) -> bytes | None:
    """EXIF のバイト列から、TIFF の部分（"II*\\0" / "MM\\0*" から）を返す。

    先頭の "Exif\\0\\0" は取り除く。TIFF の形でなければ None。
    """
    if not raw_exif:
        return None
    data = raw_exif[len(EXIF_HEADER) :] if raw_exif.startswith(EXIF_HEADER) else raw_exif
    if data[:4] in (b"II*\0", b"MM\0*"):
        return data
    return None


def read_ifd(data: bytes, offset: int, order: str) -> list[IfdEntry] | None:
    """offset の IFD の項目を返す。IFD として正しくなさそうなら None。"""
    if offset < 0 or offset + 2 > len(data):
        return None
    count = struct.unpack(order + "H", data[offset : offset + 2])[0]
    end = offset + 2 + 12 * count
    if not 0 < count <= MAX_IFD_ENTRIES or end > len(data):
        return None
    entries = []
    for i in range(count):
        start = offset + 2 + 12 * i
        tag, type_, value_count = struct.unpack(order + "HHI", data[start : start + 8])
        if type_ not in TYPE_SIZES:
            if i == 0:
                return None  # 最初の項目から型が変なら IFD ではない
            continue
        entries.append(IfdEntry(tag, type_, value_count, data[start + 8 : start + 12]))
    return entries or None


def value_bytes(data: bytes, entry: IfdEntry, order: str, base: int = 0) -> bytes | None:
    """項目の値のバイト列を返す。値の位置がデータの外なら None。"""
    size = TYPE_SIZES[entry.type] * entry.count
    if size <= 4:
        return entry.raw[:size]
    position = base + struct.unpack(order + "I", entry.raw)[0]
    if position < 0 or position + size > len(data):
        return None
    return data[position : position + size]


def pointer(entry: IfdEntry, order: str) -> int:
    """ほかの IFD・MakerNote などの位置を指す項目の値を返す。"""
    return int(struct.unpack(order + "I", entry.raw)[0])


@dataclass
class ExifBlock:
    """EXIF の IFD0・Exif・GPS・互換性の IFD の値と、MakerNote（元の位置ごと）を持つ。

    サムネイル (IFD1) は編集前の画像なので持たない。ほかの IFD を指す項目は、書き出すときに
    作り直す。
    """

    order: str
    ifd0: dict[int, Value] = field(default_factory=dict)
    exif: dict[int, Value] = field(default_factory=dict)
    gps: dict[int, Value] | None = None
    interop: dict[int, Value] | None = None
    maker_note: tuple[int, bytes] | None = None  # (元の位置, 中身)

    @classmethod
    def parse(cls, raw_exif: bytes) -> ExifBlock:
        """EXIF のバイト列（"Exif\\0\\0" 付きでもよい）を読む。読めなければ ValueError。"""
        data = tiff_block(raw_exif)
        if data is None:
            raise ValueError("EXIF の形ではありません")
        order = order_of(data[:2])
        if order is None:
            raise ValueError("バイト順の目印がありません")
        ifd0 = read_ifd(data, struct.unpack(order + "I", data[4:8])[0], order)
        if ifd0 is None:
            raise ValueError("IFD0 を読めません")
        block = cls(order)
        block.ifd0 = _values(data, ifd0, order)
        found = {entry.tag: entry for entry in ifd0}
        if TAG_EXIF_IFD in found:
            exif = read_ifd(data, pointer(found[TAG_EXIF_IFD], order), order) or []
            block.exif = _values(data, exif, order)
            inner = {entry.tag: entry for entry in exif}
            note = inner.get(TAG_MAKERNOTE)
            if note is not None and note.count > 4:
                at = pointer(note, order)
                if at >= 8 and at + note.count <= len(data):
                    block.maker_note = (at, data[at : at + note.count])
            if TAG_INTEROP_IFD in inner:
                interop = read_ifd(data, pointer(inner[TAG_INTEROP_IFD], order), order)
                block.interop = _values(data, interop, order) if interop else None
        if TAG_GPS_IFD in found:
            gps = read_ifd(data, pointer(found[TAG_GPS_IFD], order), order)
            block.gps = _values(data, gps, order) if gps else None
        return block

    def set_short(self, ifd: dict[int, Value], tag: int, value: int) -> None:
        """SHORT の値を 1 つ設定する。"""
        ifd[tag] = Value(SHORT, 1, struct.pack(self.order + "H", value))

    def set_long(self, ifd: dict[int, Value], tag: int, value: int) -> None:
        """LONG の値を 1 つ設定する。"""
        ifd[tag] = Value(LONG, 1, struct.pack(self.order + "I", value))

    def to_bytes(self, keep_maker_note: bool = True) -> bytes:
        """ "Exif\\0\\0" 付きの EXIF のバイト列にする。

        MakerNote は元と同じ位置に置き（中の値の位置がずれないように）、ほかの IFD は
        その後ろに並べる。keep_maker_note が False なら MakerNote を書かない。
        """
        order = self.order
        maker_note = self.maker_note if keep_maker_note else None
        start = 8
        if maker_note is not None:
            at, note = maker_note
            start = _even(at + len(note))

        # 先に IFD の位置を決め（ほかの IFD を指す項目は 4 バイトなので大きさは変わらない）、
        # それから指す位置を入れて書く
        layout: list[tuple[str, dict[int, Value]]] = []
        ifd0 = dict(self.ifd0)
        exif = dict(self.exif)
        placeholder = Value(LONG, 1, bytes(4))
        if exif or maker_note is not None:
            ifd0[TAG_EXIF_IFD] = placeholder
        if self.gps:
            ifd0[TAG_GPS_IFD] = placeholder
        if self.interop:
            exif[TAG_INTEROP_IFD] = placeholder
        if maker_note is not None:
            exif[TAG_MAKERNOTE] = placeholder
        layout.append(("ifd0", ifd0))
        if TAG_EXIF_IFD in ifd0:
            layout.append(("exif", exif))
        if self.interop:
            layout.append(("interop", dict(self.interop)))
        if self.gps:
            layout.append(("gps", dict(self.gps)))
        positions: dict[str, int] = {}
        position = start
        for name, values in layout:
            positions[name] = position
            position = _even(position + _ifd_size(values))

        def at(name: str) -> Value:
            return Value(LONG, 1, struct.pack(order + "I", positions[name]))

        if TAG_EXIF_IFD in ifd0:
            ifd0[TAG_EXIF_IFD] = at("exif")
        if TAG_GPS_IFD in ifd0:
            ifd0[TAG_GPS_IFD] = at("gps")
        if TAG_INTEROP_IFD in exif:
            exif[TAG_INTEROP_IFD] = at("interop")
        if maker_note is not None:
            note_at, note = maker_note
            exif[TAG_MAKERNOTE] = Value(UNDEFINED, len(note), struct.pack(order + "I", note_at))
        updated = {"ifd0": ifd0, "exif": exif}

        out = bytearray(position)
        out[:8] = (b"II" if order == "<" else b"MM") + struct.pack(order + "HI", 42, start)
        if maker_note is not None:
            note_at, note = maker_note
            out[note_at : note_at + len(note)] = note
        for name, values in layout:
            written = _write_ifd(updated.get(name, values), positions[name], order)
            out[positions[name] : positions[name] + len(written)] = written
        return EXIF_HEADER + bytes(out)


def _values(data: bytes, entries: list[IfdEntry], order: str) -> dict[int, Value]:
    """IFD の項目を、書き出せる値にする（ほかの IFD・画像データの位置を指す項目は除く）。"""
    values: dict[int, Value] = {}
    skipped = {TAG_EXIF_IFD, TAG_GPS_IFD, TAG_INTEROP_IFD, TAG_MAKERNOTE} | _LOCATION_TAGS
    for entry in entries:
        if entry.tag in skipped:
            continue
        value = value_bytes(data, entry, order)
        if value is not None:
            values[entry.tag] = Value(entry.type, entry.count, value)
    return values


def _ifd_size(values: dict[int, Value]) -> int:
    data = sum(_even(len(v.data)) for v in values.values() if len(v.data) > 4)
    return 2 + 12 * len(values) + 4 + data


def _write_ifd(values: dict[int, Value], position: int, order: str) -> bytes:
    """position に置く IFD を作る（4 バイトを超える値は IFD のすぐ後ろに並べる）。"""
    data_at = position + 2 + 12 * len(values) + 4
    head = struct.pack(order + "H", len(values))
    data = b""
    for tag in sorted(values):  # TIFF ではタグ番号の小さい順に並べる
        value = values[tag]
        if len(value.data) <= 4:
            field_bytes = value.data.ljust(4, b"\0")
        else:
            field_bytes = struct.pack(order + "I", data_at + len(data))
            data += value.data.ljust(_even(len(value.data)), b"\0")
        head += struct.pack(order + "HHI", tag, value.type, value.count) + field_bytes
    return head + struct.pack(order + "I", 0) + data


def _even(value: int) -> int:
    """偶数にそろえる（TIFF の値の位置は偶数にする決まり）。"""
    return value + (value % 2)
