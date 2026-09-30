"""写真の形（矩形・角丸・円）の切り抜き。"""

from __future__ import annotations

import math
from array import array
from enum import Enum

from PIL import Image, ImageChops, ImageMath

CORNER_RADIUS_MIN = 0
CORNER_RADIUS_MAX = 50  # 短辺に対する %。50 で両端が半円（カプセル形）
CORNER_RADIUS_DEFAULT = 10


class ShapeType(Enum):
    """写真の形。"""

    RECTANGLE = "rectangle"
    ROUNDED = "rounded"
    CIRCLE = "circle"

    @property
    def label(self) -> str:
        """UI に表示する日本語名。"""
        return _LABELS[self]


_LABELS: dict[ShapeType, str] = {
    ShapeType.RECTANGLE: "矩形",
    ShapeType.ROUNDED: "角丸",
    ShapeType.CIRCLE: "円",
}


def shape_aspect(shape: ShapeType) -> tuple[int, int] | None:
    """形に合わせて写真を切り抜くときの縦横比を返す（円は正方形）。切り抜かないなら None。"""
    return (1, 1) if shape is ShapeType.CIRCLE else None


def shape_mask(size: tuple[int, int], shape: ShapeType, corner_radius: int) -> Image.Image | None:
    """形の内側を 255、外側を 0 とする L モードのマスクを返す（縁はアンチエイリアス）。

    - 角丸: 角の半径 = 短辺 × corner_radius%（0〜50）
    - 円: 中央の、短辺を直径とする正円
    矩形、または角丸の半径が 0 なら None（切り抜かない）。
    """
    width, height = size
    short_side = min(width, height)
    if shape is ShapeType.CIRCLE:
        circle = _rounded_rect_mask((short_side, short_side), short_side / 2)
        mask = Image.new("L", size, 0)
        mask.paste(circle, ((width - short_side) // 2, (height - short_side) // 2))
        return mask
    if shape is ShapeType.ROUNDED:
        percent = min(max(corner_radius, CORNER_RADIUS_MIN), CORNER_RADIUS_MAX)
        radius = short_side * percent / 100
        if radius <= 0:
            return None
        return _rounded_rect_mask(size, radius)
    return None


def apply_shape(
    image: Image.Image,
    shape: ShapeType,
    corner_radius: int,
    fill: tuple[int, int, int] | None = None,
) -> Image.Image:
    """画像を形で切り抜いた新しい画像を返す（入力画像は変更しない）。

    fill が None なら形の外側を透明にして RGBA で返す（元の透過も残す）。fill を指定すると
    形の外側をその色で不透明に塗る（フレームと組み合わせるとき用。写真の透過は残す）。
    矩形ならコピーを返す。
    """
    mask = shape_mask(image.size, shape, corner_radius)
    if mask is None:
        return image.copy()
    if fill is not None:
        color = fill if image.mode == "RGB" else (*fill, 255)
        background = Image.new(image.mode, image.size, color)
        background.paste(image, (0, 0), mask)
        return background
    shaped = image.convert("RGBA")
    shaped.putalpha(ImageChops.multiply(shaped.getchannel("A"), mask))
    return shaped


def _rounded_rect_mask(size: tuple[int, int], radius: float) -> Image.Image:
    """角を半径 radius の円弧にした長方形のマスクを返す（radius は短辺の半分まで）。

    アンチエイリアスが必要なのは角だけなので、角の部分だけを計算して四隅に反転して貼る。
    """
    width, height = size
    radius = min(radius, min(width, height) / 2)
    corner = _corner_mask(radius)
    mask = Image.new("L", size, 255)
    n = corner.width
    mask.paste(corner, (0, 0))
    mask.paste(corner.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (width - n, 0))
    mask.paste(corner.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (0, height - n))
    mask.paste(corner.transpose(Image.Transpose.ROTATE_180), (width - n, height - n))
    return mask


def _corner_mask(radius: float) -> Image.Image:
    """左上の角（ceil(radius) 四方）のマスクを返す。円弧の中心は (radius, radius)。

    画素の中心から円弧までの距離 (r - d) を、縁の近くで正確な (r² - d²) / 2r で近似し、
    0.5 を足して 1px 幅でなめらかに 0〜255 に変える（ImageMath で画像単位に計算する）。
    """
    n = max(1, math.ceil(radius))
    # 円弧の中心までの横方向の距離の 2 乗（中心より右の画素は 0 = まっすぐな辺）
    offsets = array("f", (max(0.0, radius - (i + 0.5)) ** 2 for i in range(n)))
    dx2 = Image.frombytes("F", (n, 1), offsets.tobytes()).resize((n, n), Image.Resampling.NEAREST)
    dy2 = dx2.transpose(Image.Transpose.TRANSPOSE)
    scale = 255 / (2 * radius)
    offset = 127.5 + radius * radius * scale
    alpha = ImageMath.lambda_eval(
        lambda args: args["min"](args["max"](offset - (args["x"] + args["y"]) * scale, 0.0), 255.0),
        x=dx2,
        y=dy2,
    )
    return alpha.convert("L")
