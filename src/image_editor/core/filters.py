"""フィルター（PIL.Image -> PIL.Image の純粋関数）。"""

from __future__ import annotations

import random
from collections.abc import Callable
from enum import Enum

from PIL import Image, ImageChops, ImageEnhance, ImageOps

from image_editor.core.io import normalize_mode

# --- 係数（初版の目安値。requirements.md §5.4） ------------------------------

# セピア: グレースケール値 L に掛ける係数 (R, G, B)
SEPIA_FACTORS = (1.07, 0.74, 0.43)

# ハイトーン
HIGH_TONE_BRIGHTNESS = 1.2
HIGH_TONE_CONTRAST = 1.3

# ポラロイド風
POLAROID_CONTRAST = 0.9
POLAROID_RED_FACTOR = 1.05
POLAROID_BLUE_FACTOR = 0.90
POLAROID_BORDER_RATIO = 0.05  # 上・左・右の白枠（短辺に対する比率）
POLAROID_BOTTOM_RATIO = 0.20  # 下の白枠（短辺に対する比率）
POLAROID_BORDER_COLOR = (255, 255, 255)

# ポジフィルム風（リバーサルフィルムのような鮮やかな発色）
POSITIVE_SATURATION = 1.35
POSITIVE_CURVE = 0.5  # S 字カーブの強さ（0 = 直線、1 = smoothstep）
POSITIVE_HIGHLIGHT_WARM = 6  # 明部の赤を足す量（最大値）
POSITIVE_SHADOW_COOL = 10  # 暗部の青を足す量（最大値）

# レトロカメラ風（色あせたプリントのような発色 + フィルムの粒子）
RETRO_SATURATION = 0.8
RETRO_BLACK = 28  # 黒の浮き（出力の最小値）
RETRO_WHITE = 232  # 白の抑え（出力の最大値）
RETRO_TINT = (1.04, 1.0, 0.88)  # 暖色寄りにする係数 (R, G, B)
RETRO_GRAIN = 10  # 粒子の強さ（明るさの最大変化量）
RETRO_GRAIN_SEED = 20260928  # 粒子の模様を毎回同じにするための乱数シード


class FilterType(Enum):
    """加工の種類。"""

    NONE = "none"
    SEPIA = "sepia"
    MONOTONE = "monotone"
    HIGH_TONE = "high_tone"
    POLAROID = "polaroid"
    POSITIVE_FILM = "positive_film"
    RETRO_CAMERA = "retro_camera"

    @property
    def label(self) -> str:
        """UI に表示する日本語名。"""
        return _LABELS[self]


_LABELS: dict[FilterType, str] = {
    FilterType.NONE: "なし",
    FilterType.SEPIA: "セピア",
    FilterType.MONOTONE: "モノトーン",
    FilterType.HIGH_TONE: "ハイトーン",
    FilterType.POLAROID: "ポラロイド風",
    FilterType.POSITIVE_FILM: "ポジフィルム風",
    FilterType.RETRO_CAMERA: "レトロカメラ風",
}


def apply_filter(
    image: Image.Image, filter_type: FilterType, with_border: bool = True
) -> Image.Image:
    """画像にフィルターを適用した新しい画像を返す（入力画像は変更しない）。

    RGB に対してのみ処理し、アルファチャンネルは元のまま戻す。
    with_border=False ならポラロイドの白枠を付けず、色補正だけを行う（プレビュー用）。
    """
    image = normalize_mode(image)
    if filter_type is FilterType.NONE:
        return image.copy()

    rgb, alpha = _split_alpha(image)
    if filter_type is FilterType.POLAROID and with_border:
        return polaroid(rgb, alpha)

    filtered = _RGB_FILTERS[filter_type](rgb)
    if alpha is not None:
        filtered.putalpha(alpha)
    return filtered


def sepia(image: Image.Image) -> Image.Image:
    """RGB 画像をセピア調にする。"""
    gray = ImageOps.grayscale(image)
    channels = [gray.point(_scale_table(factor)) for factor in SEPIA_FACTORS]
    return Image.merge("RGB", channels)


def monotone(image: Image.Image) -> Image.Image:
    """RGB 画像をグレースケールにし、RGB に戻して返す。"""
    return ImageOps.grayscale(image).convert("RGB")


def high_tone(image: Image.Image) -> Image.Image:
    """RGB 画像を明るく・コントラスト強めにする。"""
    brightened = ImageEnhance.Brightness(image).enhance(HIGH_TONE_BRIGHTNESS)
    return ImageEnhance.Contrast(brightened).enhance(HIGH_TONE_CONTRAST)


def polaroid(image: Image.Image, alpha: Image.Image | None = None) -> Image.Image:
    """RGB 画像をポラロイド風に色補正し、白枠を付けて返す。

    alpha を渡すと RGBA で返す（白枠部分は不透明）。
    """
    toned = polaroid_tone(image)
    if alpha is not None:
        toned.putalpha(alpha)
    return polaroid_frame(toned)


def polaroid_frame(image: Image.Image) -> Image.Image:
    """RGB / RGBA 画像の周囲にポラロイドの白枠を付けた新しい画像を返す（白枠部分は不透明）。"""
    border, bottom = polaroid_border_sizes(image.size)
    width, height = image.size
    canvas_size = (width + border * 2, height + border + bottom)

    framed = Image.new("RGB", canvas_size, POLAROID_BORDER_COLOR)
    framed.paste(image.convert("RGB"), (border, border))
    if image.mode == "RGBA":
        framed_alpha = Image.new("L", canvas_size, 255)
        framed_alpha.paste(image.getchannel("A"), (border, border))
        framed.putalpha(framed_alpha)
    return framed


def polaroid_tone(image: Image.Image) -> Image.Image:
    """RGB 画像にポラロイド風の色補正（コントラスト弱め・黄み）だけを行う。白枠は付けない。"""
    toned = ImageEnhance.Contrast(image).enhance(POLAROID_CONTRAST)
    red, green, blue = toned.split()
    return Image.merge(
        "RGB",
        (
            red.point(_scale_table(POLAROID_RED_FACTOR)),
            green,
            blue.point(_scale_table(POLAROID_BLUE_FACTOR)),
        ),
    )


def positive_film(image: Image.Image) -> Image.Image:
    """RGB 画像をポジフィルム風にする（彩度を上げ、S 字カーブで締め、暗部を青く・明部を暖色に）。"""
    saturated = ImageEnhance.Color(image).enhance(POSITIVE_SATURATION)

    def curve(v: int) -> float:
        x = v / 255
        return (1 - POSITIVE_CURVE) * x + POSITIVE_CURVE * (3 * x * x - 2 * x * x * x)

    red = [curve(v) * 255 + POSITIVE_HIGHLIGHT_WARM * (v / 255) ** 2 for v in range(256)]
    green = [curve(v) * 255 for v in range(256)]
    blue = [curve(v) * 255 + POSITIVE_SHADOW_COOL * (1 - v / 255) ** 2 for v in range(256)]
    return saturated.point(_clip_table(red + green + blue))


def retro_camera(image: Image.Image) -> Image.Image:
    """RGB 画像をレトロカメラ風にする（黒を浮かせて白を抑え、暖色寄り・彩度控えめ・粒子あり）。"""
    muted = ImageEnhance.Color(image).enhance(RETRO_SATURATION)
    tables: list[float] = []
    for factor in RETRO_TINT:
        tables += [
            (RETRO_BLACK + v * (RETRO_WHITE - RETRO_BLACK) / 255) * factor for v in range(256)
        ]
    return add_grain(muted.point(_clip_table(tables)), RETRO_GRAIN, RETRO_GRAIN_SEED)


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


def polaroid_border_sizes(size: tuple[int, int]) -> tuple[int, int]:
    """ポラロイドの白枠の太さ (上・左・右, 下) を返す。四捨五入、最小 1px。"""
    short_side = min(size)
    return (
        max(1, int(short_side * POLAROID_BORDER_RATIO + 0.5)),
        max(1, int(short_side * POLAROID_BOTTOM_RATIO + 0.5)),
    )


def output_size(size: tuple[int, int], filter_type: FilterType) -> tuple[int, int]:
    """フィルター適用後の出力サイズを返す（ポラロイドのみ白枠の分だけ大きくなる）。"""
    if filter_type is not FilterType.POLAROID:
        return size
    border, bottom = polaroid_border_sizes(size)
    return (size[0] + border * 2, size[1] + border + bottom)


def _split_alpha(image: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    if image.mode == "RGBA":
        return image.convert("RGB"), image.getchannel("A")
    return image, None


def _clip_table(values: list[float]) -> list[int]:
    """四捨五入して 0〜255 にクリップしたルックアップテーブルを返す。"""
    return [min(255, max(0, int(v + 0.5))) for v in values]


def _scale_table(factor: float) -> list[int]:
    """各値に factor を掛けて 0〜255 にクリップするルックアップテーブル。"""
    return [min(255, int(v * factor + 0.5)) for v in range(256)]


_RGB_FILTERS: dict[FilterType, Callable[[Image.Image], Image.Image]] = {
    FilterType.SEPIA: sepia,
    FilterType.MONOTONE: monotone,
    FilterType.HIGH_TONE: high_tone,
    FilterType.POLAROID: polaroid_tone,  # 白枠なし（with_border=False のとき）
    FilterType.POSITIVE_FILM: positive_film,
    FilterType.RETRO_CAMERA: retro_camera,
}
