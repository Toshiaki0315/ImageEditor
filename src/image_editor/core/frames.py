"""フレーム（ポラロイド・チェキの白い台紙）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PIL import Image

FRAME_COLOR = (255, 255, 255)


class FrameType(Enum):
    """フレームの種類。"""

    NONE = "none"
    POLAROID = "polaroid"
    INSTAX_MINI = "instax_mini"

    @property
    def label(self) -> str:
        """UI に表示する日本語名。"""
        return _LABELS[self]


_LABELS: dict[FrameType, str] = {
    FrameType.NONE: "なし",
    FrameType.POLAROID: "ポラロイド",
    FrameType.INSTAX_MINI: "チェキ",
}


@dataclass(frozen=True)
class FrameSpec:
    """フレームの寸法（mm、縦向きのカード）。実物のおおよその値。"""

    window: tuple[float, float]  # 写真部分 (幅, 高さ)
    margins: tuple[float, float, float, float]  # 余白 (左, 上, 右, 下)


FRAME_SPECS: dict[FrameType, FrameSpec] = {
    # ポラロイド 600 / i-Type: カード 88×107mm、写真部分 79×79mm
    FrameType.POLAROID: FrameSpec(window=(79, 79), margins=(4.5, 6, 4.5, 22)),
    # チェキ (instax mini): カード 54×86mm、写真部分 46×62mm
    FrameType.INSTAX_MINI: FrameSpec(window=(46, 62), margins=(4, 6.5, 4, 17.5)),
}


def frame_spec(frame: FrameType, size: tuple[int, int]) -> FrameSpec | None:
    """写真の向きに合わせたフレームの寸法を返す。フレームなしなら None。

    写真部分が縦長のフレームに横長の写真を入れるときは、カードを横向きにする
    （反時計回りに 90° 回したときと同じく、下の広い余白が右に来る）。
    """
    if frame is FrameType.NONE:
        return None
    spec = FRAME_SPECS[frame]
    window_width, window_height = spec.window
    width, height = size
    if width > height and window_width < window_height:
        left, top, right, bottom = spec.margins
        return FrameSpec(window=(window_height, window_width), margins=(top, right, bottom, left))
    return spec


def window_aspect(frame: FrameType, size: tuple[int, int]) -> tuple[float, float] | None:
    """size の写真を入れるときの、写真部分の縦横比 (幅, 高さ) を返す。フレームなしなら None。"""
    spec = frame_spec(frame, size)
    return None if spec is None else spec.window


def frame_margins(frame: FrameType, size: tuple[int, int]) -> tuple[int, int, int, int]:
    """size の写真に付ける余白 (左, 上, 右, 下) を px で返す。四捨五入、最小 1px。

    余白は写真部分の大きさから実物の比率で計算する。写真の縦横比が写真部分と違うときは、
    写真部分に収まる側の縮尺に合わせる。フレームなしなら (0, 0, 0, 0)。
    """
    spec = frame_spec(frame, size)
    if spec is None:
        return (0, 0, 0, 0)
    scale = min(size[0] / spec.window[0], size[1] / spec.window[1])
    left, top, right, bottom = (max(1, int(mm * scale + 0.5)) for mm in spec.margins)
    return (left, top, right, bottom)


def framed_size(size: tuple[int, int], frame: FrameType) -> tuple[int, int]:
    """フレームを付けた後の大きさを返す。"""
    left, top, right, bottom = frame_margins(frame, size)
    return (size[0] + left + right, size[1] + top + bottom)


def add_frame(image: Image.Image, frame: FrameType) -> Image.Image:
    """RGB / RGBA 画像の周囲にフレームを付けた新しい画像を返す（入力画像は変更しない）。

    フレーム部分は白で不透明。写真の透過はそのまま残す。フレームなしならコピーを返す。
    """
    if frame is FrameType.NONE:
        return image.copy()
    left, top, _, _ = frame_margins(frame, image.size)
    canvas_size = framed_size(image.size, frame)

    framed = Image.new("RGB", canvas_size, FRAME_COLOR)
    framed.paste(image.convert("RGB"), (left, top))
    if image.mode == "RGBA":
        framed_alpha = Image.new("L", canvas_size, 255)
        framed_alpha.paste(image.getchannel("A"), (left, top))
        framed.putalpha(framed_alpha)
    return framed
