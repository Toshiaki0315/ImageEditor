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
_WHITE = (255, 255, 255)


class UnsupportedImageError(Exception):
    """非対応・破損などで画像を扱えないときに送出する例外。"""


@dataclass(frozen=True)
class LoadedImage:
    """読み込んだ画像と、その元ファイルの情報。"""

    image: Image.Image
    format: str
    is_animated: bool
    path: Path


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


def save_image(image: Image.Image, path: StrPath, quality: int = DEFAULT_JPEG_QUALITY) -> None:
    """拡張子から形式を決めて画像を保存する。

    JPEG / BMP では透過を白背景に合成して RGB で保存する。
    """
    path = Path(path)
    file_format = format_for_path(path)

    if file_format in _OPAQUE_FORMATS:
        image = flatten_alpha(image)

    options: dict[str, object] = {}
    if file_format == "JPEG":
        options["quality"] = quality

    image.save(path, format=file_format, **options)


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
