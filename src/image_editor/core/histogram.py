"""ヒストグラム（明るさの分布）の計算。"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops

BINS = 256


@dataclass(frozen=True)
class Histogram:
    """R・G・B と輝度のヒストグラム（それぞれ 256 段階の画素数）。"""

    red: tuple[int, ...]
    green: tuple[int, ...]
    blue: tuple[int, ...]
    luma: tuple[int, ...]

    def channels(self) -> tuple[tuple[int, ...], ...]:
        """(R, G, B, 輝度) の順に返す。"""
        return (self.red, self.green, self.blue, self.luma)

    def total(self) -> int:
        """数えた画素の数を返す。"""
        return sum(self.luma)


def compute_histogram(image: Image.Image, mask: Image.Image | None = None) -> Histogram:
    """画像のヒストグラムを返す（入力画像は変更しない）。

    透過のある画像は透明な画素（アルファ 0）を数えない。mask（L モード、0 以外を数える）を
    渡すと、その範囲だけを数える。輝度は ITU-R 601（Pillow の L 変換）で求める。
    """
    rgb = image.convert("RGB")
    if image.mode == "RGBA":
        alpha = image.getchannel("A")
        mask = alpha if mask is None else ImageChops.multiply(alpha, mask)
    counts = rgb.histogram(mask)
    luma = tuple(rgb.convert("L").histogram(mask))
    return Histogram(
        red=tuple(counts[0:BINS]),
        green=tuple(counts[BINS : BINS * 2]),
        blue=tuple(counts[BINS * 2 : BINS * 3]),
        luma=luma,
    )
