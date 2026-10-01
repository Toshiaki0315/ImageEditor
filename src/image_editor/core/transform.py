"""回転・反転・トリミング・リサイズ。"""

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

    @property
    def right(self) -> int:
        """右端の x 座標（範囲に含まない）。"""
        return self.x + self.width

    @property
    def bottom(self) -> int:
        """下端の y 座標（範囲に含まない）。"""
        return self.y + self.height

    @property
    def box(self) -> tuple[int, int, int, int]:
        """Pillow の crop などに渡す (左, 上, 右, 下)。"""
        return (self.x, self.y, self.right, self.bottom)


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
    right = min(rect.right, image_width)
    bottom = min(rect.bottom, image_height)
    if right <= left or bottom <= top:
        return None
    return CropRect(left, top, right - left, bottom - top)


def fit_aspect(rect: CropRect, aspect: tuple[float, float]) -> CropRect:
    """範囲を縦横比 aspect (幅, 高さ) になるよう中央で切り詰めた範囲を返す。

    長すぎる側だけを両端から均等に削る。端数は四捨五入し、最小 1px。
    """
    width, height = _fit_aspect_size(rect.width, rect.height, aspect)
    return CropRect(
        rect.x + (rect.width - width) // 2, rect.y + (rect.height - height) // 2, width, height
    )


def constrain_rect(
    rect: CropRect, aspect: tuple[float, float], image_size: tuple[int, int]
) -> CropRect | None:
    """範囲を画像内に収め、縦横比 aspect になるよう左上を固定して縮めた範囲を返す。

    数値入力で比を保つとき用。画像と重ならなければ None。
    """
    clamped = clamp_crop(rect, image_size)
    if clamped is None:
        return None
    return CropRect(clamped.x, clamped.y, *_fit_aspect_size(clamped.width, clamped.height, aspect))


def _fit_aspect_size(width: int, height: int, aspect: tuple[float, float]) -> tuple[int, int]:
    """width × height に収まる、縦横比 aspect の大きさ（長すぎる側だけを縮める、最小 1px）。"""
    aspect_width, aspect_height = aspect
    if width * aspect_height > height * aspect_width:
        return min(width, max(MIN_SIZE, round(height * aspect_width / aspect_height))), height
    return width, min(height, max(MIN_SIZE, round(width * aspect_height / aspect_width)))


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
    return image.crop(rect.box)


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


class OrientOp(Enum):
    """回転・反転の操作（表示中の向きに対して行う）。"""

    ROTATE_LEFT = "rotate_left"  # 反時計回りに 90°
    ROTATE_RIGHT = "rotate_right"  # 時計回りに 90°
    FLIP_HORIZONTAL = "flip_horizontal"  # 左右反転
    FLIP_VERTICAL = "flip_vertical"  # 上下反転

    @property
    def swaps_sides(self) -> bool:
        """幅と高さが入れ替わる操作か。"""
        return self in (OrientOp.ROTATE_LEFT, OrientOp.ROTATE_RIGHT)


# 時計回りの回転角 → PIL の Transpose（PIL の ROTATE_* は反時計回り）
_ROTATE_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


@dataclass(frozen=True)
class Orientation:
    """画像の向き。左右反転 (mirror) してから時計回りに rotation 度回した状態を表す。

    回転と反転の組み合わせはすべてこの 8 通りのどれかにまとまる。
    """

    rotation: int = 0  # 0 / 90 / 180 / 270（時計回り）
    mirror: bool = False

    def is_identity(self) -> bool:
        """回転も反転もしていないか。"""
        return self.rotation == 0 and not self.mirror

    def apply(self, op: OrientOp) -> Orientation:
        """今の向きに op を重ねた向きを返す。"""
        rotation, mirror = self.rotation, self.mirror
        if op is OrientOp.ROTATE_RIGHT:
            rotation += 90
        elif op is OrientOp.ROTATE_LEFT:
            rotation -= 90
        elif op is OrientOp.FLIP_HORIZONTAL:
            # 左右反転 ∘ 回転(r) = 回転(-r) ∘ 左右反転
            rotation, mirror = -rotation, not mirror
        else:
            # 上下反転 = 180° 回転 ∘ 左右反転
            rotation, mirror = 180 - rotation, not mirror
        return Orientation(rotation % 360, mirror)

    def size(self, size: tuple[int, int]) -> tuple[int, int]:
        """size の画像をこの向きにしたときの大きさを返す。"""
        return (size[1], size[0]) if self.rotation in (90, 270) else size

    def transpose(self, image: Image.Image) -> Image.Image:
        """画像をこの向きにした新しい画像を返す（入力画像は変更しない）。"""
        if self.mirror:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if self.rotation:
            image = image.transpose(_ROTATE_TRANSPOSE[self.rotation])
        return image


def transform_rect(rect: CropRect, image_size: tuple[int, int], op: OrientOp) -> CropRect:
    """image_size の画像上の範囲を、画像に op をかけた後の同じ部分を指す範囲に変換する。"""
    width, height = image_size
    if op is OrientOp.ROTATE_RIGHT:
        return CropRect(height - rect.bottom, rect.x, rect.height, rect.width)
    if op is OrientOp.ROTATE_LEFT:
        return CropRect(rect.y, width - rect.right, rect.height, rect.width)
    if op is OrientOp.FLIP_HORIZONTAL:
        return CropRect(width - rect.right, rect.y, rect.width, rect.height)
    return CropRect(rect.x, height - rect.bottom, rect.width, rect.height)


def resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """画像を LANCZOS で指定サイズにリサイズする。"""
    return image.resize(size, Image.Resampling.LANCZOS)


def _round_div(numerator: int, denominator: int) -> int:
    """numerator / denominator を四捨五入し、最小 1 にする（浮動小数の誤差を避けて整数で計算）。"""
    return max(MIN_SIZE, (2 * numerator + denominator) // (2 * denominator))
