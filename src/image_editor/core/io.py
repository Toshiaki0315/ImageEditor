"""画像の読み込み・保存・モード変換・EXIF 回転補正。"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from image_editor.core.tiff import (
    TAG_EXIF_IFD,
    TAG_GPS_IFD,
    TAG_MAKERNOTE,
    TAG_ORIENTATION,
    TAG_PIXEL_X,
    TAG_PIXEL_Y,
    ExifBlock,
    tiff_block,
)

# HEIC / HEIF（iPhone の写真）を Image.open で読めるようにする（読み込みだけに使う）
register_heif_opener()

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

# 保存できる拡張子
SAVABLE_EXTENSIONS: frozenset[str] = frozenset(_EXTENSION_FORMATS)
# 読み込みだけできる拡張子（保存するときは JPEG にする）
READ_ONLY_EXTENSIONS: frozenset[str] = frozenset({".heic", ".heif"})
# 読み込める拡張子
SUPPORTED_EXTENSIONS: frozenset[str] = SAVABLE_EXTENSIONS | READ_ONLY_EXTENSIONS
# 読み込みだけできる形式の画像を保存するときの拡張子
FALLBACK_SAVE_SUFFIX = ".jpg"

# 読み込みを許可する Pillow の形式（MPO は一部カメラの JPEG）
_LOADABLE_FORMATS: dict[str, str] = {
    "PNG": "PNG",
    "JPEG": "JPEG",
    "MPO": "JPEG",
    "GIF": "GIF",
    "TIFF": "TIFF",
    "BMP": "BMP",
    "HEIF": "HEIF",  # HEIC も含む
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
# クリップボードから貼り付けた画像の表示名と、保存するときの名前・形式・場所
PASTED_NAME = "クリップボードの画像"
PASTED_FILE_PREFIX = "クリップボード_"
PASTED_SAVE_SUFFIX = ".png"
PICTURES_DIR = Path.home() / "Pictures"
# JPEG の APP1 に入る EXIF の大きさの上限（"Exif\0\0" を含む）。超えたら MakerNote を外す
MAX_EXIF_BYTES = 65533


class UnsupportedImageError(Exception):
    """非対応・破損などで画像を扱えないときに送出する例外。"""


@dataclass(frozen=True)
class LoadedImage:
    """読み込んだ画像と、その元ファイルの情報。"""

    image: Image.Image
    format: str
    is_animated: bool
    path: Path | None  # 元のファイル。クリップボードから貼り付けた画像は None
    # 保存するときの元にする EXIF（なければ None）。元のバイト列があればそれ、なければ
    # （TIFF など）Pillow で読み直したもの（位置がずれて壊れるので MakerNote は除く）
    exif: bytes | None = None
    # 元ファイルの EXIF のバイト列そのもの（"Exif\0\0" で始まることもある）。MakerNote の中の
    # 値の位置がずれないよう、表示 (core.exif_info) にはこちらを使う。TIFF ファイルでは None
    raw_exif: bytes | None = None

    @property
    def name(self) -> str:
        """表示名（ファイル名。貼り付けた画像は「クリップボードの画像」）。"""
        return self.path.name if self.path is not None else PASTED_NAME


def pasted_image(image: Image.Image) -> LoadedImage:
    """クリップボードから貼り付けた画像を、元のファイルのない画像として返す（形式は PNG 扱い）。"""
    return LoadedImage(
        image=normalize_mode(image.copy()), format="PNG", is_animated=False, path=None
    )


def pasted_save_path(now: datetime | None = None, folder: Path | None = None) -> Path:
    """貼り付けた画像の保存ダイアログの初期パス「クリップボード_日時.png」を返す。

    場所は folder（省略時はピクチャフォルダ。なければホーム）。同じ名前があれば _2 … を付ける。
    """
    if folder is None:
        folder = PICTURES_DIR if PICTURES_DIR.is_dir() else Path.home()
    stem = f"{PASTED_FILE_PREFIX}{(now or datetime.now()):%Y%m%d-%H%M%S}"
    candidate = folder / f"{stem}{PASTED_SAVE_SUFFIX}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{number}{PASTED_SAVE_SUFFIX}"
        number += 1
    return candidate


@dataclass(frozen=True)
class SaveOptions:
    """保存時の設定。"""

    quality: int = DEFAULT_JPEG_QUALITY  # JPEG の品質 1〜100
    keep_exif: bool = True  # 撮影日時などの EXIF を残す（JPEG・PNG・TIFF）
    keep_gps: bool = False  # EXIF を残すとき、位置情報 (GPS) も残す


def is_supported(path: StrPath) -> bool:
    """拡張子が対応形式かどうかを返す（大文字・小文字は区別しない）。"""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def is_savable(path: StrPath) -> bool:
    """拡張子が保存できる形式かどうかを返す（大文字・小文字は区別しない）。"""
    return Path(path).suffix.lower() in SAVABLE_EXTENSIONS


def save_suffix(path: StrPath) -> str:
    """元の画像を保存するときの拡張子（保存できない形式なら .jpg）を返す。"""
    suffix = Path(path).suffix
    return suffix if is_savable(path) else FALLBACK_SAVE_SUFFIX


def format_for_path(path: StrPath) -> str:
    """拡張子から Pillow の保存形式名を返す。非対応なら UnsupportedImageError。"""
    suffix = Path(path).suffix.lower()
    try:
        return _EXTENSION_FORMATS[suffix]
    except KeyError:
        raise UnsupportedImageError(f"対応していない拡張子です: {suffix or '(なし)'}") from None


def default_save_path(path: Path) -> Path:
    """保存ダイアログの初期パス `<元の名前>_edited.<元の拡張子>` を返す。

    元の形式が保存できない（HEIC など）なら拡張子は .jpg にする。すでにあれば
    `_edited_2`、`_edited_3` … と、既存のファイルと重ならない名前にする。
    """
    return next(c for c in edited_names(path, path.parent) if not c.exists())


def edited_names(source: Path, folder: Path) -> Iterator[Path]:
    """folder に保存するときの名前の候補 `<元の名前>_edited`、`_edited_2` … を順に返す。

    拡張子は save_suffix（保存できない形式なら .jpg）。候補は終わりなく続く。
    """
    suffix = save_suffix(source)
    yield folder / f"{source.stem}_edited{suffix}"
    number = 2
    while True:
        yield folder / f"{source.stem}_edited_{number}{suffix}"
        number += 1


def path_key(path: Path) -> str:
    """同じファイルかを比べるためのキー（macOS のファイルシステムは大文字・小文字を区別しない）。"""
    return str(path.resolve()).casefold()


def is_same_file(a: Path, b: Path) -> bool:
    """2 つのパスが同じファイルを指すかを返す。

    macOS のファイルシステムは大文字・小文字を区別しないので、実在するファイルは
    os.path.samefile で判定し、まだ無いファイルは絶対パスを大文字・小文字を無視して比べる。
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return path_key(a) == path_key(b)


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
            raw_exif = source.info.get("exif")
            if not isinstance(raw_exif, bytes):
                raw_exif = None
            exif = raw_exif if tiff_block(raw_exif) is not None else _read_exif(source)
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
        raw_exif=raw_exif,
    )


def normalize_mode(image: Image.Image) -> Image.Image:
    """画像を RGB（透過ありなら RGBA）に変換して返す。"""
    mode = image.mode
    if mode in ("RGB", "RGBA"):
        return image
    if mode.startswith("I;16") or mode in ("I", "F"):
        return _to_8bit_gray(image).convert("RGB")
    if _has_alpha(image):
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


def save_edited(
    image: Image.Image,
    path: StrPath,
    options: SaveOptions,
    source_exif: bytes | None = None,
) -> None:
    """編集した画像を「保存の設定」に従って保存する。

    source_exif は元画像の EXIF。options.keep_exif のときだけ、prepare_exif で整えて書き込む。
    TIFF は Pillow が EXIF を書き直して MakerNote の中の値の位置がずれるので、MakerNote を残さない。
    """
    exif = None
    if options.keep_exif and source_exif is not None:
        keep_maker_note = format_for_path(path) != "TIFF"
        exif = prepare_exif(source_exif, image.size, options.keep_gps, keep_maker_note)
    save_image(image, path, quality=options.quality, exif=exif)


def prepare_exif(
    exif: bytes,
    size: tuple[int, int],
    keep_gps: bool = False,
    keep_maker_note: bool = True,
) -> bytes:
    """元画像の EXIF を、編集後の画像に書き込める形に整えて返す（元のデータは変えない）。

    - 向き (Orientation) は読み込み時に補正済みなので 1（そのまま）にする
    - Exif IFD の画像の幅・高さを size に合わせる
    - keep_gps が False なら位置情報 (GPS) を取り除く
    - MakerNote（メーカー独自の情報）は元と同じ位置に置き、中の値の位置がずれないようにする。
      keep_maker_note が False のとき・EXIF が JPEG に入らないほど大きいとき・元の EXIF の形を
      読めないときは、壊れた MakerNote を書かないよう残さない
    - サムネイルは編集前の画像なので残さない
    撮影日時・カメラなどのそれ以外のタグは元の値のまま残す。
    """
    try:
        block = ExifBlock.parse(exif)
    except (ValueError, struct.error):
        return _prepare_with_pillow(exif, size, keep_gps)
    block.set_short(block.ifd0, TAG_ORIENTATION, 1)
    if not keep_gps:
        block.gps = None
    for tag, length in ((TAG_PIXEL_X, size[0]), (TAG_PIXEL_Y, size[1])):
        if tag in block.exif:
            block.set_long(block.exif, tag, length)
    data = block.to_bytes(keep_maker_note)
    if keep_maker_note and len(data) > MAX_EXIF_BYTES:
        data = block.to_bytes(keep_maker_note=False)
    return data


def _prepare_with_pillow(exif: bytes, size: tuple[int, int], keep_gps: bool) -> bytes:
    """形を読めない EXIF を、Pillow で読んで整える（MakerNote は位置がずれるので外す）。"""
    data = Image.Exif()
    data.load(exif)
    data[TAG_ORIENTATION] = 1
    if not keep_gps and TAG_GPS_IFD in data:
        del data[TAG_GPS_IFD]
    if TAG_EXIF_IFD in data:
        exif_ifd = data.get_ifd(TAG_EXIF_IFD)
        exif_ifd.pop(TAG_MAKERNOTE, None)
        if TAG_PIXEL_X in exif_ifd:
            exif_ifd[TAG_PIXEL_X] = size[0]
        if TAG_PIXEL_Y in exif_ifd:
            exif_ifd[TAG_PIXEL_Y] = size[1]
    return data.tobytes()


def _read_exif(source: Image.Image) -> bytes | None:
    """元のバイト列がないとき（TIFF など）に、Pillow で読んだ EXIF を返す。

    Pillow で書き直すと MakerNote の中の値の位置がずれるので、MakerNote は外す。
    なければ、または壊れていて読めなければ None。
    """
    try:
        exif = source.getexif()
        if not len(exif):
            return None
        if TAG_EXIF_IFD in exif:
            exif.get_ifd(TAG_EXIF_IFD).pop(TAG_MAKERNOTE, None)
        return exif.tobytes()
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
