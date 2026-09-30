"""プレビューに重ねるヒストグラム（R・G・B を半透明で、輝度を灰色で重ねる）。"""

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent
from PyQt6.QtWidgets import QWidget

from image_editor.core.histogram import BINS, Histogram

GRAPH_SIZE = QSize(BINS, 90)  # グラフの大きさ（論理ピクセル。横は 1 段階 1px）
PADDING = 6
BACKGROUND = QColor(0, 0, 0, 150)
# R・G・B・輝度の塗りの色（重なると混ざるよう半透明）
CHANNEL_COLORS = (
    QColor(255, 70, 70, 110),
    QColor(70, 220, 70, 110),
    QColor(80, 130, 255, 120),
    QColor(230, 230, 230, 120),
)


def histogram_peak(histogram: Histogram) -> int:
    """高さの基準にする値（すべてのチャンネルの、両端を除いた最大の画素数。最小 1）。

    白飛び・黒つぶれで両端 (0・255) だけ極端に多いと他がつぶれて見えないので、両端は
    基準に入れず、グラフの上端で切る。
    """
    return max(1, *(max(channel[1:-1]) for channel in histogram.channels()))


class HistogramView(QWidget):
    """ヒストグラムを描くウィジェット。マウス操作は下のウィジェットに通す。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._histogram: Histogram | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(GRAPH_SIZE.width() + PADDING * 2, GRAPH_SIZE.height() + PADDING * 2)
        self.hide()

    def set_histogram(self, histogram: Histogram | None) -> None:
        """描くヒストグラムを設定する。None で消す。"""
        self._histogram = histogram
        self.setVisible(histogram is not None)
        self.update()

    def histogram(self) -> Histogram | None:
        """表示中のヒストグラムを返す。"""
        return self._histogram

    def paintEvent(self, event: QPaintEvent | None) -> None:
        if self._histogram is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(QRectF(self.rect()), 6, 6)

        graph = QRectF(PADDING, PADDING, GRAPH_SIZE.width(), GRAPH_SIZE.height())
        peak = histogram_peak(self._histogram)
        for channel, color in zip(self._histogram.channels(), CHANNEL_COLORS, strict=True):
            painter.fillPath(_channel_path(channel, peak, graph), color)
        painter.end()


def _channel_path(channel: tuple[int, ...], peak: int, graph: QRectF) -> QPainterPath:
    """1 チャンネル分の塗りの輪郭（下端から山の形）。"""
    step = graph.width() / len(channel)
    path = QPainterPath(QPointF(graph.left(), graph.bottom()))
    for index, count in enumerate(channel):
        height = graph.height() * min(1.0, count / peak)
        x = graph.left() + index * step
        path.lineTo(QPointF(x, graph.bottom() - height))
        path.lineTo(QPointF(x + step, graph.bottom() - height))
    path.lineTo(QPointF(graph.right(), graph.bottom()))
    path.closeSubpath()
    return path
