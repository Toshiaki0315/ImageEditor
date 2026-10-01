"""フィルターの前後にかける効果（露出・明るさ・コントラスト・色温度・彩度・ディテール・周辺減光・
経年劣化）。"""

from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

from image_editor.core.filters import add_grain
from image_editor.core.parallel import filter_image

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

# コントラスト（-100〜+100、0 = 変化なし）
CONTRAST_MIN = -100
CONTRAST_MAX = 100
CONTRAST_MIN_SLOPE = 0.5  # -100 のとき、中間の灰色からの差をこの倍率に縮める

# 露出（EV = 段。+1.0 で光の量 2 倍、-1.0 で半分）
EXPOSURE_MIN = -5.0
EXPOSURE_MAX = 5.0
EXPOSURE_STEP = 0.1

# ディテール（シャープ・ぼかし・ノイズ除去）。半径は短辺に比例させ、縮小プレビューと原寸で
# 効き方をそろえる
DETAIL_MIN = 0
DETAIL_MAX = 100
SHARPEN_RADIUS_RATIO = 0.0012  # アンシャープマスクの半径（短辺に対する比率）
# 半径の下限（px）。小さい画像でも効くようにする。大きい画像の縮小プレビュー（短辺 1200px 程度）
# では比率の半径がこれを上回るので、プレビューと原寸の効き方の比例は崩れない
SHARPEN_MIN_RADIUS = 1.0
SHARPEN_MAX_PERCENT = 250  # 100 のときの強さ (%)
SHARPEN_THRESHOLD = 2  # これより小さい明暗差は強調しない（ざらつきを抑える）
BLUR_MAX_RADIUS_RATIO = 0.01  # 100 のときのガウスぼかしの半径（短辺に対する比率）
DENOISE_RADIUS_RATIO = 0.002  # なめらかにするぼかしの半径（短辺に対する比率）
DENOISE_EDGE_THRESHOLD = 40  # ぼかしとの差がこれ以上の部分は輪郭とみなして残す


def sharpen(
    image: Image.Image,
    amount: int,
    reference: float | None = None,
    output: float | None = None,
) -> Image.Image:
    """輪郭をくっきりさせた新しい画像を返す（入力画像は変更しない）。

    amount は 0〜100（0 は変化なし）。アンシャープマスクの半径は短辺に比例させる
    （reference を渡すと、画像の短辺の代わりにその長さを基準にする）。
    output は保存する写真の短辺。縮小プレビューで渡すと、保存時の半径（下限込み）を
    reference / output 倍に換算して、保存結果と同じ効き方にする。
    RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("シャープ", amount, DETAIL_MIN, DETAIL_MAX)
    if amount == 0:
        return image.copy()
    rgb, alpha = _split_rgb(image)
    mask = ImageFilter.UnsharpMask(
        radius=_sharpen_radius(min(rgb.size) if reference is None else reference, output),
        percent=round(SHARPEN_MAX_PERCENT * amount / DETAIL_MAX),
        threshold=SHARPEN_THRESHOLD,
    )
    return _merge_alpha(filter_image(rgb, mask), alpha)


def blur(image: Image.Image, amount: int, reference: float | None = None) -> Image.Image:
    """全体をぼかした新しい画像を返す（入力画像は変更しない）。

    amount は 0〜100（0 は変化なし）。ガウスぼかしの半径は短辺に比例させる（100 で短辺の 1%。
    reference を渡すと、画像の短辺の代わりにその長さを基準にする）。
    RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("ぼかし", amount, DETAIL_MIN, DETAIL_MAX)
    if amount == 0:
        return image.copy()
    rgb, alpha = _split_rgb(image)
    radius = _detail_radius(rgb, BLUR_MAX_RADIUS_RATIO * amount / DETAIL_MAX, reference)
    return _merge_alpha(filter_image(rgb, ImageFilter.GaussianBlur(radius)), alpha)


def denoise(image: Image.Image, amount: int, reference: float | None = None) -> Image.Image:
    """輪郭を残してざらつきをなめらかにした新しい画像を返す（入力画像は変更しない）。

    amount は 0〜100（0 は変化なし）。ぼかした画像との差が小さい（なめらかな）部分ほど
    ぼかした画像を混ぜ、差が大きい輪郭は元のまま残す。ぼかしの半径は短辺に比例させる
    （reference を渡すと、画像の短辺の代わりにその長さを基準にする）。
    RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("ノイズ除去", amount, DETAIL_MIN, DETAIL_MAX)
    if amount == 0:
        return image.copy()
    rgb, alpha = _split_rgb(image)
    radius = _detail_radius(rgb, DENOISE_RADIUS_RATIO, reference)
    smooth = filter_image(rgb, ImageFilter.GaussianBlur(radius))
    difference = ImageChops.difference(rgb, smooth).convert("L")
    strength = amount / DETAIL_MAX
    # 差が小さいほどぼかした画像を多く混ぜ、しきい値に向かってなめらかに元の画像に戻す
    weight = difference.point(
        [round(255 * strength * _smooth_falloff(v / DENOISE_EDGE_THRESHOLD)) for v in range(256)]
    )
    return _merge_alpha(Image.composite(smooth, rgb, weight), alpha)


def _sharpen_radius(reference: float, output: float | None) -> float:
    """シャープの半径。保存時の半径（比率の半径と下限の大きいほう）を表示の縮尺に換算する。"""
    output = reference if output is None else output
    saved = max(SHARPEN_MIN_RADIUS, output * SHARPEN_RADIUS_RATIO)
    return saved * reference / output


def _smooth_falloff(t: float) -> float:
    """t = 0 で 1、t = 1 以上で 0 になり、その間はなめらかに下がる（smoothstep の逆）。"""
    t = min(max(t, 0.0), 1.0)
    return 1 - t * t * (3 - 2 * t)


def _detail_radius(image: Image.Image, ratio: float, reference: float | None) -> float:
    """基準の長さ（省略時は画像の短辺）に比例した半径（px）。"""
    return (min(image.size) if reference is None else reference) * ratio


def _split_rgb(image: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    return image.convert("RGB"), alpha


def _merge_alpha(rgb: Image.Image, alpha: Image.Image | None) -> Image.Image:
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


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


def contrast(image: Image.Image, amount: int) -> Image.Image:
    """コントラスト（明暗の差）を変えた新しい画像を返す（入力画像は変更しない）。

    amount は -100〜+100（0 は変化なし）。
    - プラス: S 字のトーンカーブ（smoothstep を amount/100 の割合で混ぜる）で明暗の差を強める。
      黒 (0) と白 (255) は変えないので、白飛び・黒つぶれしにくい
    - マイナス: 中間の灰色 (128) に向けて差を縮める（-100 で差が半分）。フェードした調子になる

    RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_amount("コントラスト", amount, CONTRAST_MIN, CONTRAST_MAX)
    if amount == 0:
        return image.copy()

    t = abs(amount) / CONTRAST_MAX
    if amount > 0:

        def curve(x: float) -> float:
            return (1 - t) * x + t * (3 * x * x - 2 * x * x * x)

    else:
        slope = 1 - (1 - CONTRAST_MIN_SLOPE) * t

        def curve(x: float) -> float:
            return 0.5 + (x - 0.5) * slope

    table = _clip_table([255 * curve(v / 255) for v in range(256)])
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB").point(table * 3)
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def exposure(image: Image.Image, ev: float) -> Image.Image:
    """露出を ev 段（EV）変えた新しい画像を返す（入力画像は変更しない）。

    ev は -5.0〜+5.0（0 は変化なし）。色を一度リニア（光の量）に直して 2^ev 倍し、sRGB に
    戻す。カメラの露出補正と同じく、明るい部分は白く飛び、暗い部分は沈む。
    RGB にのみ適用し、アルファは元のまま戻す。
    """
    if not EXPOSURE_MIN <= ev <= EXPOSURE_MAX:
        raise ValueError(f"露出は {EXPOSURE_MIN}〜{EXPOSURE_MAX} EV で指定してください: {ev}")
    if ev == 0:
        return image.copy()

    gain = 2.0**ev
    table = _clip_table(
        [255 * _linear_to_srgb(min(1.0, _srgb_to_linear(v / 255) * gain)) for v in range(256)]
    )
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB").point(table * 3)
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def _srgb_to_linear(value: float) -> float:
    """sRGB の値 (0〜1) を光の量 (リニア、0〜1) に直す。"""
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value: float) -> float:
    """光の量 (リニア、0〜1) を sRGB の値 (0〜1) に直す。"""
    if value <= 0.0031308:
        return value * 12.92
    return 1.055 * value ** (1 / 2.4) - 0.055
