"""文字・透かし（ウォーターマーク）を画像に描く。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("/System/Library/Fonts")
TEXT_SIZE_MIN = 1.0  # 文字の大きさ（短辺に対する %）
TEXT_SIZE_MAX = 30.0
TEXT_SIZE_DEFAULT = 5.0
TEXT_OPACITY_MIN = 0
TEXT_OPACITY_MAX = 100
TEXT_OPACITY_DEFAULT = 80
TEXT_MARGIN_RATIO = 0.03  # 写真の端からの余白（短辺に対する比率）
LINE_SPACING_RATIO = 0.25  # 行間（文字の大きさに対する比率）
WHITE = (255, 255, 255)


class TextFont(Enum):
    """文字のフォント（どの Mac にも入っているもの）。値は (ファイル名, ttc の番号)。"""

    GOTHIC = ("ヒラギノ角ゴシック W3.ttc", 0)
    GOTHIC_BOLD = ("ヒラギノ角ゴシック W6.ttc", 0)
    MINCHO = ("ヒラギノ明朝 ProN.ttc", 0)
    MARU_GOTHIC = ("ヒラギノ丸ゴ ProN W4.ttc", 0)
    HELVETICA = ("Helvetica.ttc", 0)
    TIMES = ("Times.ttc", 0)

    @property
    def label(self) -> str:
        """UI に表示する名前。"""
        return _FONT_LABELS[self]

    @property
    def path(self) -> Path:
        """フォントファイルのパス。"""
        return FONT_DIR / self.value[0]


_FONT_LABELS: dict[TextFont, str] = {
    TextFont.GOTHIC: "ヒラギノ角ゴシック",
    TextFont.GOTHIC_BOLD: "ヒラギノ角ゴシック（太字）",
    TextFont.MINCHO: "ヒラギノ明朝",
    TextFont.MARU_GOTHIC: "ヒラギノ丸ゴ",
    TextFont.HELVETICA: "Helvetica",
    TextFont.TIMES: "Times",
}


class TextPosition(Enum):
    """文字を置く場所。写真の上の 9 か所と、フレームの余白。"""

    TOP_LEFT = "top_left"
    TOP = "top"
    TOP_RIGHT = "top_right"
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM = "bottom"
    BOTTOM_RIGHT = "bottom_right"
    FRAME_MARGIN = "frame_margin"  # ポラロイド・チェキの広い余白（フレームがなければ下中央）

    @property
    def label(self) -> str:
        """UI に表示する名前。"""
        return _POSITION_LABELS[self]


_POSITION_LABELS: dict[TextPosition, str] = {
    TextPosition.TOP_LEFT: "左上",
    TextPosition.TOP: "上",
    TextPosition.TOP_RIGHT: "右上",
    TextPosition.LEFT: "左",
    TextPosition.CENTER: "中央",
    TextPosition.RIGHT: "右",
    TextPosition.BOTTOM_LEFT: "左下",
    TextPosition.BOTTOM: "下",
    TextPosition.BOTTOM_RIGHT: "右下",
    TextPosition.FRAME_MARGIN: "フレームの余白",
}

# 位置ごとの横・縦のそろえ方（0 = 左・上、0.5 = 中央、1 = 右・下）
_ANCHORS: dict[TextPosition, tuple[float, float]] = {
    TextPosition.TOP_LEFT: (0, 0),
    TextPosition.TOP: (0.5, 0),
    TextPosition.TOP_RIGHT: (1, 0),
    TextPosition.LEFT: (0, 0.5),
    TextPosition.CENTER: (0.5, 0.5),
    TextPosition.RIGHT: (1, 0.5),
    TextPosition.BOTTOM_LEFT: (0, 1),
    TextPosition.BOTTOM: (0.5, 1),
    TextPosition.BOTTOM_RIGHT: (1, 1),
    TextPosition.FRAME_MARGIN: (0.5, 0.5),
}


@dataclass(frozen=True)
class TextSettings:
    """文字・透かしの設定。text が空なら何も描かない。

    size は写真の短辺に対する %（縮小プレビューと原寸で大きさがそろう）。
    """

    text: str = ""
    font: TextFont = TextFont.GOTHIC
    size: float = TEXT_SIZE_DEFAULT
    color: tuple[int, int, int] = WHITE
    opacity: int = TEXT_OPACITY_DEFAULT
    position: TextPosition = TextPosition.BOTTOM_RIGHT

    def is_empty(self) -> bool:
        """描く文字がないか（空白だけも含む）。"""
        return not self.text.strip()


def load_font(font: TextFont, size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """フォントを読み込む。ファイルがなければ Pillow の組み込みフォントで代わりに描く。"""
    return _load_font(font, max(1, size_px))


@lru_cache(maxsize=32)
def _load_font(font: TextFont, size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(font.path), size_px, index=font.value[1])
    except OSError:
        return ImageFont.load_default(size_px)


def text_size_px(settings: TextSettings, reference: float) -> int:
    """文字の大きさ（px）。reference は基準にする写真の短辺。"""
    size = min(max(settings.size, TEXT_SIZE_MIN), TEXT_SIZE_MAX)
    return max(1, round(reference * size / 100))


def draw_text(
    image: Image.Image,
    settings: TextSettings,
    box: tuple[int, int, int, int] | None = None,
    reference: float | None = None,
) -> Image.Image:
    """画像に文字を描いた新しい画像を返す（入力画像は変更しない）。

    box（左, 上, 右, 下）の中に、settings.position に合わせて置く（省略時は画像全体）。
    写真の上の位置では box の端から短辺の 3% 内側に置く。文字の大きさ・余白の基準は
    reference（省略時は box の短辺）。box に収まらないときは収まるまで小さくする。
    不透明度に合わせて半透明で重ね、元の透過はそのまま残す。
    """
    if settings.is_empty():
        return image.copy()
    left, top, right, bottom = box or (0, 0, image.width, image.height)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return image.copy()
    reference = min(width, height) if reference is None else reference
    margin = 0 if settings.position is TextPosition.FRAME_MARGIN else reference * TEXT_MARGIN_RATIO
    available = (max(1.0, width - margin * 2), max(1.0, height - margin * 2))

    size_px = text_size_px(settings, reference)
    font, spacing, text_box = _fit_text(settings, size_px, available)
    text_width, text_height = text_box[2] - text_box[0], text_box[3] - text_box[1]
    anchor_x, anchor_y = _ANCHORS[settings.position]
    x = left + margin + (available[0] - text_width) * anchor_x - text_box[0]
    y = top + margin + (available[1] - text_height) * anchor_y - text_box[1]

    alpha = round(255 * min(max(settings.opacity, 0), TEXT_OPACITY_MAX) / TEXT_OPACITY_MAX)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).multiline_text(
        (x, y),
        settings.text,
        font=font,
        fill=(*settings.color, alpha),
        spacing=spacing,
        align=_ALIGN[anchor_x],
    )
    base = image.convert("RGBA")
    result = Image.alpha_composite(base, layer)
    if image.mode == "RGBA":
        # 元の透過は残す（文字は透明な部分の上にも見えるよう、文字の不透明度と合わせる）
        return result
    return result.convert(image.mode)


_ALIGN = {0: "left", 0.5: "center", 1: "right"}


def _fit_text(
    settings: TextSettings, size_px: int, available: tuple[float, float]
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, int, tuple[float, float, float, float]]:
    """available に収まるフォント・行間・文字の範囲を返す（収まらなければ小さくする）。"""
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    while True:
        font = load_font(settings.font, size_px)
        spacing = max(0, round(size_px * LINE_SPACING_RATIO))
        text_box = draw.multiline_textbbox((0, 0), settings.text, font=font, spacing=spacing)
        width, height = text_box[2] - text_box[0], text_box[3] - text_box[1]
        if (width <= available[0] and height <= available[1]) or size_px <= 1:
            return font, spacing, text_box
        scale = min(available[0] / max(width, 1), available[1] / max(height, 1))
        size_px = max(1, min(size_px - 1, int(size_px * scale)))
