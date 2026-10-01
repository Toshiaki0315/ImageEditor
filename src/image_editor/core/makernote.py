"""exifread が読めない MakerNote（ペンタックス・リコー・Samsung など）を読む。

MakerNote は EXIF の中にメーカーが独自の形式で書く情報。多くは TIFF と同じ IFD
（タグ番号・型・個数・値の並び）で書かれているが、先頭の目印（ヘッダー）、バイト順、
値の位置の基準（MakerNote の先頭か、TIFF の先頭か）がメーカー・機種ごとに違う。
タグ番号と名前は ExifTool のタグ一覧に合わせ、名前の分からないタグは番号で表す。
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass

# 値の表示で並べる数の上限（それより多ければ省略する）
MAX_VALUES_SHOWN = 16
# IFD として正しそうか確かめるときの、1 つの IFD の項目数の上限
MAX_IFD_ENTRIES = 1000

_TAG_EXIF_IFD = 0x8769
_TAG_MAKERNOTE = 0x927C
_TAG_MAKE = 0x010F

# TIFF の型ごとの 1 個の大きさ（バイト）
_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
_TYPE_FORMATS = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 13: "I"}


@dataclass(frozen=True)
class MakerNoteTag:
    """MakerNote の 1 項目。名前が分からなければ name は "Tag 0x0012" のような番号。"""

    name: str
    value: str


@dataclass(frozen=True)
class MakerNoteResult:
    """MakerNote を読んだ結果。

    format は形式の名前（"Pentax" など）。読めなかったときは tags が空で、
    size（バイト数）だけを持つ。
    """

    format: str
    tags: tuple[MakerNoteTag, ...]
    size: int

    def is_decoded(self) -> bool:
        """項目を読めたか。"""
        return bool(self.tags)


def read_maker_note(tiff: bytes) -> MakerNoteResult | None:
    """EXIF の TIFF ブロック（"II*\\0" / "MM\\0*" で始まる）から MakerNote を探して読む。

    MakerNote がなければ None。形式が分からない・壊れている MakerNote は、項目なしで返す。
    """
    try:
        reader = _TiffReader(tiff)
        location = reader.maker_note()
        if location is None:
            return None
        offset, size = location
        make = reader.make()
        note = tiff[offset : offset + size]
        return _decode(reader, note, offset, make)
    except (ValueError, struct.error):
        return None


# --- 形式ごとの読み方 ---------------------------------------------------------------


def _decode(reader: _TiffReader, note: bytes, offset: int, make: str) -> MakerNoteResult:
    size = len(note)
    upper_make = make.upper()
    if note.startswith(b"HDRP"):
        return MakerNoteResult("Google HDR+", (), size)
    candidates: list[tuple[str, int, list[str], list[int], dict[int, str]]] = []
    tiff_order = reader.order
    if note.startswith(b"PENTAX \0"):
        order = _order_of(note[8:10]) or tiff_order
        candidates.append(("Pentax", 10, [order], [offset], PENTAX_TAGS))
    elif note.startswith(b"AOC\0"):
        orders = _orders(_order_of(note[4:6]) or tiff_order)
        candidates.append(("Pentax", 6, orders, [offset, 0], PENTAX_TAGS))
    elif note.startswith(b"S1\0\0\0\0\0\0\x0c\0\0\0"):
        candidates.append(("Pentax", 12, _orders(tiff_order), [offset], PENTAX_TAGS))
    elif note.startswith((b"RICOH\0II", b"RICOH\0MM")):
        order = _order_of(note[6:8]) or tiff_order
        candidates.append(("Ricoh（Pentax 形式）", 8, [order], [offset], PENTAX_TAGS))
    elif upper_make.startswith(("RICOH", "PENTAX RICOH")):
        header = note[:8]
        if _is_tiff_header_at_8(header):
            # WG-M1 などの、TIFF と同じヘッダーの形式（位置は MakerNote の先頭が基準）
            order = _order_of(header[:2]) or tiff_order
            candidates.append(("Ricoh", 8, [order], [offset], RICOH_TAGS))
        else:
            candidates.append(("Ricoh", 8, _orders(tiff_order), [0, offset], RICOH_TAGS))
    elif upper_make.startswith("SAMSUNG"):
        candidates.append(("Samsung", 0, _orders(tiff_order), [0, offset], SAMSUNG_TAGS))
    elif upper_make.startswith(("PENTAX", "ASAHI")):
        candidates.append(("Pentax", 0, _orders(tiff_order), [0, offset], PENTAX_TAGS))
    # どれにも当てはまらなければ、ヘッダーのない IFD として読めるか試す
    candidates.append(("不明な形式", 0, _orders(tiff_order), [0, offset], {}))

    for name, start, orders, bases, table in candidates:
        tags = _read_best(reader.data, offset + start, orders, bases, table)
        if tags:
            return MakerNoteResult(name, tags, size)
    # 形式は分かったが読めなかった（壊れている・知らない版）ときも、形式の名前は出す
    return MakerNoteResult(candidates[0][0], (), size)


def _read_best(
    data: bytes,
    ifd_offset: int,
    orders: Iterable[str],
    bases: Iterable[int],
    table: dict[int, str],
) -> tuple[MakerNoteTag, ...]:
    """バイト順と位置の基準の組み合わせを試し、値の位置がいちばん多く収まる読み方で返す。"""
    best: tuple[int, tuple[MakerNoteTag, ...]] = (0, ())
    for order in orders:
        entries = _read_ifd(data, ifd_offset, order)
        if not entries:
            continue
        for base in bases:
            tags, valid = _decode_entries(data, entries, order, base, table)
            if valid > best[0]:
                best = (valid, tags)
    return best[1]


# --- TIFF の読み取り ----------------------------------------------------------------


@dataclass(frozen=True)
class _Entry:
    tag: int
    type: int
    count: int
    raw: bytes  # 値そのもの（4 バイト以下）か、値の位置（4 バイト）


class _TiffReader:
    """EXIF の TIFF ブロックから、MakerNote の位置とメーカー名を探す。"""

    def __init__(self, data: bytes) -> None:
        order = _order_of(data[:2])
        if order is None or struct.unpack(order + "H", data[2:4])[0] != 42:
            raise ValueError("TIFF のヘッダーではありません")
        self.data = data
        self.order = order
        self.ifd0 = struct.unpack(order + "I", data[4:8])[0]

    def _find(self, ifd_offset: int, tag: int) -> _Entry | None:
        for entry in _read_ifd(self.data, ifd_offset, self.order) or ():
            if entry.tag == tag:
                return entry
        return None

    def make(self) -> str:
        entry = self._find(self.ifd0, _TAG_MAKE)
        if entry is None or entry.type != 2:
            return ""
        value = _value_bytes(self.data, entry, self.order, 0)
        return "" if value is None else _ascii(value)

    def maker_note(self) -> tuple[int, int] | None:
        """MakerNote の位置と大きさ（TIFF の先頭から）を返す。なければ None。"""
        exif = self._find(self.ifd0, _TAG_EXIF_IFD)
        if exif is None:
            return None
        exif_offset = struct.unpack(self.order + "I", exif.raw[:4])[0]
        note = self._find(exif_offset, _TAG_MAKERNOTE)
        if note is None or note.count <= 4:
            return None
        offset = struct.unpack(self.order + "I", note.raw[:4])[0]
        if offset + note.count > len(self.data):
            return None
        return offset, note.count


def _read_ifd(data: bytes, offset: int, order: str) -> list[_Entry] | None:
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
        if type_ not in _TYPE_SIZES:
            if i == 0:
                return None  # 最初の項目から型が変なら IFD ではない
            continue
        entries.append(_Entry(tag, type_, value_count, data[start + 8 : start + 12]))
    return entries or None


def _value_bytes(data: bytes, entry: _Entry, order: str, base: int) -> bytes | None:
    """項目の値のバイト列を返す。値の位置がデータの外なら None。"""
    size = _TYPE_SIZES[entry.type] * entry.count
    if size <= 4:
        return entry.raw[:size]
    position = base + struct.unpack(order + "I", entry.raw)[0]
    if position < 0 or position + size > len(data):
        return None
    return data[position : position + size]


def _decode_entries(
    data: bytes, entries: list[_Entry], order: str, base: int, table: dict[int, str]
) -> tuple[tuple[MakerNoteTag, ...], int]:
    """項目を名前と値の文字列にする。値の位置がデータの中に収まった数も返す。"""
    tags = []
    valid = 0
    for entry in entries:
        value = _value_bytes(data, entry, order, base)
        if value is None:
            continue
        valid += 1
        name = table.get(entry.tag, f"Tag 0x{entry.tag:04x}")
        tags.append(MakerNoteTag(name, format_value(entry.type, value, order)))
    return tuple(tags), valid


# --- 値の表示 ---------------------------------------------------------------------


def format_value(type_: int, value: bytes, order: str = "<") -> str:
    """TIFF の型と値のバイト列を、表示用の文字列にする。"""
    if type_ == 2:
        return _ascii(value)
    if type_ in (1, 7):
        text = value.rstrip(b"\0")
        if text and len(text) <= 256 and all(32 <= b < 127 for b in text):
            return text.decode("ascii")
        if type_ == 7:
            return _hex(value)
    if type_ in (5, 10):
        code = order + ("II" if type_ == 5 else "ii")
        pairs = [struct.unpack(code, value[i : i + 8]) for i in range(0, len(value), 8)]
        return _join([f"{n}/{d}" for n, d in pairs])
    code = _TYPE_FORMATS[type_]
    size = _TYPE_SIZES[type_]
    count = len(value) // size
    numbers = struct.unpack(f"{order}{count}{code}", value[: count * size])
    texts = [f"{n:g}" if isinstance(n, float) else str(n) for n in numbers]
    return _join(texts)


def _join(texts: list[str]) -> str:
    if len(texts) == 1:
        return texts[0]
    shown = ", ".join(texts[:MAX_VALUES_SHOWN])
    if len(texts) > MAX_VALUES_SHOWN:
        return f"[{shown}, …]（全 {len(texts)} 個）"
    return f"[{shown}]"


def _hex(value: bytes) -> str:
    shown = " ".join(f"{b:02x}" for b in value[:MAX_VALUES_SHOWN])
    if len(value) > MAX_VALUES_SHOWN:
        return f"{shown} …（{len(value)} バイト）"
    return shown


def _ascii(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()


def _order_of(mark: bytes) -> str | None:
    """バイト順の目印 (II / MM) を struct の書式に。目印でなければ None。"""
    return {b"II": "<", b"MM": ">"}.get(mark)


def _orders(first: str) -> list[str]:
    return [first, ">" if first == "<" else "<"]


def _is_tiff_header_at_8(header: bytes) -> bool:
    return header in (b"MM\0\x2a\0\0\0\x08", b"II\x2a\0\x08\0\0\0")


# --- タグの名前（ExifTool のタグ一覧に合わせる） ---------------------------------------

PENTAX_TAGS: dict[int, str] = {
    0x0000: "PentaxVersion",
    0x0001: "PentaxModelType",
    0x0002: "PreviewImageSize",
    0x0003: "PreviewImageLength",
    0x0004: "PreviewImageStart",
    0x0005: "PentaxModelID",
    0x0006: "Date",
    0x0007: "Time",
    0x0008: "Quality",
    0x0009: "PentaxImageSize",
    0x000B: "PictureMode",
    0x000C: "FlashMode",
    0x000D: "FocusMode",
    0x000E: "AFPointSelected",
    0x000F: "AFPointsInFocus",
    0x0010: "FocusPosition",
    0x0012: "ExposureTime",
    0x0013: "FNumber",
    0x0014: "ISO",
    0x0015: "LightReading",
    0x0016: "ExposureCompensation",
    0x0017: "MeteringMode",
    0x0018: "AutoBracketing",
    0x0019: "WhiteBalance",
    0x001A: "WhiteBalanceMode",
    0x001B: "BlueBalance",
    0x001C: "RedBalance",
    0x001D: "FocalLength",
    0x001E: "DigitalZoom",
    0x001F: "Saturation",
    0x0020: "Contrast",
    0x0021: "Sharpness",
    0x0022: "WorldTimeLocation",
    0x0023: "HometownCity",
    0x0024: "DestinationCity",
    0x0025: "HometownDST",
    0x0026: "DestinationDST",
    0x0027: "DSPFirmwareVersion",
    0x0028: "CPUFirmwareVersion",
    0x0029: "FrameNumber",
    0x002D: "EffectiveLV",
    0x0032: "ImageEditing",
    0x0033: "PictureMode",
    0x0034: "DriveMode",
    0x0035: "SensorSize",
    0x0037: "ColorSpace",
    0x0038: "ImageAreaOffset",
    0x0039: "RawImageSize",
    0x003C: "AFPointsInFocus",
    0x003D: "DataScaling",
    0x003E: "PreviewImageBorders",
    0x003F: "LensRec",
    0x0040: "SensitivityAdjust",
    0x0041: "ImageEditCount",
    0x0047: "CameraTemperature",
    0x0048: "AELock",
    0x0049: "NoiseReduction",
    0x004D: "FlashExposureComp",
    0x004F: "ImageTone",
    0x0050: "ColorTemperature",
    0x0053: "ColorTempDaylight",
    0x0054: "ColorTempShade",
    0x0055: "ColorTempCloudy",
    0x0056: "ColorTempTungsten",
    0x0057: "ColorTempFluorescentD",
    0x0058: "ColorTempFluorescentN",
    0x0059: "ColorTempFluorescentW",
    0x005A: "ColorTempFlash",
    0x005C: "ShakeReductionInfo",
    0x005D: "ShutterCount",
    0x0060: "FaceInfo",
    0x0062: "RawDevelopmentProcess",
    0x0067: "Hue",
    0x0068: "AWBInfo",
    0x0069: "DynamicRangeExpansion",
    0x006B: "TimeInfo",
    0x006C: "HighLowKeyAdj",
    0x006D: "ContrastHighlight",
    0x006E: "ContrastShadow",
    0x006F: "ContrastHighlightShadowAdj",
    0x0070: "FineSharpness",
    0x0071: "HighISONoiseReduction",
    0x0072: "AFAdjustment",
    0x0073: "MonochromeFilterEffect",
    0x0074: "MonochromeToning",
    0x0076: "FaceDetect",
    0x0077: "FaceDetectFrameSize",
    0x0079: "ShadowCorrection",
    0x007A: "ISOAutoMinSpeed",
    0x007B: "CrossProcess",
    0x007D: "LensCorr",
    0x007E: "WhiteLevel",
    0x007F: "BleachBypassToning",
    0x0080: "AspectRatio",
    0x0082: "BlurControl",
    0x0085: "HDR",
    0x0087: "ShutterType",
    0x0088: "NeutralDensityFilter",
    0x008B: "ISO",
    0x0092: "IntervalShooting",
    0x0095: "SkinToneCorrection",
    0x0096: "ClarityControl",
    0x009E: "HDF",
    0x0200: "BlackPoint",
    0x0201: "WhitePoint",
    0x0203: "ColorMatrixA",
    0x0204: "ColorMatrixB",
    0x0205: "CameraSettings",
    0x0206: "AEInfo",
    0x0207: "LensInfo",
    0x0208: "FlashInfo",
    0x0209: "AEMeteringSegments",
    0x020A: "FlashMeteringSegments",
    0x020B: "SlaveFlashMeteringSegments",
    0x020D: "WB_RGGBLevelsDaylight",
    0x020E: "WB_RGGBLevelsShade",
    0x020F: "WB_RGGBLevelsCloudy",
    0x0210: "WB_RGGBLevelsTungsten",
    0x0211: "WB_RGGBLevelsFluorescentD",
    0x0212: "WB_RGGBLevelsFluorescentN",
    0x0213: "WB_RGGBLevelsFluorescentW",
    0x0214: "WB_RGGBLevelsFlash",
    0x0215: "CameraInfo",
    0x0216: "BatteryInfo",
    0x021C: "ColorMatrixA2",
    0x021D: "ColorMatrixB2",
    0x021F: "AFInfo",
    0x0221: "KelvinWB",
    0x0222: "ColorInfo",
    0x0224: "EVStepInfo",
    0x0226: "ShotInfo",
    0x0227: "FacePos",
    0x0228: "FaceSize",
    0x0229: "SerialNumber",
    0x022A: "FilterInfo",
    0x022B: "LevelInfoK3III",
    0x022D: "WBLevels",
    0x022E: "Artist",
    0x022F: "Copyright",
    0x0230: "FirmwareVersion",
    0x0231: "ContrastDetectAFArea",
    0x0235: "CrossProcessParams",
    0x0238: "CAFPointInfo",
    0x0239: "LensInfoQ",
    0x023F: "Model",
    0x0243: "PixelShiftInfo",
    0x0245: "AFPointInfo",
    0x03FE: "DataDump",
    0x03FF: "TempInfo",
    0x0402: "ToneCurve",
    0x0403: "ToneCurves",
    0x040B: "FaceInfoK3III",
    0x040C: "AFInfoK3III",
    0x0E00: "PrintIM",
}

RICOH_TAGS: dict[int, str] = {
    0x0001: "MakerNoteType",
    0x0002: "FirmwareVersion",
    0x0005: "SerialNumber",
    0x0E00: "PrintIM",
    0x1000: "RecordingFormat",
    0x1001: "ImageInfo",
    0x1002: "DriveMode",
    0x1003: "Sharpness",
    0x1004: "WhiteBalanceFineTune",
    0x1006: "FocusMode",
    0x1007: "AutoBracketing",
    0x1009: "MacroMode",
    0x100A: "FlashMode",
    0x100B: "FlashExposureComp",
    0x100C: "ManualFlashOutput",
    0x100D: "FullPressSnap",
    0x100E: "DynamicRangeExpansion",
    0x100F: "NoiseReduction",
    0x1010: "ImageEffects",
    0x1011: "Vignetting",
    0x1012: "Contrast",
    0x1013: "Saturation",
    0x1014: "Sharpness",
    0x1015: "ToningEffect",
    0x1016: "HueAdjust",
    0x1017: "WideAdapter",
    0x1018: "CropMode",
    0x1019: "NDFilter",
    0x101A: "WBBracketShotNumber",
    0x1200: "AFStatus",
    0x1201: "AFAreaXPosition1",
    0x1202: "AFAreaYPosition1",
    0x1203: "AFAreaXPosition",
    0x1204: "AFAreaYPosition",
    0x1205: "AFAreaMode",
    0x1307: "ColorTempKelvin",
    0x1308: "ColorTemperature",
    0x1500: "FocalLength",
    0x1601: "SensorWidth",
    0x1602: "SensorHeight",
    0x1603: "CroppedImageWidth",
    0x1604: "CroppedImageHeight",
    0x2001: "RicohSubdir",
    0x4001: "ThetaSubdir",
}

SAMSUNG_TAGS: dict[int, str] = {
    0x0001: "MakerNoteVersion",
    0x0002: "DeviceType",
    0x0003: "SamsungModelID",
    0x0011: "OrientationInfo",
    0x0020: "SmartAlbumColor",
    0x0021: "PictureWizard",
    0x0030: "LocalLocationName",
    0x0031: "LocationName",
    0x0035: "PreviewIFD",
    0x0040: "RawDataByteOrder",
    0x0041: "WhiteBalanceSetup",
    0x0043: "CameraTemperature",
    0x0050: "RawDataCFAPattern",
    0x0100: "FaceDetect",
    0x0120: "FaceRecognition",
    0x0123: "FaceName",
    0xA001: "FirmwareName",
    0xA002: "SerialNumber",
    0xA003: "LensType",
    0xA004: "LensFirmware",
    0xA005: "InternalLensSerialNumber",
    0xA010: "SensorAreas",
    0xA011: "ColorSpace",
    0xA012: "SmartRange",
    0xA013: "ExposureCompensation",
    0xA014: "ISO",
    0xA018: "ExposureTime",
    0xA019: "FNumber",
    0xA01A: "FocalLengthIn35mmFormat",
    0xA020: "EncryptionKey",
    0xA021: "WB_RGGBLevelsUncorrected",
    0xA022: "WB_RGGBLevelsAuto",
    0xA023: "WB_RGGBLevelsIlluminator1",
    0xA024: "WB_RGGBLevelsIlluminator2",
    0xA025: "HighlightLinearityLimit",
    0xA028: "WB_RGGBLevelsBlack",
    0xA030: "ColorMatrix",
    0xA031: "ColorMatrixSRGB",
    0xA032: "ColorMatrixAdobeRGB",
    0xA033: "CbCrMatrixDefault",
    0xA034: "CbCrMatrix",
    0xA035: "CbCrGainDefault",
    0xA036: "CbCrGain",
    0xA040: "ToneCurveSRGBDefault",
    0xA041: "ToneCurveAdobeRGBDefault",
    0xA042: "ToneCurveSRGB",
    0xA043: "ToneCurveAdobeRGB",
}
