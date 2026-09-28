"""フィルターの前後にかける効果（明るさ・色温度・彩度・周辺減光・経年劣化）。"""

from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageEnhance

from image_editor.core.filters import add_grain

VIGNETTE_MIN = 0
VIGNETTE_MAX = 100
# 強さ 100 のとき、四隅の明るさを何割落とすか
VIGNETTE_MAX_DARKEN = 0.8
# 中心からの距離（0 = 中心、1 = 上下左右の端、√2 = 四隅）がこれより内側は暗くしない。
# ここから四隅に向かって滑らかに暗くなり、四隅で最大になる
VIGNETTE_START = 0.35
_CORNER = math.sqrt(2)
# Image.radial_gradient は四隅が 255 になるよう正規化されている（端の中央は 255/√2）
_GRADIENT_EDGE = 255 / _CORNER

# 経年劣化（強さ 100 のときの値。強さに比例して効かせる）
AGING_MIN = 0
AGING_MAX = 100
AGING_MAX_DESATURATE = 0.6  # 彩度を何割落とすか（退色）
AGING_MAX_BLACK = 45  # 黒をどこまで浮かせるか（フェード）
AGING_MAX_WHITE_DROP = 25  # 白をどれだけ抑えるか（フェード）
AGING_MAX_TINT = (1.08, 1.0, 0.72)  # R, G, B に掛ける係数（黄ばみ・青の抜け）
AGING_MAX_GRAIN = 14  # 粒子の強さ（明るさの最大変化量）
AGING_GRAIN_SEED = 19700101  # 粒子の模様を毎回同じにするための乱数シード

# 色温度（ケルビン）。指定した色温度の光で照らしたような色にする
TEMPERATURE_MIN = 2000  # ろうそく・電球色（暖色）
TEMPERATURE_MAX = 10000  # 曇り空・日陰（青み）
TEMPERATURE_NEUTRAL = 6500  # 昼光。この値では変化なし
TEMPERATURE_STEP = 100
TEMPERATURE_STRENGTH = 0.5  # 黒体放射の色の差をどれだけ反映するか（1 = そのまま）
_LUMA = (0.299, 0.587, 0.114)

# 彩度（-100 = 白黒、0 = 変化なし、+100 = 鮮やかさ 2 倍）
SATURATION_MIN = -100
SATURATION_MAX = 100

# 明るさ（-100〜+100、0 = 変化なし）。中間の明るさをガンマで持ち上げ・押し下げ、黒と白は保つ
BRIGHTNESS_MIN = -100
BRIGHTNESS_MAX = 100
BRIGHTNESS_GAMMA_BASE = 2.0  # ガンマ = BASE ** (-値 / 50)。+100 で 0.25、-100 で 4


def vignette(image: Image.Image, amount: int) -> Image.Image:
    """画像の中心を基準に、周辺を楕円状に暗くした新しい画像を返す（入力画像は変更しない）。

    amount は 0〜100（0 は変化なし）。RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("周辺減光", amount, VIGNETTE_MIN, VIGNETTE_MAX)
    if amount == 0:
        return image.copy()

    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB")

    # 中心からの距離の放射状グラデーションを画像の大きさに引き伸ばす（縦横比に合わせて楕円になる）
    distance = Image.radial_gradient("L").resize(rgb.size, Image.Resampling.BILINEAR)
    strength = VIGNETTE_MAX_DARKEN * amount / VIGNETTE_MAX
    multiplier = distance.point([_brightness(v / _GRADIENT_EDGE, strength) for v in range(256)])
    result = ImageChops.multiply(rgb, Image.merge("RGB", (multiplier,) * 3))

    if alpha is not None:
        result.putalpha(alpha)
    return result


def _brightness(distance: float, strength: float) -> int:
    """中心からの距離（端 = 1）に対する明るさの倍率 (0〜255 = 0〜1 倍)。滑らかに暗くなる。"""
    t = min(max((distance - VIGNETTE_START) / (_CORNER - VIGNETTE_START), 0.0), 1.0)
    smooth = t * t * (3 - 2 * t)
    return round(255 * (1 - strength * smooth))


def aging(image: Image.Image, amount: int) -> Image.Image:
    """時間が経ったような風合いにした新しい画像を返す（入力画像は変更しない）。

    amount は 0〜100（0 は変化なし）。大きいほど、退色（彩度が下がる）・フェード（黒が浮き
    白が抑えられる）・黄ばみと青の抜け・粒子が強くなる。粒子の模様は固定で、同じ入力なら
    毎回同じ結果になる。RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("経年劣化", amount, AGING_MIN, AGING_MAX)
    if amount == 0:
        return image.copy()

    t = amount / AGING_MAX
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = ImageEnhance.Color(image.convert("RGB")).enhance(1 - AGING_MAX_DESATURATE * t)

    # フェードと色かぶりを 1 回の LUT でかける
    black = AGING_MAX_BLACK * t
    white = 255 - AGING_MAX_WHITE_DROP * t
    faded = [black + v * (white - black) / 255 for v in range(256)]
    tints = [1 + (factor - 1) * t for factor in AGING_MAX_TINT]
    rgb = rgb.point(_clip_table([value * tint for tint in tints for value in faded]))

    grain = round(AGING_MAX_GRAIN * t)
    if grain:
        rgb = add_grain(rgb, grain, AGING_GRAIN_SEED)

    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def _check_amount(name: str, amount: int, minimum: int, maximum: int) -> None:
    if not minimum <= amount <= maximum:
        raise ValueError(f"{name}は {minimum}〜{maximum} で指定してください: {amount}")


def _clip_table(values: list[float]) -> list[int]:
    """四捨五入して 0〜255 にクリップしたルックアップテーブルを返す。"""
    return [min(255, max(0, int(v + 0.5))) for v in values]


def color_temperature(image: Image.Image, kelvin: int) -> Image.Image:
    """指定した色温度の光で照らしたような色にした新しい画像を返す（入力画像は変更しない）。

    kelvin は 2000〜10000。6500 は変化なし、低いほど暖色、高いほど青みになる。
    明るさはほぼ保つ。RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("色温度", kelvin, TEMPERATURE_MIN, TEMPERATURE_MAX)
    if kelvin == TEMPERATURE_NEUTRAL:
        return image.copy()

    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    tables: list[float] = []
    for multiplier in temperature_multipliers(kelvin):
        tables += [v * multiplier for v in range(256)]
    rgb = image.convert("RGB").point(_clip_table(tables))

    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def temperature_multipliers(kelvin: int) -> tuple[float, float, float]:
    """色温度に対する R / G / B の倍率を返す（6500K で 1、明るさ (輝度) は 1 に正規化）。"""
    reference = kelvin_to_rgb(TEMPERATURE_NEUTRAL)
    color = kelvin_to_rgb(kelvin)
    raw = [1 + (c / r - 1) * TEMPERATURE_STRENGTH for c, r in zip(color, reference, strict=True)]
    luma = sum(weight * m for weight, m in zip(_LUMA, raw, strict=True))
    red, green, blue = (m / luma for m in raw)
    return red, green, blue


def kelvin_to_rgb(kelvin: float) -> tuple[float, float, float]:
    """黒体放射の色温度に対応する RGB (0〜255) の近似値を返す（Tanner Helland の近似式）。"""
    t = kelvin / 100
    if t <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        red = 329.698727446 * (t - 60) ** -0.1332047592
        green = 288.1221695283 * (t - 60) ** -0.0755148492
    if t >= 66:
        blue = 255.0
    elif t <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(t - 10) - 305.0447927307

    def clip(value: float) -> float:
        return min(255.0, max(1.0, value))  # 0 だと倍率計算で割れないので下限は 1

    return clip(red), clip(green), clip(blue)


def saturation(image: Image.Image, amount: int) -> Image.Image:
    """彩度（色の鮮やかさ）を変えた新しい画像を返す（入力画像は変更しない）。

    amount は -100〜+100。-100 で白黒、0 で変化なし、+100 で鮮やかさ 2 倍。
    RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("彩度", amount, SATURATION_MIN, SATURATION_MAX)
    if amount == 0:
        return image.copy()

    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = ImageEnhance.Color(image.convert("RGB")).enhance(1 + amount / SATURATION_MAX)
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def brightness(image: Image.Image, amount: int) -> Image.Image:
    """明るさを変えた新しい画像を返す（入力画像は変更しない）。

    amount は -100〜+100（0 は変化なし）。プラスで明るく、マイナスで暗くする。中間の明るさを
    トーンカーブ（ガンマ）で動かすので、黒 (0) と白 (255) は変わらず、白飛び・黒つぶれしにくい。
    RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("明るさ", amount, BRIGHTNESS_MIN, BRIGHTNESS_MAX)
    if amount == 0:
        return image.copy()

    gamma = BRIGHTNESS_GAMMA_BASE ** (-amount / 50)
    curve = _clip_table([255 * (v / 255) ** gamma for v in range(256)])
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB").point(curve * 3)
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb
