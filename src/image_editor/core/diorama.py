"""ジオラマ風（ミニチュア風・ティルトシフト）の加工。

ピントの合う帯だけをくっきり残し、帯の外側に向かってなめらかにぼかし、色を少し鮮やかに
して、ミニチュア模型を接写したように見せる。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageEnhance, ImageFilter

from image_editor.core.parallel import filter_image
from image_editor.core.tone import curve_table, map_rgb, s_curve, smoothstep

DIORAMA_BLUR_MIN = 0
DIORAMA_BLUR_MAX = 100
DIORAMA_POSITION_MIN = 0  # ピントの位置（写真の上端・左端からの %）
DIORAMA_POSITION_MAX = 100
DIORAMA_POSITION_DEFAULT = 50
DIORAMA_WIDTH_MIN = 0  # ピントの幅（写真の高さ・幅に対する %）
DIORAMA_WIDTH_MAX = 100
DIORAMA_WIDTH_DEFAULT = 20
DIORAMA_VIVID_MIN = 0
DIORAMA_VIVID_MAX = 100
DIORAMA_VIVID_DEFAULT = 30

# ぼかし 100 のときのガウスぼかしの半径（短辺に対する比率。縮小プレビューと原寸でそろえる）
DIORAMA_MAX_RADIUS_RATIO = 0.02
# ピントの帯の端から、ぼけきるまでの長さ（写真の高さ・幅に対する比率）
DIORAMA_TRANSITION = 0.25
# 鮮やかさ 100 のとき: 彩度を何割上げるか、S 字カーブ（コントラスト）をどれだけ混ぜるか
DIORAMA_MAX_SATURATION = 0.5
DIORAMA_MAX_CONTRAST = 0.4


class DioramaDirection(Enum):
    """ピントの帯の向き。"""

    HORIZONTAL = "horizontal"  # 横の帯（上下をぼかす）
    VERTICAL = "vertical"  # 縦の帯（左右をぼかす）

    @property
    def label(self) -> str:
        """UI に表示する名前。"""
        return _DIRECTION_LABELS[self]


_DIRECTION_LABELS: dict[DioramaDirection, str] = {
    DioramaDirection.HORIZONTAL: "横の帯",
    DioramaDirection.VERTICAL: "縦の帯",
}


@dataclass(frozen=True)
class DioramaSettings:
    """ジオラマ風の加工の設定。blur が 0 なら何もしない（鮮やかさも効かない）。"""

    blur: int = 0
    direction: DioramaDirection = DioramaDirection.HORIZONTAL
    position: int = DIORAMA_POSITION_DEFAULT
    width: int = DIORAMA_WIDTH_DEFAULT
    vivid: int = DIORAMA_VIVID_DEFAULT

    def is_off(self) -> bool:
        """加工しない設定か。"""
        return self.blur == 0


@dataclass(frozen=True)
class DioramaBand:
    """ピントの帯の位置（写真の高さ・幅に対する割合。0〜1 の外にはみ出すこともある）。

    sharp_start〜sharp_end はくっきり残す範囲、その外側の blur_start・blur_end でぼけきる。
    """

    sharp_start: float
    sharp_end: float
    blur_start: float
    blur_end: float


def diorama_band(settings: DioramaSettings) -> DioramaBand:
    """設定からピントの帯の位置を返す（プレビューのガイド表示にも使う）。"""
    center = settings.position / 100
    half = settings.width / 200
    return DioramaBand(
        sharp_start=center - half,
        sharp_end=center + half,
        blur_start=center - half - DIORAMA_TRANSITION,
        blur_end=center + half + DIORAMA_TRANSITION,
    )


def diorama(
    image: Image.Image,
    settings: DioramaSettings,
    area: tuple[int, int, int, int] | None = None,
    reference: float | None = None,
) -> Image.Image:
    """ジオラマ風にした新しい画像を返す（入力画像は変更しない）。

    area（左, 上, 右, 下）は、ピントの位置・幅の基準にする写真の範囲（省略時は画像全体）。
    帯はその外側にも続けて描く。ぼかしの半径は reference（省略時は area の短辺）に比例させる。
    RGB にのみ適用し、アルファは元のまま戻す。
    """
    _check_settings(settings)
    if settings.is_off():
        return image.copy()
    left, top, right, bottom = area or (0, 0, image.width, image.height)
    if reference is None:
        reference = min(right - left, bottom - top)
    radius = reference * DIORAMA_MAX_RADIUS_RATIO * settings.blur / DIORAMA_BLUR_MAX
    mask = _sharpness_mask(image.size, settings, (left, top, right, bottom))
    vivid = settings.vivid / DIORAMA_VIVID_MAX
    contrast = curve_table(lambda x: s_curve(x, DIORAMA_MAX_CONTRAST * vivid)) * 3

    def process(rgb: Image.Image) -> Image.Image:
        blurred = filter_image(rgb, ImageFilter.GaussianBlur(radius))
        result = Image.composite(rgb, blurred, mask)
        if vivid:
            result = ImageEnhance.Color(result).enhance(1 + DIORAMA_MAX_SATURATION * vivid)
            result = result.point(contrast)
        return result

    return map_rgb(image, process)


def _sharpness_mask(
    size: tuple[int, int], settings: DioramaSettings, area: tuple[int, int, int, int]
) -> Image.Image:
    """くっきり残す度合い（255 = そのまま、0 = ぼけきる）の L モードのマスクを返す。

    帯に沿う向きには変わらないので、1 列（1 行）分を計算して引き伸ばす。
    """
    width, height = size
    left, top, right, bottom = area
    horizontal = settings.direction is DioramaDirection.HORIZONTAL
    length, start, span = (height, top, bottom - top) if horizontal else (width, left, right - left)
    band = diorama_band(settings)
    center = (band.sharp_start + band.sharp_end) / 2
    half = (band.sharp_end - band.sharp_start) / 2
    span = max(span, 1)

    def sharpness(i: int) -> int:
        u = (i + 0.5 - start) / span  # 写真の高さ・幅に対する位置（画素の中心）
        outside = max(0.0, abs(u - center) - half)
        return round(255 * (1 - smoothstep(min(outside / DIORAMA_TRANSITION, 1.0))))

    line = bytes(sharpness(i) for i in range(length))
    strip_size = (1, length) if horizontal else (length, 1)
    strip = Image.frombytes("L", strip_size, line)
    return strip.resize(size, Image.Resampling.NEAREST)


def _check_settings(settings: DioramaSettings) -> None:
    for name, value, minimum, maximum in (
        ("ぼかし", settings.blur, DIORAMA_BLUR_MIN, DIORAMA_BLUR_MAX),
        ("ピントの位置", settings.position, DIORAMA_POSITION_MIN, DIORAMA_POSITION_MAX),
        ("ピントの幅", settings.width, DIORAMA_WIDTH_MIN, DIORAMA_WIDTH_MAX),
        ("鮮やかさ", settings.vivid, DIORAMA_VIVID_MIN, DIORAMA_VIVID_MAX),
    ):
        if not minimum <= value <= maximum:
            raise ValueError(f"ジオラマの{name}は {minimum}〜{maximum} で指定してください: {value}")
