"""フィルターの後にかける効果（周辺減光）。"""

from __future__ import annotations

import math

from PIL import Image, ImageChops

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


def vignette(image: Image.Image, amount: int) -> Image.Image:
    """画像の中心を基準に、周辺を楕円状に暗くした新しい画像を返す（入力画像は変更しない）。

    amount は 0〜100（0 は変化なし）。RGB にのみ適用し、アルファは元のまま戻す。
    """
    if not VIGNETTE_MIN <= amount <= VIGNETTE_MAX:
        raise ValueError(f"周辺減光は {VIGNETTE_MIN}〜{VIGNETTE_MAX} で指定してください: {amount}")
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
