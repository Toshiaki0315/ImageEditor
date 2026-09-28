"""フィルター（PIL.Image -> PIL.Image の純粋関数）。"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from PIL import Image, ImageEnhance, ImageOps

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


class FilterType(Enum):
    """加工の種類。"""

    NONE = "none"
    SEPIA = "sepia"
    MONOTONE = "monotone"
    HIGH_TONE = "high_tone"
    POLAROID = "polaroid"

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
}


def apply_filter(image: Image.Image, filter_type: FilterType) -> Image.Image:
    """画像にフィルターを適用した新しい画像を返す（入力画像は変更しない）。

    RGB に対してのみ処理し、アルファチャンネルは元のまま戻す。
    """
    image = normalize_mode(image)
    if filter_type is FilterType.NONE:
        return image.copy()

    rgb, alpha = _split_alpha(image)
    if filter_type is FilterType.POLAROID:
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
    toned = ImageEnhance.Contrast(image).enhance(POLAROID_CONTRAST)
    red, green, blue = toned.split()
    toned = Image.merge(
        "RGB",
        (
            red.point(_scale_table(POLAROID_RED_FACTOR)),
            green,
            blue.point(_scale_table(POLAROID_BLUE_FACTOR)),
        ),
    )

    border, bottom = polaroid_border_sizes(image.size)
    width, height = image.size
    canvas_size = (width + border * 2, height + border + bottom)

    framed = Image.new("RGB", canvas_size, POLAROID_BORDER_COLOR)
    framed.paste(toned, (border, border))
    if alpha is not None:
        framed_alpha = Image.new("L", canvas_size, 255)
        framed_alpha.paste(alpha, (border, border))
        framed.putalpha(framed_alpha)
    return framed


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


def _scale_table(factor: float) -> list[int]:
    """各値に factor を掛けて 0〜255 にクリップするルックアップテーブル。"""
    return [min(255, int(v * factor + 0.5)) for v in range(256)]


_RGB_FILTERS: dict[FilterType, Callable[[Image.Image], Image.Image]] = {
    FilterType.SEPIA: sepia,
    FilterType.MONOTONE: monotone,
    FilterType.HIGH_TONE: high_tone,
}
