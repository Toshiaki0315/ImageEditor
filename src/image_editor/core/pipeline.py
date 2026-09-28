"""編集設定 (EditSettings) と、それを画像に適用する apply_edits()。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PIL import Image

from image_editor.core import effects, filters, transform
from image_editor.core.filters import FilterType
from image_editor.core.transform import CropRect

PREVIEW_MAX_SIDE = 1600


@dataclass(frozen=True)
class EditSettings:
    """編集設定。トリミング範囲は原画像の座標系で持つ。"""

    crop: CropRect | None = None
    width: int | None = None
    height: int | None = None
    keep_aspect: bool = True
    filter: FilterType = FilterType.NONE
    vignette: int = 0  # 周辺減光の強さ 0〜100（0 = なし）
    aging: int = 0  # 経年劣化の強さ 0〜100（0 = なし）
    temperature: int = effects.TEMPERATURE_NEUTRAL  # 色温度（ケルビン、6500 = 変化なし）


def apply_edits(original: Image.Image, settings: EditSettings) -> Image.Image:
    """原画像に編集を適用した新しい画像を返す（原画像は変更しない）。

    処理順: トリミング → リサイズ → 色温度 → フィルター → 周辺減光 → 経年劣化
    → ポラロイドの白枠。
    白枠には周辺減光・経年劣化をかけない。
    """
    image = original
    rect = _effective_crop(original.size, settings)
    if rect is not None:
        image = transform.crop(image, rect)

    size = transform.fit_size(image.size, settings.width, settings.height, settings.keep_aspect)
    if size != image.size:
        image = transform.resize(image, size)

    # 写真アプリのホワイトバランスと同じく、色温度はフィルターの前に整える
    image = _apply_temperature(image, settings)
    # apply_filter は常に新しい画像を返すので、原画像がそのまま返ることはない
    image = filters.apply_filter(image, settings.filter, with_border=False)
    if settings.vignette:
        image = effects.vignette(image, settings.vignette)
    if settings.aging:
        image = effects.aging(image, settings.aging)
    if settings.filter is FilterType.POLAROID:
        image = filters.polaroid_frame(image)
    return image


def render_preview(
    image: Image.Image,
    settings: EditSettings,
    factor: float = 1.0,
    trimmed: bool = False,
) -> Image.Image:
    """プレビュー表示用の画像を返す（入力画像は変更しない）。

    image は原画像を factor 倍に縮小したプレビュー用の画像。フィルターの色・周辺減光・
    経年劣化を適用し、リサイズとポラロイドの白枠は適用しない（出力サイズは output_size で
    確認する）。

    - trimmed=False: 元の画角全体を表示する。周辺減光はトリミング範囲（なければ全体）を
      基準にかけ、トリミング範囲はいつでも選び直せる
    - trimmed=True: トリミング範囲だけを切り抜いて表示する（範囲がなければ全体）
    """
    rect = _effective_crop(image.size, scale_settings(settings, factor))
    rendered = filters.apply_filter(
        _apply_temperature(image, settings), settings.filter, with_border=False
    )
    if trimmed and rect is not None:
        rendered = transform.crop(rendered, rect)
        rect = None
    if settings.vignette:
        if rect is None:
            rendered = effects.vignette(rendered, settings.vignette)
        else:
            # トリミング範囲の中心を基準に暗くし、元の位置に戻す
            box = (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
            region = effects.vignette(rendered.crop(box), settings.vignette)
            rendered.paste(region, box[:2])
    if settings.aging:
        # 経年劣化は画素ごとの色の変化と固定模様の粒子なので、表示範囲全体にかける
        rendered = effects.aging(rendered, settings.aging)
    return rendered


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


def make_preview(
    original: Image.Image, max_side: int = PREVIEW_MAX_SIDE
) -> tuple[Image.Image, float]:
    """プレビュー用に長辺 max_side 以下へ縮小した画像と、その縮小率を返す。

    元から小さい画像は縮小せず、縮小率 1.0 で原画像をそのまま返す（変更はしない）。
    縮小率は scale_settings にそのまま渡せる。
    """
    long_side = max(original.size)
    if long_side <= max_side:
        return original, 1.0
    factor = max_side / long_side
    size = (
        max(1, round(original.width * factor)),
        max(1, round(original.height * factor)),
    )
    # reducing_gap で先に整数倍の縮小をしてから LANCZOS をかけ、大きな画像でも速くする
    preview = original.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
    return preview, factor


def _apply_temperature(image: Image.Image, settings: EditSettings) -> Image.Image:
    if settings.temperature == effects.TEMPERATURE_NEUTRAL:
        return image
    return effects.color_temperature(image, settings.temperature)


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
