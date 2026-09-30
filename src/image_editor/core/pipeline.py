"""編集設定 (EditSettings) と、それを画像に適用する apply_edits()。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PIL import Image

from image_editor.core import effects, filters, frames, shapes, transform
from image_editor.core.filters import FilterType
from image_editor.core.frames import FRAME_COLOR, FrameType
from image_editor.core.histogram import Histogram, compute_histogram
from image_editor.core.shapes import ShapeType
from image_editor.core.transform import CropRect, Orientation

PREVIEW_MAX_SIDE = 1600


@dataclass(frozen=True)
class EditSettings:
    """編集設定。トリミング範囲は、回転・反転した後の原寸画像の座標系で持つ。"""

    orientation: Orientation = Orientation()
    crop: CropRect | None = None
    width: int | None = None
    height: int | None = None
    keep_aspect: bool = True
    filter: FilterType = FilterType.NONE
    vignette: int = 0  # 周辺減光の強さ 0〜100（0 = なし）
    aging: int = 0  # 経年劣化の強さ 0〜100（0 = なし）
    temperature: int = effects.TEMPERATURE_NEUTRAL  # 色温度（ケルビン、6500 = 変化なし）
    saturation: int = 0  # 彩度 -100〜+100（0 = 変化なし）
    brightness: int = 0  # 明るさ -100〜+100（0 = 変化なし）
    contrast: int = 0  # コントラスト -100〜+100（0 = 変化なし）
    exposure: float = 0.0  # 露出 -5.0〜+5.0 EV（0 = 変化なし）
    sharpen: int = 0  # シャープ 0〜100（0 = なし）
    blur: int = 0  # ぼかし 0〜100（0 = なし）
    denoise: int = 0  # ノイズ除去 0〜100（0 = なし）
    frame: FrameType = FrameType.NONE
    shape: ShapeType = ShapeType.RECTANGLE
    corner_radius: int = shapes.CORNER_RADIUS_DEFAULT  # 角丸の半径（短辺に対する % 0〜50）


def apply_edits(original: Image.Image, settings: EditSettings) -> Image.Image:
    """原画像に編集を適用した新しい画像を返す（原画像は変更しない）。

    処理順: 回転・反転 → トリミング（フレームの写真部分・円の比率への切り抜きを含む）
    → リサイズ → 露出 → 明るさ → コントラスト → 色温度 → 彩度 → フィルター → 周辺減光
    → 経年劣化 → 形 → フレーム。形の外側は、フレームがあればフレームの白、なければ透明にする。
    フレームには周辺減光・経年劣化をかけない。
    """
    image = settings.orientation.transpose(original)
    rect = effective_crop(image.size, settings.crop, settings.frame, settings.shape)
    if rect is not None:
        image = transform.crop(image, rect)

    size = transform.fit_size(image.size, settings.width, settings.height, settings.keep_aspect)
    if size != image.size:
        image = transform.resize(image, size)

    # 写真アプリの基本補正と同じく、露出〜彩度・ディテールはフィルターの前に整える
    image = _apply_detail(_apply_basic_adjustments(image, settings), settings)
    # apply_filter は常に新しい画像を返すので、原画像がそのまま返ることはない
    image = filters.apply_filter(image, settings.filter)
    if settings.vignette:
        image = effects.vignette(image, settings.vignette)
    if settings.aging:
        image = effects.aging(image, settings.aging)
    return _apply_shape_and_frame(image, settings)


def render_preview(
    image: Image.Image,
    settings: EditSettings,
    factor: float = 1.0,
    trimmed: bool = False,
) -> Image.Image:
    """プレビュー表示用の画像を返す（入力画像は変更しない）。

    詳しくは render_preview_with_histogram。
    """
    return render_preview_with_histogram(image, settings, factor, trimmed)[0]


def render_preview_with_histogram(
    image: Image.Image,
    settings: EditSettings,
    factor: float = 1.0,
    trimmed: bool = False,
) -> tuple[Image.Image, Histogram]:
    """プレビュー表示用の画像と、保存される写真のヒストグラムを返す（入力画像は変更しない）。

    image は原画像を factor 倍に縮小したプレビュー用の画像（回転・反転する前のもの）。
    回転・反転・フィルターの色・周辺減光・経年劣化を適用し、リサイズは適用しない
    （出力サイズは output_size で確認する）。

    - trimmed=False: 元の画角全体を表示する。周辺減光はトリミング範囲（フレーム・円が
      あればその比率に切り抜いた範囲。なければ全体）を基準にかけ、トリミング範囲は
      いつでも選び直せる。形とフレームは反映しない
    - trimmed=True: 切り抜いた範囲だけを表示し、形とフレームも反映して完成形を見せる
      （切り抜く範囲がなければ全体）

    ヒストグラムは、実際に切り抜く範囲（なければ全体）の、形・フレームを付ける前の写真から
    数える（マスクやフレームの白は含めない。形の外側と透明な画素も数えない）。
    """
    image = settings.orientation.transpose(image)
    scaled = scale_settings(settings, factor)
    rect = effective_crop(image.size, scaled.crop, scaled.frame, scaled.shape)
    # ディテールの半径は、保存時と同じく実際に切り抜く範囲（なければ全体）の短辺を基準にする
    reference = min(rect.width, rect.height) if rect is not None else min(image.size)
    output = _saved_photo_short_side(image.size, settings, factor)
    adjusted = _apply_detail(_apply_basic_adjustments(image, settings), settings, reference, output)
    rendered = filters.apply_filter(adjusted, settings.filter)
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
    photo = transform.crop(rendered, rect) if rect is not None else rendered
    shape_mask = shapes.shape_mask(photo.size, settings.shape, settings.corner_radius)
    histogram = compute_histogram(photo, shape_mask)
    if trimmed:
        rendered = _apply_shape_and_frame(rendered, settings)
    return rendered, histogram


def output_size(original_size: tuple[int, int], settings: EditSettings) -> tuple[int, int]:
    """画像を処理せずに、apply_edits の出力サイズを計算する（フレームを含む）。"""
    size = settings.orientation.size(original_size)
    rect = effective_crop(size, settings.crop, settings.frame, settings.shape)
    if rect is not None:
        size = (rect.width, rect.height)
    size = transform.fit_size(size, settings.width, settings.height, settings.keep_aspect)
    return frames.framed_size(size, settings.frame)


def effective_crop(
    size: tuple[int, int],
    crop: CropRect | None,
    frame: FrameType = FrameType.NONE,
    shape: ShapeType = ShapeType.RECTANGLE,
) -> CropRect | None:
    """実際に切り抜く範囲を返す（size の画像の座標系）。切り抜かないなら None。

    トリミング範囲は画像内に収まるよう補正する。フレームがあるときは、トリミング範囲
    （なければ画像全体）をフレームの写真部分の縦横比になるよう中央で切り抜く。
    フレームがなく形が円のときは、中央を正方形に切り抜く（フレームがあるときの円は
    写真部分の中に描くので、写真部分の比率のまま）。
    """
    rect = transform.clamp_crop(crop, size) if crop is not None else None
    base = rect or CropRect(0, 0, *size)
    aspect = frames.window_aspect(frame, (base.width, base.height))
    if aspect is None:
        aspect = shapes.shape_aspect(shape)
    if aspect is None:
        return rect
    return transform.fit_aspect(base, aspect)


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


def _apply_shape_and_frame(image: Image.Image, settings: EditSettings) -> Image.Image:
    """形で切り抜き、フレームを付ける。

    形の外側は、フレームがあればフレームの白で塗り、なければ透明にする。
    """
    has_frame = settings.frame is not FrameType.NONE
    if settings.shape is not ShapeType.RECTANGLE:
        fill = FRAME_COLOR if has_frame else None
        image = shapes.apply_shape(image, settings.shape, settings.corner_radius, fill)
    if has_frame:
        image = frames.add_frame(image, settings.frame)
    return image


def _apply_detail(
    image: Image.Image,
    settings: EditSettings,
    reference: float | None = None,
    output: float | None = None,
) -> Image.Image:
    """ディテール（ノイズ除去 → ぼかし → シャープ）をかける。変化がなければ入力をそのまま返す。

    半径は reference（省略時は画像の短辺）に比例させる。output は保存する写真の短辺で、
    縮小プレビューでシャープの半径の下限を保存時と同じ効き方に換算するのに使う。
    """
    if settings.denoise:
        image = effects.denoise(image, settings.denoise, reference)
    if settings.blur:
        image = effects.blur(image, settings.blur, reference)
    if settings.sharpen:
        image = effects.sharpen(image, settings.sharpen, reference, output)
    return image


def _saved_photo_short_side(
    preview_size: tuple[int, int], settings: EditSettings, factor: float
) -> float:
    """保存する写真（切り抜き・リサイズ後、フレームを付ける前）の短辺を、プレビューから求める。

    preview_size は回転・反転した後のプレビューの大きさ、factor は原画像に対する縮小率。
    """
    original = (round(preview_size[0] / factor), round(preview_size[1] / factor))
    rect = effective_crop(original, settings.crop, settings.frame, settings.shape)
    size = (rect.width, rect.height) if rect is not None else original
    size = transform.fit_size(size, settings.width, settings.height, settings.keep_aspect)
    return min(size)


def _apply_basic_adjustments(image: Image.Image, settings: EditSettings) -> Image.Image:
    """フィルターの前にかける基本補正（露出 → 明るさ → コントラスト → 色温度 → 彩度）。

    変化がなければ入力をそのまま返す。
    """
    if settings.exposure:
        image = effects.exposure(image, settings.exposure)
    if settings.brightness:
        image = effects.brightness(image, settings.brightness)
    if settings.contrast:
        image = effects.contrast(image, settings.contrast)
    if settings.temperature != effects.TEMPERATURE_NEUTRAL:
        image = effects.color_temperature(image, settings.temperature)
    if settings.saturation:
        image = effects.saturation(image, settings.saturation)
    return image


def _scale(value: int, factor: float) -> int:
    return int(value * factor + 0.5) if value >= 0 else -int(-value * factor + 0.5)


def _scale_length(value: int | None, factor: float) -> int | None:
    if value is None:
        return None
    return min(transform.MAX_SIZE, max(1, _scale(value, factor)))
