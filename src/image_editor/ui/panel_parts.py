"""設定パネルの部品（定数・スライダーなどの小さなウィジェット・表示用の書式・状態）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from image_editor.core.pipeline import EditSettings
from image_editor.core.transform import (
    AspectRatio,
)

if TYPE_CHECKING:
    from image_editor.ui.settings_panel import SettingsPanel

# 未読込時に数値欄へ表示する文字（空文字だと QSpinBox の特殊表示が無効になるため空白）
BLANK_TEXT = " "
TRIM_TEXT = "トリミング実行"
EDIT_RANGE_TEXT = "範囲を編集"
# フレーム・円を選んでいるとき、比のプルダウンに表示する項目（ユーザーは選べない）
FOLLOW_FRAME_TEXT = "フレーム・円に合わせる"
FOLLOW_FRAME_DATA = "follow_frame"
# 「加工」のスライダーの最小の長さ（細かく調整しやすいよう長めにする）
SLIDER_MIN_WIDTH = 225
# タブの名前
TAB_ADJUST_TEXT = "加工"
TAB_CROP_TEXT = "切り抜き"
TAB_OUTPUT_TEXT = "出力"
TAB_DIORAMA_TEXT = "ジオラマ"
DIORAMA_NOTE_TEXT = (
    "ぼかしを 0 より大きくすると、ピントの帯（プレビューの実線の間）だけをくっきり残し、"
    "外側に向かってぼかします（点線でぼけきります）。街並みを見下ろした写真に向いています。"
)
# パネルのグループ間の間隔と上下の余白（px）
PANEL_SPACING = 4
PANEL_MARGIN = 6


@dataclass(frozen=True)
class PanelState:
    """アンドゥ／リドゥで戻す、設定パネルの状態。

    保存に使う設定 (EditSettings) に加えて、範囲の指定を助ける比の選択も持つ
    （戻したトリミング範囲と比の固定が食い違わないように）。
    """

    settings: EditSettings
    aspect: AspectRatio = AspectRatio.FREE
    portrait: bool = False


class Updating:
    """プログラムから値を変える間、連動処理とシグナル発行を止める。"""

    def __init__(self, panel: SettingsPanel) -> None:
        self._panel = panel
        self._previous = False

    def __enter__(self) -> None:
        self._previous = self._panel._updating
        self._panel._updating = True

    def __exit__(self, *exc: object) -> None:
        self._panel._updating = self._previous


def ev_text(ev: float) -> str:
    """露出を「+1.3 EV」「-0.5 EV」「0.0 EV」のように表示する。"""
    return f"{ev:+.1f} EV" if ev else "0.0 EV"


def signed_text(value: int) -> str:
    """0 以外は符号付きで表示する（例: +30, -50）。"""
    return f"{value:+d}" if value else "0"


def tab_page(*widgets: QWidget) -> QWidget:
    """タブの中身（部品を上から並べ、余りは下に空ける）を作る。"""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(PANEL_SPACING)
    # タブの枠の内側にさらに余白を足すとパネルの最小幅が広がるので、左右は詰める
    layout.setContentsMargins(0, PANEL_MARGIN, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return page


def percent_text(value: int) -> str:
    return f"{value}%"


def kelvin_text(kelvin: int) -> str:
    return f"{kelvin} K"


class ResettableSlider(QSlider):
    """ダブルクリックで既定値に戻る横向きのスライダー。"""

    def __init__(self, default: int, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._default = default

    def default_value(self) -> int:
        """既定値を返す。"""
        return self._default

    def reset(self) -> None:
        """既定値に戻す（変われば valueChanged を発行する）。"""
        self.setValue(self._default)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.reset()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def amount_slider(
    minimum: int, maximum: int, default: int = 0
) -> tuple[ResettableSlider, QLabel, QHBoxLayout]:
    """強さを指定するスライダーと、現在値を表示するラベルを横に並べて返す。

    スライダーは default で始まり、ダブルクリックで default に戻る。
    """
    slider = ResettableSlider(default)
    slider.setRange(minimum, maximum)
    slider.setValue(default)
    slider.setPageStep(10)
    slider.setMinimumWidth(SLIDER_MIN_WIDTH)
    label = QLabel(str(minimum))
    label.setMinimumWidth(64)  # 「10000 K」が入る幅で、各スライダーの長さをそろえる
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    row = QHBoxLayout()
    row.addWidget(slider)
    row.addWidget(label)
    return slider, label, row


@dataclass(frozen=True)
class Adjustment:
    """設定 (EditSettings) の 1 項目と、それを操作するスライダー・値の表示の対応。

    スライダーは整数しか持てないので、設定の値との換算 (to_setting / to_slider) を持つ
    （例: 露出は「EV × 10」、色温度は「ケルビン ÷ 100」でスライダーに持つ）。
    """

    field: str  # EditSettings の項目名
    slider: ResettableSlider
    label: QLabel  # 今の値の表示
    to_setting: Callable[[int], Any]
    to_slider: Callable[[Any], int]
    text: Callable[[Any], str]  # 値の表示の書式

    def value(self) -> Any:
        """設定の値を返す。"""
        return self.to_setting(self.slider.value())

    def set_value(self, value: Any) -> None:
        """設定の値をスライダーに反映する（変われば valueChanged を発行する）。"""
        self.slider.setValue(self.to_slider(value))

    def update_label(self) -> None:
        """値の表示を今の値に合わせる。"""
        self.label.setText(self.text(self.value()))


def _same(value: Any) -> Any:
    return value


def adjustment(
    field: str,
    minimum: int,
    maximum: int,
    default: int = 0,
    *,
    to_setting: Callable[[int], Any] = _same,
    to_slider: Callable[[Any], int] = _same,
    text: Callable[[Any], str] = str,
    page_step: int | None = None,
) -> tuple[Adjustment, QHBoxLayout]:
    """設定の 1 項目を操作するスライダーと値の表示を作り、横に並べた行と一緒に返す。

    minimum・maximum・default はスライダーの値（設定の値を to_slider で換算したもの）。
    """
    slider, label, row = amount_slider(minimum, maximum, default)
    if page_step is not None:
        slider.setPageStep(page_step)
    item = Adjustment(field, slider, label, to_setting, to_slider, text)
    item.update_label()
    return item, row


def spin_box(minimum: int, maximum: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)  # 入力確定時にだけ連動させる
    spin.setAccelerated(True)
    return spin
