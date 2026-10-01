"""フィルター（PIL.Image -> PIL.Image の純粋関数）。"""

from __future__ import annotations

import random
from collections.abc import Callable
from enum import Enum

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

from image_editor.core.io import normalize_mode
from image_editor.core.parallel import filter_image

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

# トーン系の加工（トーンカーブ + 色味の係数 (R, G, B) + 彩度）
# ハイキー: 明るく軽やか。中間〜暗部を大きく持ち上げ、黒も少し浮かせてコントラストを弱める
HIGH_KEY_GAMMA = 0.6  # 出力 = 黒の浮き + (1 - 黒の浮き) × 入力^ガンマ
HIGH_KEY_BLACK = 20
HIGH_KEY_SATURATION = 0.85
# ローキー: 暗く重厚。中間〜暗部を沈め、明部は残す
LOW_KEY_GAMMA = 1.8
LOW_KEY_SATURATION = 0.9
# ドラマチック: 強い S 字カーブで明暗を強調し、彩度を落として全体をやや締める
DRAMATIC_CURVE = 0.7  # 2 重の S 字カーブを混ぜる割合
DRAMATIC_GAIN = 0.95
DRAMATIC_SATURATION = 0.45  # S 字カーブで色の差も広がるので、先に強めに下げておく
# モダン: 黒を少し浮かせたマット調、やや寒色で彩度控えめ
MODERN_CURVE = 0.3
MODERN_BLACK = 18
MODERN_WHITE = 245
MODERN_TINT = (0.97, 1.0, 1.05)
MODERN_SATURATION = 0.85
# ナチュラル: 彩度と明暗差をわずかに上げ、ほんのり暖色
NATURAL_CURVE = 0.15
NATURAL_TINT = (1.02, 1.0, 0.98)
NATURAL_SATURATION = 1.12

# シネマティック: 暗部を青緑、明部をオレンジに寄せる（ティール＆オレンジ）
CINEMATIC_CURVE = 0.3
CINEMATIC_SPLIT = 0.10  # 明部は R を上げ B を下げ、暗部はその逆
CINEMATIC_SHADOW_GREEN = 0.04  # 暗部に足す緑（青緑にする）
CINEMATIC_SATURATION = 0.9
# ノワール: コントラストの強い白黒。黒を深く、硬く
NOIR_CURVE = 0.9  # 2 重の S 字カーブを混ぜる割合
NOIR_GAMMA = 1.25  # 黒を深くする
# ブリーチバイパス: 色を大きく抜いて明暗を強くし、粒子でざらっとさせる
BLEACH_SATURATION = 0.25  # S 字カーブで色の差も広がるので、先に強めに下げておく
BLEACH_CURVE = 0.8
BLEACH_GRAIN = 8
BLEACH_GRAIN_SEED = 19440606
# パステル: 黒を大きく浮かせて淡く明るく、色を柔らかく
PASTEL_BLACK = 70
PASTEL_GAMMA = 0.8
PASTEL_TINT = (1.02, 0.99, 1.03)
PASTEL_SATURATION = 0.7
# クロスプロセス: R は強い S 字、G は持ち上げ、B は狭い範囲に圧縮（暗部を青紫、明部を黄緑に）
CROSS_RED_CURVE = 0.8
CROSS_GREEN_GAMMA = 0.85
CROSS_BLUE_RANGE = (0.2, 0.75)
CROSS_SATURATION = 1.15
# 青写真（サイアノタイプ）: 明るさを濃紺〜淡い水色のグラデーションで表す
CYANOTYPE_DARK = (10, 35, 80)
CYANOTYPE_LIGHT = (220, 236, 248)
# 夏らしい: 明るく、青と緑を爽やかに
SUMMER_GAMMA = 0.85
SUMMER_TINT = (0.97, 1.03, 1.07)
SUMMER_SATURATION = 1.25
# 秋らしい: 暖かく落ち着いた色
AUTUMN_CURVE = 0.2
AUTUMN_GAMMA = 1.05
AUTUMN_TINT = (1.08, 0.99, 0.82)
AUTUMN_SATURATION = 1.05
# ソフトフォーカス: 明るい部分をにじませ、全体をわずかにぼかす
# ぼかしの半径（短辺に対する比率。縮小プレビューと原寸で見た目をそろえる）
SOFT_RADIUS_RATIO = 0.015
SOFT_GLOW_THRESHOLD = 0.55  # これより明るい部分をにじませる
SOFT_GLOW_STRENGTH = 0.7
SOFT_BLUR_MIX = 0.25
# HDR 風: 大きな半径のアンシャープマスクで細部の明暗を強調し、暗部を持ち上げる
HDR_RADIUS_RATIO = 0.02  # 短辺に対する比率
HDR_DETAIL_PERCENT = 90
HDR_GAMMA = 0.85
HDR_SATURATION = 1.15
# 赤外線風: 緑を明るく青を暗くした明るさに、R と B を入れ替えた色を少し混ぜる
INFRARED_WEIGHTS = (-0.2, 1.5, -0.9, 0.0)  # 明るさ = R, G, B の重み付き和（0〜255 に収める）
INFRARED_GAMMA = 0.6  # 草木をより白く光らせる
INFRARED_COLOR_MIX = 0.3


class FilterType(Enum):
    """加工の種類。"""

    NONE = "none"
    SEPIA = "sepia"
    MONOTONE = "monotone"
    HIGH_TONE = "high_tone"
    POLAROID = "polaroid"
    POSITIVE_FILM = "positive_film"
    RETRO_CAMERA = "retro_camera"
    HIGH_KEY = "high_key"
    LOW_KEY = "low_key"
    DRAMATIC = "dramatic"
    MODERN = "modern"
    NATURAL = "natural"
    CINEMATIC = "cinematic"
    NOIR = "noir"
    BLEACH_BYPASS = "bleach_bypass"
    PASTEL = "pastel"
    CROSS_PROCESS = "cross_process"
    CYANOTYPE = "cyanotype"
    SUMMER = "summer"
    AUTUMN = "autumn"
    SOFT_FOCUS = "soft_focus"
    HDR = "hdr"
    INFRARED = "infrared"

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
    FilterType.HIGH_KEY: "ハイキー",
    FilterType.LOW_KEY: "ローキー",
    FilterType.DRAMATIC: "ドラマチック",
    FilterType.MODERN: "モダン",
    FilterType.NATURAL: "ナチュラル",
    FilterType.CINEMATIC: "シネマティック",
    FilterType.NOIR: "ノワール",
    FilterType.BLEACH_BYPASS: "ブリーチバイパス",
    FilterType.PASTEL: "パステル",
    FilterType.CROSS_PROCESS: "クロスプロセス",
    FilterType.CYANOTYPE: "青写真",
    FilterType.SUMMER: "夏らしい",
    FilterType.AUTUMN: "秋らしい",
    FilterType.SOFT_FOCUS: "ソフトフォーカス",
    FilterType.HDR: "HDR 風",
    FilterType.INFRARED: "赤外線風",
}


def apply_filter(image: Image.Image, filter_type: FilterType) -> Image.Image:
    """画像にフィルターを適用した新しい画像を返す（入力画像は変更しない）。

    RGB に対してのみ処理し、アルファチャンネルは元のまま戻す。フィルターは色だけを変え、
    大きさは変えない（フレームは core.frames で付ける）。
    """
    image = normalize_mode(image)
    if filter_type is FilterType.NONE:
        return image.copy()

    rgb, alpha = _split_alpha(image)
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


def polaroid_tone(image: Image.Image) -> Image.Image:
    """RGB 画像にポラロイド風の色補正（コントラスト弱め・黄み）を行う。"""
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


def high_key(image: Image.Image) -> Image.Image:
    """RGB 画像をハイキー（明るく軽やか、コントラスト弱め）にする。"""
    black = HIGH_KEY_BLACK / 255
    return _tone(
        image,
        lambda x: black + (1 - black) * x**HIGH_KEY_GAMMA,
        saturation=HIGH_KEY_SATURATION,
    )


def low_key(image: Image.Image) -> Image.Image:
    """RGB 画像をローキー（暗く重厚、明部は残す）にする。"""
    return _tone(image, lambda x: x**LOW_KEY_GAMMA, saturation=LOW_KEY_SATURATION)


def dramatic(image: Image.Image) -> Image.Image:
    """RGB 画像をドラマチック（強い明暗、彩度控えめ）にする。"""

    def curve(x: float) -> float:
        once = _smoothstep(x)
        twice = _smoothstep(once)
        return ((1 - DRAMATIC_CURVE) * once + DRAMATIC_CURVE * twice) * DRAMATIC_GAIN

    return _tone(image, curve, saturation=DRAMATIC_SATURATION)


def modern(image: Image.Image) -> Image.Image:
    """RGB 画像をモダン（黒の浮いたマット調、やや寒色、彩度控えめ）にする。"""
    black, white = MODERN_BLACK / 255, MODERN_WHITE / 255

    def curve(x: float) -> float:
        s_curve = (1 - MODERN_CURVE) * x + MODERN_CURVE * _smoothstep(x)
        return black + (white - black) * s_curve

    return _tone(image, curve, MODERN_TINT, MODERN_SATURATION)


def natural(image: Image.Image) -> Image.Image:
    """RGB 画像をナチュラル（彩度と明暗差をわずかに上げ、ほんのり暖色）にする。"""
    return _tone(
        image,
        lambda x: (1 - NATURAL_CURVE) * x + NATURAL_CURVE * _smoothstep(x),
        NATURAL_TINT,
        NATURAL_SATURATION,
    )


def cinematic(image: Image.Image) -> Image.Image:
    """RGB 画像をシネマティック（暗部を青緑、明部をオレンジに寄せる）にする。"""

    def s_curve(x: float) -> float:
        return (1 - CINEMATIC_CURVE) * x + CINEMATIC_CURVE * _smoothstep(x)

    return _channel_curves(
        image,
        (
            lambda x: s_curve(x) + CINEMATIC_SPLIT * (2 * x - 1),
            lambda x: s_curve(x) + CINEMATIC_SHADOW_GREEN * (1 - x) ** 2,
            lambda x: s_curve(x) - CINEMATIC_SPLIT * (2 * x - 1),
        ),
        CINEMATIC_SATURATION,
    )


def noir(image: Image.Image) -> Image.Image:
    """RGB 画像をノワール（コントラストの強い白黒、深い黒）にする。"""

    def curve(x: float) -> float:
        once = _smoothstep(x)
        return ((1 - NOIR_CURVE) * once + NOIR_CURVE * _smoothstep(once)) ** NOIR_GAMMA

    gray = ImageOps.grayscale(image).point(_clip_table([curve(v / 255) * 255 for v in range(256)]))
    return gray.convert("RGB")


def bleach_bypass(image: Image.Image) -> Image.Image:
    """RGB 画像をブリーチバイパス（色を抜いて明暗を強く、ざらっと）にする。"""
    toned = _tone(
        image,
        lambda x: (1 - BLEACH_CURVE) * x + BLEACH_CURVE * _smoothstep(x),
        saturation=BLEACH_SATURATION,
    )
    return add_grain(toned, BLEACH_GRAIN, BLEACH_GRAIN_SEED)


def pastel(image: Image.Image) -> Image.Image:
    """RGB 画像をパステル（淡く明るく、色を柔らかく）にする。"""
    black = PASTEL_BLACK / 255
    return _tone(
        image,
        lambda x: black + (1 - black) * x**PASTEL_GAMMA,
        PASTEL_TINT,
        PASTEL_SATURATION,
    )


def cross_process(image: Image.Image) -> Image.Image:
    """RGB 画像をクロスプロセス（暗部を青紫、明部を黄緑に偏らせた派手な色）にする。"""
    low, high = CROSS_BLUE_RANGE
    return _channel_curves(
        image,
        (
            lambda x: (1 - CROSS_RED_CURVE) * x + CROSS_RED_CURVE * _smoothstep(x),
            lambda x: x**CROSS_GREEN_GAMMA,
            lambda x: low + (high - low) * x,
        ),
        CROSS_SATURATION,
    )


def cyanotype(image: Image.Image) -> Image.Image:
    """RGB 画像を青写真（明るさを濃紺〜淡い水色で表す）にする。"""
    return ImageOps.colorize(ImageOps.grayscale(image), CYANOTYPE_DARK, CYANOTYPE_LIGHT)


def summer(image: Image.Image) -> Image.Image:
    """RGB 画像を夏らしく（明るく、青と緑を爽やかに）する。"""
    return _tone(image, lambda x: x**SUMMER_GAMMA, SUMMER_TINT, SUMMER_SATURATION)


def autumn(image: Image.Image) -> Image.Image:
    """RGB 画像を秋らしく（暖かく落ち着いた色に）する。"""
    return _tone(
        image,
        lambda x: ((1 - AUTUMN_CURVE) * x + AUTUMN_CURVE * _smoothstep(x)) ** AUTUMN_GAMMA,
        AUTUMN_TINT,
        AUTUMN_SATURATION,
    )


def soft_focus(image: Image.Image) -> Image.Image:
    """RGB 画像をソフトフォーカス（明るい部分がにじみ、光があふれたような柔らかさ）にする。

    ぼかしの大きさは短辺に比例させるので、縮小プレビューと原寸で見た目がそろう。
    """
    blurred = filter_image(image, ImageFilter.GaussianBlur(_radius(image, SOFT_RADIUS_RATIO)))
    threshold = SOFT_GLOW_THRESHOLD
    glow_curve = [
        max(0.0, (v / 255 - threshold) / (1 - threshold)) * 255 * SOFT_GLOW_STRENGTH
        for v in range(256)
    ]
    glow = blurred.point(_clip_table(glow_curve) * 3)
    return ImageChops.screen(Image.blend(image, blurred, SOFT_BLUR_MIX), glow)


def hdr(image: Image.Image) -> Image.Image:
    """RGB 画像を HDR 風（暗部と明部の細部を強調し、くっきり）にする。

    大きな半径のアンシャープマスクで部分ごとの明暗差を強め、暗部を持ち上げる。
    半径は短辺に比例させるので、縮小プレビューと原寸で見た目がそろう。
    """
    detailed = filter_image(
        image,
        ImageFilter.UnsharpMask(
            radius=_radius(image, HDR_RADIUS_RATIO), percent=HDR_DETAIL_PERCENT, threshold=0
        ),
    )
    return _tone(detailed, lambda x: x**HDR_GAMMA, saturation=HDR_SATURATION)


def infrared(image: Image.Image) -> Image.Image:
    """RGB 画像を赤外線風（緑の草木が白く光り、空が暗い、非現実的な色）にする。"""
    brightness = image.convert("L", INFRARED_WEIGHTS)
    brightness = brightness.point(
        _clip_table([(v / 255) ** INFRARED_GAMMA * 255 for v in range(256)])
    )
    red, green, blue = image.split()
    swapped = Image.merge("RGB", (blue, green, red))  # R と B を入れ替えた非現実的な色
    return Image.blend(Image.merge("RGB", (brightness,) * 3), swapped, INFRARED_COLOR_MIX)


def _radius(image: Image.Image, ratio: float) -> float:
    return max(1.0, min(image.size) * ratio)


def _channel_curves(
    image: Image.Image,
    curves: tuple[Callable[[float], float], Callable[[float], float], Callable[[float], float]],
    saturation: float = 1.0,
) -> Image.Image:
    """彩度を変えてから、R / G / B それぞれのトーンカーブ (0〜1 → 0〜1) を 1 回の LUT でかける。"""
    if saturation != 1.0:
        image = ImageEnhance.Color(image).enhance(saturation)
    table = [curve(v / 255) * 255 for curve in curves for v in range(256)]
    return image.point(_clip_table(table))


def _tone(
    image: Image.Image,
    curve: Callable[[float], float],
    tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
    saturation: float = 1.0,
) -> Image.Image:
    """彩度を変えてから、トーンカーブ (0〜1 → 0〜1) と色味の係数を 1 回の LUT でかける。"""
    if saturation != 1.0:
        image = ImageEnhance.Color(image).enhance(saturation)
    levels = [curve(v / 255) * 255 for v in range(256)]
    return image.point(_clip_table([level * factor for factor in tint for level in levels]))


def _smoothstep(x: float) -> float:
    return x * x * (3 - 2 * x)


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
    FilterType.POLAROID: polaroid_tone,
    FilterType.POSITIVE_FILM: positive_film,
    FilterType.RETRO_CAMERA: retro_camera,
    FilterType.HIGH_KEY: high_key,
    FilterType.LOW_KEY: low_key,
    FilterType.DRAMATIC: dramatic,
    FilterType.MODERN: modern,
    FilterType.NATURAL: natural,
    FilterType.CINEMATIC: cinematic,
    FilterType.NOIR: noir,
    FilterType.BLEACH_BYPASS: bleach_bypass,
    FilterType.PASTEL: pastel,
    FilterType.CROSS_PROCESS: cross_process,
    FilterType.CYANOTYPE: cyanotype,
    FilterType.SUMMER: summer,
    FilterType.AUTUMN: autumn,
    FilterType.SOFT_FOCUS: soft_focus,
    FilterType.HDR: hdr,
    FilterType.INFRARED: infrared,
}
