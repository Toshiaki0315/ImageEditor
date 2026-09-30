"""画像の読み込み・保存・モード変換・EXIF 回転補正。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

StrPath = str | os.PathLike[str]

# 拡張子 -> Pillow の保存形式
_EXTENSION_FORMATS: dict[str, str] = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".gif": "GIF",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".bmp": "BMP",
}

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(_EXTENSION_FORMATS)

# 読み込みを許可する Pillow の形式（MPO は一部カメラの JPEG）
_LOADABLE_FORMATS: dict[str, str] = {
    "PNG": "PNG",
    "JPEG": "JPEG",
    "MPO": "JPEG",
    "GIF": "GIF",
    "TIFF": "TIFF",
    "BMP": "BMP",
}

# 透過を持てない保存形式
_OPAQUE_FORMATS = frozenset({"JPEG", "BMP"})

_ALPHA_MODES = frozenset({"RGBA", "LA", "PA", "RGBa", "La"})

DEFAULT_JPEG_QUALITY = 90
JPEG_QUALITY_MIN = 1
JPEG_QUALITY_MAX = 100
_WHITE = (255, 255, 255)

# EXIF を書き込める保存形式
_EXIF_FORMATS = frozenset({"JPEG", "PNG", "TIFF"})
# EXIF のタグ
_TAG_ORIENTATION = 0x0112
_TAG_EXIF_IFD = 0x8769
_TAG_GPS_IFD = 0x8825
_TAG_PIXEL_X = 0xA002  # Exif IFD の画像の幅
_TAG_PIXEL_Y = 0xA003  # Exif IFD の画像の高さ


class UnsupportedImageError(Exception):
    """非対応・破損などで画像を扱えないときに送出する例外。"""


@dataclass(frozen=True)
class LoadedImage:
    """読み込んだ画像と、その元ファイルの情報。"""

    image: Image.Image
    format: str
    is_animated: bool
    path: Path
    exif: bytes | None = None  # 元ファイルの EXIF（なければ None）


@dataclass(frozen=True)
class SaveOptions:
    """保存時の設定。"""

    quality: int = DEFAULT_JPEG_QUALITY  # JPEG の品質 1〜100
    keep_exif: bool = True  # 撮影日時などの EXIF を残す（JPEG・PNG・TIFF）
    keep_gps: bool = False  # EXIF を残すとき、位置情報 (GPS) も残す


def is_supported(path: StrPath) -> bool:
    """拡張子が対応形式かどうかを返す（大文字・小文字は区別しない）。"""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def format_for_path(path: StrPath) -> str:
    """拡張子から Pillow の保存形式名を返す。非対応なら UnsupportedImageError。"""
    suffix = Path(path).suffix.lower()
    try:
        return _EXTENSION_FORMATS[suffix]
    except KeyError:
        raise UnsupportedImageError(f"対応していない拡張子です: {suffix or '(なし)'}") from None


def default_save_path(path: Path) -> Path:
    """保存ダイアログの初期パス `<元の名前>_edited.<元の拡張子>` を返す。

    すでにあれば `_edited_2`、`_edited_3` … と、既存のファイルと重ならない名前にする。
    """
    candidate = path.with_name(f"{path.stem}_edited{path.suffix}")
    number = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_edited_{number}{path.suffix}")
        number += 1
    return candidate


def is_same_file(a: Path, b: Path) -> bool:
    """2 つのパスが同じファイルを指すかを返す。

    macOS のファイルシステムは大文字・小文字を区別しないので、実在するファイルは
    os.path.samefile で判定し、まだ無いファイルは絶対パスを大文字・小文字を無視して比べる。
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return str(a.resolve()).casefold() == str(b.resolve()).casefold()


def load_image(path: StrPath) -> LoadedImage:
    """画像を読み込み、EXIF 回転補正と RGB / RGBA への正規化を行って返す。

    GIF・TIFF は先頭フレームのみを扱う。読み込めない場合は UnsupportedImageError。
    """
    path = Path(path)
    if not is_supported(path):
        raise UnsupportedImageError(f"対応していない拡張子です: {path.suffix or '(なし)'}")

    try:
        with Image.open(path) as source:
            file_format = _LOADABLE_FORMATS.get(source.format or "")
            if file_format is None:
                raise UnsupportedImageError(f"対応していない画像形式です: {source.format}")
            is_animated = getattr(source, "n_frames", 1) > 1
            source.seek(0)
            exif = _read_exif(source)
            # exif_transpose は常に新しい画像を返すので、ファイルを閉じても使える
            image = ImageOps.exif_transpose(source)
            image.load()
    except UnsupportedImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as e:
        raise UnsupportedImageError(f"画像を読み込めません: {path.name}") from e

    return LoadedImage(
        image=normalize_mode(image),
        format=file_format,
        is_animated=is_animated,
        path=path,
        exif=exif,
    )


def normalize_mode(image: Image.Image) -> Image.Image:
    """画像を RGB（透過ありなら RGBA）に変換して返す。"""
    mode = image.mode
    if mode in ("RGB", "RGBA"):
        return image
    if mode.startswith("I;16") or mode in ("I", "F"):
        return _to_8bit_gray(image).convert("RGB")
    if mode in _ALPHA_MODES or (mode == "P" and "transparency" in image.info):
        return image.convert("RGBA")
    return image.convert("RGB")


def save_image(
    image: Image.Image,
    path: StrPath,
    quality: int = DEFAULT_JPEG_QUALITY,
    exif: bytes | None = None,
) -> None:
    """拡張子から形式を決めて画像を保存する。

    JPEG / BMP では透過を白背景に合成して RGB で保存する。quality は JPEG の品質
    （1〜100、範囲外なら ValueError）。exif を渡すと JPEG・PNG・TIFF に書き込む
    （prepare_exif で整えたものを渡す）。
    """
    if not JPEG_QUALITY_MIN <= quality <= JPEG_QUALITY_MAX:
        raise ValueError(
            f"quality は {JPEG_QUALITY_MIN}〜{JPEG_QUALITY_MAX} で指定してください: {quality}"
        )
    path = Path(path)
    file_format = format_for_path(path)

    if file_format in _OPAQUE_FORMATS:
        image = flatten_alpha(image)

    options: dict[str, object] = {}
    if file_format == "JPEG":
        options["quality"] = quality
    if exif is not None and file_format in _EXIF_FORMATS:
        options["exif"] = exif

    image.save(path, format=file_format, **options)


def prepare_exif(exif: bytes, size: tuple[int, int], keep_gps: bool = False) -> bytes:
    """元画像の EXIF を、編集後の画像に書き込める形に整えて返す（元のデータは変えない）。

    - 向き (Orientation) は読み込み時に補正済みなので 1（そのまま）にする
    - Exif IFD の画像の幅・高さを size に合わせる
    - keep_gps が False なら位置情報 (GPS) を取り除く
    撮影日時・カメラなどのそれ以外のタグは残す。
    """
    data = Image.Exif()
    data.load(exif)
    data[_TAG_ORIENTATION] = 1
    if not keep_gps and _TAG_GPS_IFD in data:
        del data[_TAG_GPS_IFD]
    if _TAG_EXIF_IFD in data:
        exif_ifd = data.get_ifd(_TAG_EXIF_IFD)
        if _TAG_PIXEL_X in exif_ifd:
            exif_ifd[_TAG_PIXEL_X] = size[0]
        if _TAG_PIXEL_Y in exif_ifd:
            exif_ifd[_TAG_PIXEL_Y] = size[1]
    return data.tobytes()


def _read_exif(source: Image.Image) -> bytes | None:
    """画像の EXIF を返す。なければ、または壊れていて読めなければ None。"""
    try:
        exif = source.getexif()
        return exif.tobytes() if len(exif) else None
    except Exception:  # EXIF が壊れていても画像は読み込めるようにする
        return None


def flatten_alpha(image: Image.Image, background: tuple[int, int, int] = _WHITE) -> Image.Image:
    """透過を指定色（既定は白）の背景に合成し、RGB 画像を返す。"""
    if not _has_alpha(image):
        return image if image.mode == "RGB" else image.convert("RGB")
    rgba = image.convert("RGBA")
    flattened = Image.new("RGB", rgba.size, background)
    flattened.paste(rgba, mask=rgba.getchannel("A"))
    return flattened


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in _ALPHA_MODES or (image.mode == "P" and "transparency" in image.info)


def _to_8bit_gray(image: Image.Image) -> Image.Image:
    """16bit / 32bit のグレースケール画像を 8bit (L) に変換する。"""
    if image.mode == "F":
        return image.convert("L")
    image = image.convert("I")
    _, max_value = image.getextrema()
    if max_value > 255:
        # 16bit の値域 (0〜65535) を 8bit に縮める
        image = image.point(lambda v: v * (1 / 256))
    return image.convert("L")
