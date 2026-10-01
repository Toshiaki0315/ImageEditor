"""写真に記録された EXIF・位置情報 (GPS)・MakerNote を、表示用に読む。

読み込み時に Pillow が持つ元の EXIF のバイト列（または TIFF ファイルそのもの）を
exifread で読む。exifread が MakerNote を読めないメーカー（ペンタックス・リコー・
Samsung など）は core.makernote で読む。保存用に整えた EXIF ではなく元のバイト列を
使うのは、MakerNote の中の値の位置がずれないようにするため。
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import exifread

from image_editor.core.io import LoadedImage
from image_editor.core.makernote import read_maker_note
from image_editor.core.tiff import tiff_block  # noqa: F401 - 外からも使う

# 値の表示の長さの上限（それより長ければ省略する）
MAX_VALUE_LENGTH = 300
# TIFF ファイルから MakerNote を自前で読むとき、ファイル全体を読み込む大きさの上限
MAX_TIFF_READ = 64 * 1024 * 1024

# exifread の警告（壊れたタグなど）は表示に関係ないので出さない
logging.getLogger("exifread").setLevel(logging.ERROR)


class ExifGroup(Enum):
    """表示するときのグループ（並びもこの順）。値は表示名。"""

    IMAGE = "画像"
    EXIF = "撮影"
    GPS = "位置情報 (GPS)"
    MAKERNOTE = "MakerNote"
    INTEROP = "互換性"
    THUMBNAIL = "サムネイル"


_PREFIX_GROUPS: dict[str, ExifGroup] = {
    "Image": ExifGroup.IMAGE,
    "EXIF": ExifGroup.EXIF,
    "GPS": ExifGroup.GPS,
    "MakerNote": ExifGroup.MAKERNOTE,
    "Interoperability": ExifGroup.INTEROP,
    "Thumbnail": ExifGroup.THUMBNAIL,
}
# ほかの IFD の位置を指すだけのタグは出さない
_POINTER_TAGS = frozenset({"ExifOffset", "GPSInfo", "InteroperabilityOffset", "SubIFDs"})
# TIFF の画像の構造を表すだけのタグ（これしかなければ「EXIF がない」とみなす）
_STRUCTURE_TAGS = frozenset(
    {
        "SubfileType",
        "OldSubfileType",
        "ImageWidth",
        "ImageLength",
        "BitsPerSample",
        "Compression",
        "PhotometricInterpretation",
        "FillOrder",
        "StripOffsets",
        "SamplesPerPixel",
        "RowsPerStrip",
        "StripByteCounts",
        "PlanarConfiguration",
        "Predictor",
        "TileWidth",
        "TileLength",
        "TileOffsets",
        "TileByteCounts",
        "ExtraSamples",
        "SampleFormat",
        "JPEGInterchangeFormat",
        "JPEGInterchangeFormatLength",
    }
)


@dataclass(frozen=True)
class ExifEntry:
    """表示する 1 項目。tag は元のタグ名（exifread・ExifTool の名前）。"""

    group: ExifGroup
    tag: str
    value: str

    @property
    def label(self) -> str:
        """項目名。日本語訳が分かれば「ExposureTime（露出時間）」のように添える。"""
        japanese = JAPANESE_NAMES.get(self.tag)
        return f"{self.tag}（{japanese}）" if japanese else self.tag


@dataclass(frozen=True)
class GpsPosition:
    """撮影した場所（10 進の度。南緯・西経は負）。"""

    latitude: float
    longitude: float

    def map_url(self) -> str:
        """macOS のマップアプリでこの場所を開く URL。"""
        point = f"{self.latitude:.6f},{self.longitude:.6f}"
        return f"maps://?ll={point}&q={point}"


@dataclass(frozen=True)
class ExifInfo:
    """読めた EXIF の情報。maker_note は MakerNote の形式（なければ None）。"""

    entries: tuple[ExifEntry, ...] = ()
    maker_note: str | None = None
    gps: GpsPosition | None = None

    def is_empty(self) -> bool:
        """表示する情報がないか（画像の構造を表すタグしかない場合も含む）。"""
        return all(entry.tag in _STRUCTURE_TAGS for entry in self.entries)

    def groups(self) -> list[tuple[ExifGroup, tuple[ExifEntry, ...]]]:
        """グループごとの項目を、ExifGroup の順に返す（項目のないグループは除く）。"""
        result = []
        for group in ExifGroup:
            entries = tuple(entry for entry in self.entries if entry.group is group)
            if entries:
                result.append((group, entries))
        return result


def read_exif_info(raw_exif: bytes | None = None, tiff_path: Path | None = None) -> ExifInfo:
    """EXIF を読んで表示用の情報を返す。読めなければ空の ExifInfo。

    raw_exif は読み込み時の元の EXIF（JPEG・HEIC・PNG など）。TIFF ファイルは EXIF が
    ファイルそのものに入っているので、代わりに tiff_path を渡す。
    """
    data = tiff_block(raw_exif)
    if data is None and tiff_path is not None:
        try:
            if tiff_path.stat().st_size <= MAX_TIFF_READ:
                data = tiff_block(tiff_path.read_bytes())
            else:
                # 大きすぎる TIFF は exifread にファイルから読ませる（MakerNote は自前で読まない）
                with tiff_path.open("rb") as file:
                    return _build(_process(file), None)
        except OSError:
            return ExifInfo()
    if data is None:
        return ExifInfo()
    return _build(_process(io.BytesIO(data)), data)


def exif_info_of(loaded: LoadedImage) -> ExifInfo:
    """読み込んだ画像の元ファイルの EXIF を読む（TIFF はファイルから読む）。"""
    tiff_path = loaded.path if loaded.format == "TIFF" and loaded.path is not None else None
    return read_exif_info(loaded.raw_exif, tiff_path)


def _process(file: Any) -> dict[str, Any]:
    """exifread で読む。MakerNote の読み取りで失敗したら、MakerNote なしで読み直す。"""
    for details in (True, False):
        try:
            file.seek(0)
            return exifread.process_file(file, details=details, extract_thumbnail=False)
        except Exception:  # 壊れた EXIF・MakerNote でもアプリは止めない
            continue
    return {}


def _build(tags: dict[str, Any], data: bytes | None) -> ExifInfo:
    entries: list[ExifEntry] = []
    maker_note: str | None = None
    raw_maker_note = None
    for key, value in tags.items():
        prefix, _, name = key.partition(" ")
        group = _PREFIX_GROUPS.get(prefix)
        if group is None or not name or name in _POINTER_TAGS:
            continue
        if group is ExifGroup.EXIF and name == "MakerNote":
            raw_maker_note = value  # 中身を読めたかどうかで、出し方を後で決める
            continue
        entries.append(ExifEntry(group, name, _value_text(value)))

    if any(entry.group is ExifGroup.MAKERNOTE for entry in entries):
        # exifread が読めたメーカー（Canon・Nikon・Sony・Apple など）
        maker_note = _text(tags.get("Image Make")) or "MakerNote"
    else:
        # exifread が読めなかった MakerNote は、ペンタックス・リコー・Samsung などとして読む
        # （MakerNote の場所は EXIF から自分で探す）
        result = read_maker_note(data) if data is not None else None
        if result is not None and result.is_decoded():
            maker_note = result.format
            entries += [ExifEntry(ExifGroup.MAKERNOTE, t.name, t.value) for t in result.tags]
        elif result is not None or raw_maker_note is not None:
            size = result.size if result is not None else len(raw_maker_note.values)
            kind = result.format if result is not None else "不明な形式"
            maker_note = f"{kind}（解読できない形式）"
            summary = f"解読できない形式（{size} バイト）"
            entries.append(ExifEntry(ExifGroup.MAKERNOTE, "MakerNote", summary))

    gps = _gps_position(tags)
    entries = [_friendly_gps(entry, tags) for entry in entries]
    return ExifInfo(tuple(entries), maker_note, gps)


def _value_text(value: Any) -> str:
    text = _text(value)
    if len(text) > MAX_VALUE_LENGTH:
        return text[:MAX_VALUE_LENGTH] + "…"
    return text


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\0", "").strip()


# --- 位置情報 ------------------------------------------------------------------------


def _degrees(value: Any) -> float | None:
    """緯度・経度のタグ（度・分・秒の 3 つ）を 10 進の度にする。読めなければ None。"""
    try:
        degrees, minutes, seconds = (float(v) for v in value.values)
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return None
    return degrees + minutes / 60 + seconds / 3600


def _gps_position(tags: dict[str, Any]) -> GpsPosition | None:
    latitude = _degrees(tags.get("GPS GPSLatitude"))
    longitude = _degrees(tags.get("GPS GPSLongitude"))
    if latitude is None or longitude is None:
        return None
    if _text(tags.get("GPS GPSLatitudeRef")).upper().startswith("S"):
        latitude = -latitude
    if _text(tags.get("GPS GPSLongitudeRef")).upper().startswith("W"):
        longitude = -longitude
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return GpsPosition(latitude, longitude)


def format_dms(degrees: float, positive: str, negative: str) -> str:
    """10 進の度を「35° 39′ 21.87″ N」のような度分秒にする（符号は方角の文字で表す）。"""
    sign = positive if degrees >= 0 else negative
    value = abs(degrees)
    whole = int(value)
    minutes_float = (value - whole) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    if seconds >= 59.995:  # 四捨五入で 60.00″ にならないよう繰り上げる
        seconds = 0.0
        minutes += 1
    if minutes == 60:
        minutes = 0
        whole += 1
    return f"{whole}° {minutes}′ {seconds:.2f}″ {sign}"


def _friendly_gps(entry: ExifEntry, tags: dict[str, Any]) -> ExifEntry:
    """緯度・経度・高度を読みやすい値にする（ほかの項目はそのまま）。"""
    if entry.group is not ExifGroup.GPS:
        return entry
    if entry.tag in ("GPSLatitude", "GPSLongitude"):
        value = _degrees(tags.get(f"GPS {entry.tag}"))
        if value is None:
            return entry
        reference = _text(tags.get(f"GPS {entry.tag}Ref")).upper()
        positive, negative = ("N", "S") if entry.tag == "GPSLatitude" else ("E", "W")
        if reference.startswith(negative):
            value = -value
        text = f"{format_dms(value, positive, negative)}（{value:.6f}）"
        return ExifEntry(entry.group, entry.tag, text)
    if entry.tag == "GPSAltitude":
        try:
            meters = float(tags["GPS GPSAltitude"].values[0])
        except (KeyError, AttributeError, IndexError, TypeError, ValueError, ZeroDivisionError):
            return entry
        below = _text(tags.get("GPS GPSAltitudeRef")) in ("1", "Below Sea Level")
        place = "海面下" if below else "海抜"
        return ExifEntry(entry.group, entry.tag, f"{place} {meters:.1f} m")
    return entry


# --- 日本語訳 ------------------------------------------------------------------------

JAPANESE_NAMES: dict[str, str] = {
    # 画像 (IFD0)
    "ImageWidth": "画像の幅",
    "ImageLength": "画像の高さ",
    "BitsPerSample": "画素のビット数",
    "Compression": "圧縮方式",
    "PhotometricInterpretation": "画素の構成",
    "ImageDescription": "画像の説明",
    "Make": "メーカー",
    "Model": "機種",
    "StripOffsets": "画像データの位置",
    "Orientation": "画像の向き",
    "SamplesPerPixel": "色の成分の数",
    "RowsPerStrip": "ストリップの行数",
    "StripByteCounts": "ストリップのバイト数",
    "XResolution": "水平解像度",
    "YResolution": "垂直解像度",
    "PlanarConfiguration": "画像データの並び",
    "ResolutionUnit": "解像度の単位",
    "TransferFunction": "再生階調カーブ",
    "Software": "ソフトウェア",
    "DateTime": "更新日時",
    "Artist": "撮影者",
    "HostComputer": "ホストコンピューター",
    "WhitePoint": "白色点",
    "PrimaryChromaticities": "原色の色度",
    "JPEGInterchangeFormat": "JPEG データの位置",
    "JPEGInterchangeFormatLength": "JPEG データのバイト数",
    "YCbCrCoefficients": "色変換の係数",
    "YCbCrSubSampling": "色差のサンプリング比",
    "YCbCrPositioning": "色差の画素の位置",
    "ReferenceBlackWhite": "黒と白の基準値",
    "Copyright": "著作権",
    "Rating": "評価",
    "DocumentName": "文書名",
    "PageName": "ページ名",
    "InterColorProfile": "ICC プロファイル",
    "XPTitle": "タイトル",
    "XPComment": "コメント",
    "XPAuthor": "作成者",
    "XPKeywords": "キーワード",
    "XPSubject": "件名",
    # 撮影 (Exif IFD)
    "ExposureTime": "露出時間",
    "FNumber": "F 値",
    "ExposureProgram": "露出プログラム",
    "SpectralSensitivity": "分光感度",
    "ISOSpeedRatings": "撮影感度",
    "OECF": "光電変換関数",
    "SensitivityType": "感度の種類",
    "RecommendedExposureIndex": "推奨露光指数",
    "ISOSpeed": "ISO スピード",
    "ExifVersion": "Exif のバージョン",
    "DateTimeOriginal": "撮影日時",
    "DateTimeDigitized": "デジタル化した日時",
    "OffsetTime": "更新日時の時差",
    "OffsetTimeOriginal": "撮影日時の時差",
    "OffsetTimeDigitized": "デジタル化した日時の時差",
    "ComponentsConfiguration": "色の成分の並び",
    "CompressedBitsPerPixel": "画像の圧縮率",
    "ShutterSpeedValue": "シャッタースピード (APEX)",
    "ApertureValue": "絞り値 (APEX)",
    "BrightnessValue": "輝度値 (APEX)",
    "ExposureBiasValue": "露出補正",
    "MaxApertureValue": "レンズの開放 F 値 (APEX)",
    "SubjectDistance": "被写体までの距離",
    "MeteringMode": "測光方式",
    "LightSource": "光源",
    "Flash": "フラッシュ",
    "FocalLength": "焦点距離",
    "SubjectArea": "被写体の領域",
    "MakerNote": "メーカーノート",
    "UserComment": "ユーザーコメント",
    "SubSecTime": "更新日時の秒未満",
    "SubSecTimeOriginal": "撮影日時の秒未満",
    "SubSecTimeDigitized": "デジタル化した日時の秒未満",
    "FlashPixVersion": "FlashPix のバージョン",
    "ColorSpace": "色空間",
    "ExifImageWidth": "画像の幅",
    "ExifImageLength": "画像の高さ",
    "RelatedSoundFile": "関連する音声ファイル",
    "FlashEnergy": "フラッシュの強さ",
    "SpatialFrequencyResponse": "空間周波数応答",
    "FocalPlaneXResolution": "焦点面の水平解像度",
    "FocalPlaneYResolution": "焦点面の垂直解像度",
    "FocalPlaneResolutionUnit": "焦点面の解像度の単位",
    "SubjectLocation": "被写体の位置",
    "ExposureIndex": "露出インデックス",
    "SensingMethod": "センサーの方式",
    "FileSource": "ファイルの出どころ",
    "SceneType": "シーンの種類",
    "CVAPattern": "CFA パターン",
    "CFAPattern": "CFA パターン",
    "CustomRendered": "画像処理",
    "ExposureMode": "露出モード",
    "WhiteBalance": "ホワイトバランス",
    "DigitalZoomRatio": "デジタルズームの倍率",
    "FocalLengthIn35mmFilm": "35mm 換算の焦点距離",
    "SceneCaptureType": "撮影シーン",
    "GainControl": "ゲイン制御",
    "Contrast": "コントラスト",
    "Saturation": "彩度",
    "Sharpness": "シャープネス",
    "DeviceSettingDescription": "撮影条件の記述",
    "SubjectDistanceRange": "被写体までの距離の範囲",
    "ImageUniqueID": "画像の固有 ID",
    "CameraOwnerName": "カメラの所有者",
    "BodySerialNumber": "カメラのシリアル番号",
    "LensSpecification": "レンズの仕様",
    "LensMake": "レンズのメーカー",
    "LensModel": "レンズの機種",
    "LensSerialNumber": "レンズのシリアル番号",
    "Gamma": "ガンマ",
    "ImageNumber": "画像番号",
    "TimeZoneOffset": "時差",
    "SelfTimerMode": "セルフタイマー",
    "PrintIM": "プリントの設定 (PrintIM)",
    # 位置情報 (GPS)
    "GPSVersionID": "GPS タグのバージョン",
    "GPSLatitudeRef": "北緯・南緯",
    "GPSLatitude": "緯度",
    "GPSLongitudeRef": "東経・西経",
    "GPSLongitude": "経度",
    "GPSAltitudeRef": "高度の基準",
    "GPSAltitude": "高度",
    "GPSTimeStamp": "GPS の時刻 (UTC)",
    "GPSSatellites": "測位に使った衛星",
    "GPSStatus": "受信機の状態",
    "GPSMeasureMode": "測位の方式",
    "GPSDOP": "測位の精度",
    "GPSSpeedRef": "速度の単位",
    "GPSSpeed": "速度",
    "GPSTrackRef": "進行方向の基準",
    "GPSTrack": "進行方向",
    "GPSImgDirectionRef": "撮影方向の基準",
    "GPSImgDirection": "撮影方向",
    "GPSMapDatum": "測地系",
    "GPSDestLatitudeRef": "目的地の北緯・南緯",
    "GPSDestLatitude": "目的地の緯度",
    "GPSDestLongitudeRef": "目的地の東経・西経",
    "GPSDestLongitude": "目的地の経度",
    "GPSDestBearingRef": "目的地の方角の基準",
    "GPSDestBearing": "目的地の方角",
    "GPSDestDistanceRef": "目的地までの距離の単位",
    "GPSDestDistance": "目的地までの距離",
    "GPSProcessingMethod": "測位方式の名前",
    "GPSAreaInformation": "測位した地点の名前",
    "GPSDate": "GPS の日付",
    "GPSDifferential": "差分補正",
    "GPSHPositioningError": "水平方向の測位誤差",
    # 互換性
    "InteroperabilityIndex": "互換性の識別子",
    "InteroperabilityVersion": "互換性のバージョン",
    "RelatedImageFileFormat": "関連画像のファイル形式",
    "RelatedImageWidth": "関連画像の幅",
    "RelatedImageLength": "関連画像の高さ",
    # MakerNote でよく使われる名前
    "Quality": "画質",
    "FlashMode": "フラッシュモード",
    "FocusMode": "フォーカスモード",
    "ISO": "ISO 感度",
    "ExposureCompensation": "露出補正",
    "SerialNumber": "シリアル番号",
    "InternalSerialNumber": "内部シリアル番号",
    "FirmwareVersion": "ファームウェアのバージョン",
    "LensType": "レンズの種類",
    "ShutterCount": "シャッター回数",
    "DriveMode": "ドライブモード",
    "NoiseReduction": "ノイズリダクション",
    "ColorTemperature": "色温度",
    "CameraTemperature": "カメラの温度",
    "FrameNumber": "コマ番号",
    "PictureMode": "ピクチャーモード",
    "ImageTone": "仕上がり",
    "MacroMode": "マクロモード",
    "DigitalZoom": "デジタルズーム",
    "ImageType": "画像の種類",
    "OwnerName": "所有者",
    "AFAreaMode": "AF エリアモード",
    "FaceDetect": "顔検出",
    "DeviceType": "機器の種類",
    "MakerNoteVersion": "メーカーノートのバージョン",
    "DynamicRangeExpansion": "ダイナミックレンジ拡大",
    "AspectRatio": "縦横比",
    "Date": "日付",
    "Time": "時刻",
    "WhiteBalanceMode": "ホワイトバランスのモード",
    "AutoBracketing": "オートブラケット",
    "HighISONoiseReduction": "高感度ノイズリダクション",
    "ShakeReductionInfo": "手ぶれ補正の情報",
    "LensInfo": "レンズの情報",
    "FirmwareName": "ファームウェア名",
    "LensFirmware": "レンズのファームウェア",
}
