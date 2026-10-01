"""色の加工に共通の部品（ルックアップテーブル・トーンカーブ・アルファの扱い・粒子）。

filters（テイスト）と effects（色の調整・周辺減光・経年劣化など）から使う。
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable

from PIL import Image, ImageChops

Curve = Callable[[float], float]  # 0〜1 → 0〜1 のトーンカーブ


def clip_table(values: Iterable[float]) -> list[int]:
    """四捨五入して 0〜255 にクリップしたルックアップテーブルを返す。"""
    return [min(255, max(0, int(v + 0.5))) for v in values]


def curve_table(curve: Curve) -> list[int]:
    """トーンカーブ (0〜1 → 0〜1) を 0〜255 の 1 チャンネル分のテーブルにする。"""
    return clip_table(curve(v / 255) * 255 for v in range(256))


def smoothstep(x: float) -> float:
    """0 → 0、1 → 1 で、両端がなめらかな S 字カーブ。"""
    return x * x * (3 - 2 * x)


def s_curve(x: float, strength: float) -> float:
    """直線と smoothstep を strength の割合（0 = 直線、1 = smoothstep）で混ぜた S 字カーブ。"""
    return (1 - strength) * x + strength * smoothstep(x)


def map_rgb(image: Image.Image, process: Callable[[Image.Image], Image.Image]) -> Image.Image:
    """RGB にだけ process をかけ、アルファは元のまま戻した新しい画像を返す。

    process には RGB の画像が渡る（RGBA なら RGB にしたもの）。入力画像は変更しない。
    """
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = process(image.convert("RGB"))
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def apply_curve(image: Image.Image, curve: Curve) -> Image.Image:
    """R・G・B に同じトーンカーブをかけた新しい画像を返す（アルファは元のまま）。"""
    table = curve_table(curve)
    return map_rgb(image, lambda rgb: rgb.point(table * 3))


def add_grain(image: Image.Image, strength: int, seed: int) -> Image.Image:
    """RGB 画像にモノクロの粒子（ノイズ）を重ねる。同じ seed と大きさなら毎回同じ模様になる。

    明るさは最大で ±strength 変化する。
    """
    rng = random.Random(seed)
    size = image.size

    def uniform_noise() -> Image.Image:
        return Image.frombytes("L", size, rng.randbytes(size[0] * size[1]))

    # 一様乱数 2 つの平均で、中央 (128) に寄った自然な粒子にする
    noise = Image.blend(uniform_noise(), uniform_noise(), 0.5)
    scale = strength / 128
    brighter = noise.point([int(max(0, v - 128) * scale + 0.5) for v in range(256)])
    darker = noise.point([int(max(0, 128 - v) * scale + 0.5) for v in range(256)])
    image = ImageChops.add(image, Image.merge("RGB", (brighter,) * 3))
    return ImageChops.subtract(image, Image.merge("RGB", (darker,) * 3))
