"""トリミング・リサイズ。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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


class AspectRatio(Enum):
    """トリミングの縦横比の選択肢。値は横向きのときの (幅, 高さ)。"""

    FREE = None
    SQUARE = (1, 1)
    RATIO_4_3 = (4, 3)
    RATIO_3_2 = (3, 2)
    RATIO_16_9 = (16, 9)

    @property
    def label(self) -> str:
        """UI に表示する名前。"""
        if self.value is None:
            return "自由"
        return f"{self.value[0]}:{self.value[1]}"

    def ratio(self, portrait: bool = False) -> tuple[int, int] | None:
        """縦横比 (幅, 高さ) を返す。portrait なら縦向きにする。自由なら None。"""
        if self.value is None:
            return None
        width, height = self.value
        return (height, width) if portrait else (width, height)


def oriented(aspect: tuple[float, float], landscape: bool) -> tuple[float, float]:
    """縦横比を横向き（幅 ≥ 高さ）または縦向きにそろえて返す。"""
    long_side, short_side = max(aspect), min(aspect)
    return (long_side, short_side) if landscape else (short_side, long_side)


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


def constrain_rect(
    rect: CropRect, aspect: tuple[float, float], image_size: tuple[int, int]
) -> CropRect | None:
    """範囲を画像内に収め、縦横比 aspect になるよう左上を固定して縮めた範囲を返す。

    数値入力で比を保つとき用。画像と重ならなければ None。
    """
    clamped = clamp_crop(rect, image_size)
    if clamped is None:
        return None
    aspect_width, aspect_height = aspect
    width, height = clamped.width, clamped.height
    if width * aspect_height > height * aspect_width:
        width = min(width, max(MIN_SIZE, round(height * aspect_width / aspect_height)))
    else:
        height = min(height, max(MIN_SIZE, round(width * aspect_height / aspect_width)))
    return CropRect(clamped.x, clamped.y, width, height)


def aspect_drag_rect(
    anchor: tuple[int, int],
    point: tuple[int, int],
    aspect: tuple[float, float],
    image_size: tuple[int, int],
) -> CropRect:
    """anchor を固定した角として point の方向へ広げた、縦横比 aspect の範囲を返す。

    ドラッグで比を保って範囲を選ぶとき用。マウスの位置まで届く大きさ（比に対して長い方の
    辺に合わせる）にし、画像の端を越えるときは比を保ったまま縮める。
    """
    anchor_x, anchor_y = anchor
    image_width, image_height = image_size
    aspect_width, aspect_height = aspect
    dx, dy = point[0] - anchor_x, point[1] - anchor_y
    width, height = float(abs(dx)), float(abs(dy))
    if width * aspect_height >= height * aspect_width:
        height = width * aspect_height / aspect_width
    else:
        width = height * aspect_width / aspect_height

    max_width = anchor_x if dx < 0 else image_width - anchor_x
    max_height = anchor_y if dy < 0 else image_height - anchor_y
    scale = 1.0
    if width > max_width:
        scale = max_width / width
    if height * scale > max_height:
        scale = max_height / height
    width_px = int(width * scale + 1e-9)
    height_px = min(max_height, round(width_px * aspect_height / aspect_width))

    x = anchor_x - width_px if dx < 0 else anchor_x
    y = anchor_y - height_px if dy < 0 else anchor_y
    return CropRect(x, y, width_px, height_px)


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
