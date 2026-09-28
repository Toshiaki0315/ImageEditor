"""編集設定 (EditSettings) と、それを画像に適用する apply_edits()。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PIL import Image

from image_editor.core import filters, transform
from image_editor.core.filters import FilterType
from image_editor.core.transform import CropRect


@dataclass(frozen=True)
class EditSettings:
    """編集設定。トリミング範囲は原画像の座標系で持つ。"""

    crop: CropRect | None = None
    width: int | None = None
    height: int | None = None
    keep_aspect: bool = True
    filter: FilterType = FilterType.NONE


def apply_edits(original: Image.Image, settings: EditSettings) -> Image.Image:
    """原画像に トリミング → リサイズ → フィルター の順で編集を適用した新しい画像を返す。

    原画像は変更しない。
    """
    image = original
    rect = _effective_crop(original.size, settings)
    if rect is not None:
        image = transform.crop(image, rect)

    size = transform.fit_size(image.size, settings.width, settings.height, settings.keep_aspect)
    if size != image.size:
        image = transform.resize(image, size)

    # apply_filter は常に新しい画像を返すので、原画像がそのまま返ることはない
    return filters.apply_filter(image, settings.filter)


def output_size(original_size: tuple[int, int], settings: EditSettings) -> tuple[int, int]:
    """画像を処理せずに、apply_edits の出力サイズを計算する（ポラロイドの枠を含む）。"""
    size = original_size
    rect = _effective_crop(original_size, settings)
    if rect is not None:
        size = (rect.width, rect.height)
    size = transform.fit_size(size, settings.width, settings.height, settings.keep_aspect)
    return filters.output_size(size, settings.filter)


def scale_settings(settings: EditSettings, factor: float) -> EditSettings:
    """縮小プレビュー用に、トリミング範囲と出力サイズを factor 倍に換算した設定を返す。

    換算後の幅・高さ・トリミング範囲の大きさは最小 1px。
    """
    if factor <= 0:
        raise ValueError(f"factor は正の数で指定してください: {factor}")

    crop = None
    if settings.crop is not None:
        rect = settings.crop
        # 左上と右下をそれぞれ換算し、端がずれないようにする
        left, top = _scale(rect.x, factor), _scale(rect.y, factor)
        right = _scale(rect.x + rect.width, factor)
        bottom = _scale(rect.y + rect.height, factor)
        width = max(1, right - left) if rect.width > 0 else rect.width
        height = max(1, bottom - top) if rect.height > 0 else rect.height
        crop = CropRect(left, top, width, height)

    return replace(
        settings,
        crop=crop,
        width=_scale_length(settings.width, factor),
        height=_scale_length(settings.height, factor),
    )


def _effective_crop(size: tuple[int, int], settings: EditSettings) -> CropRect | None:
    if settings.crop is None:
        return None
    return transform.clamp_crop(settings.crop, size)


def _scale(value: int, factor: float) -> int:
    return int(value * factor + 0.5) if value >= 0 else -int(-value * factor + 0.5)


def _scale_length(value: int | None, factor: float) -> int | None:
    if value is None:
        return None
    return min(transform.MAX_SIZE, max(1, _scale(value, factor)))
