"""設定パネルの部品（定数・スライダーなどの小さなウィジェット・表示用の書式・状態）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def spin_box(minimum: int, maximum: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)  # 入力確定時にだけ連動させる
    spin.setAccelerated(True)
    return spin
