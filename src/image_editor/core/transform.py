"""トリミング・リサイズ。"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

MIN_SIZE = 1
MAX_SIZE = 20000


@dataclass(frozen=True)
class CropRect:
    """トリミング範囲（原画像の座標系、px）。"""

    x: int
    y: int
    width: int
    height: int


def clamp_crop(rect: CropRect, image_size: tuple[int, int]) -> CropRect | None:
    """範囲を画像内に収まるよう補正して返す。

    画像との重なり部分に切り詰める。幅・高さが 0 以下、または画像と重ならない場合は None。
    """
    if rect.width <= 0 or rect.height <= 0:
        return None
    image_width, image_height = image_size
    left = max(rect.x, 0)
    top = max(rect.y, 0)
    right = min(rect.x + rect.width, image_width)
    bottom = min(rect.y + rect.height, image_height)
    if right <= left or bottom <= top:
        return None
    return CropRect(left, top, right - left, bottom - top)


def fit_aspect(rect: CropRect, aspect: tuple[float, float]) -> CropRect:
    """範囲を縦横比 aspect (幅, 高さ) になるよう中央で切り詰めた範囲を返す。

    長すぎる側だけを両端から均等に削る。端数は四捨五入し、最小 1px。
    """
    aspect_width, aspect_height = aspect
    if rect.width * aspect_height > rect.height * aspect_width:
        width = min(rect.width, max(MIN_SIZE, round(rect.height * aspect_width / aspect_height)))
        return CropRect(rect.x + (rect.width - width) // 2, rect.y, width, rect.height)
    height = min(rect.height, max(MIN_SIZE, round(rect.width * aspect_height / aspect_width)))
    return CropRect(rect.x, rect.y + (rect.height - height) // 2, rect.width, height)


def crop(image: Image.Image, rect: CropRect) -> Image.Image:
    """画像を指定範囲で切り抜く。範囲は事前に clamp_crop で補正しておくこと。"""
    return image.crop((rect.x, rect.y, rect.x + rect.width, rect.y + rect.height))


def fit_size(
    orig_size: tuple[int, int],
    width: int | None,
    height: int | None,
    keep_aspect: bool,
) -> tuple[int, int]:
    """指定された幅・高さと縦横比保持の設定から出力サイズを計算する。

    - 両方 None: 元のサイズ
    - 片方だけ指定: keep_aspect なら縦横比から他方を計算、そうでなければ他方は元のまま
    - 両方指定: keep_aspect なら指定範囲に収まる最大サイズ、そうでなければ指定どおり

    端数は四捨五入し、最小 1px。指定値が 1〜20000 の範囲外なら ValueError。
    """
    for name, value in (("width", width), ("height", height)):
        if value is not None and not MIN_SIZE <= value <= MAX_SIZE:
            raise ValueError(f"{name} は {MIN_SIZE}〜{MAX_SIZE} で指定してください: {value}")

    orig_width, orig_height = orig_size
    if width is None and height is None:
        return orig_size
    if not keep_aspect:
        return (width or orig_width, height or orig_height)

    if width is not None and height is not None:
        # 縦横比を保ったまま指定範囲に収める（縮小率が小さい方に合わせる）
        if width * orig_height <= height * orig_width:
            height = None
        else:
            width = None
    if width is not None:
        return (width, _round_div(orig_height * width, orig_width))
    assert height is not None
    return (_round_div(orig_width * height, orig_height), height)


def resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """画像を LANCZOS で指定サイズにリサイズする。"""
    return image.resize(size, Image.Resampling.LANCZOS)


def _round_div(numerator: int, denominator: int) -> int:
    """numerator / denominator を四捨五入し、最小 1 にする（浮動小数の誤差を避けて整数で計算）。"""
    return max(MIN_SIZE, (2 * numerator + denominator) // (2 * denominator))
