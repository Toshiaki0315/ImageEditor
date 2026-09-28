"""フィルターの後にかける効果（周辺減光・経年劣化）。"""

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
