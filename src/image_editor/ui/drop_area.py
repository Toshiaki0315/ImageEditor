"""D&D エリアとプレビュー表示。"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QMimeData, QPointF, QRectF, QSize, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import QLabel, QWidget

from image_editor.core.diorama import DioramaBand
from image_editor.core.histogram import Histogram
from image_editor.core.io import is_supported
from image_editor.ui.crop_overlay import CropOverlay
from image_editor.ui.histogram_view import HistogramView
from image_editor.ui.qt_image import pil_to_qimage

PLACEHOLDER_TEXT = "ここに画像をドロップしてください\n（⌘V で貼り付けもできます）"
MARGIN = 16
BORDER_RADIUS = 12
HIGHLIGHT_FILL_ALPHA = 40
BADGE_MARGIN = 8  # 画像の左上から「加工前」などの表示までの間隔
BADGE_STYLE = (
    "QLabel { background: rgba(0, 0, 0, 160); color: white; border-radius: 4px; padding: 2px 8px; }"
)
# 透過部分の市松模様（1 マスの大きさは論理ピクセル）
CHECKER_SIZE = 8
CHECKER_LIGHT = QColor(255, 255, 255)
CHECKER_DARK = QColor(204, 204, 204)
# ジオラマのピントの帯のガイド（実線: くっきり残す範囲の端、点線: ぼけきる位置）
GUIDE_COLOR = QColor(255, 204, 0)
GUIDE_SHADOW = QColor(0, 0, 0, 140)


@dataclass(frozen=True)
class DioramaGuide:
    """プレビューに重ねる、ジオラマのピントの帯のガイド。

    area は表示している画像の中の写真の範囲（左, 上, 幅, 高さ。画像に対する 0〜1 の割合）。
    帯の位置 (band) は写真に対する割合で、写真の外にも続けて描く。
    """

    area: tuple[float, float, float, float]
    horizontal: bool
    band: DioramaBand

    def lines(self) -> tuple[tuple[float, bool], ...]:
        """ガイドの線の位置（表示している画像に対する割合）と、実線かどうかを返す。"""
        left, top, width, height = self.area
        start, length = (top, height) if self.horizontal else (left, width)
        band = self.band
        return (
            (start + band.blur_start * length, False),
            (start + band.sharp_start * length, True),
            (start + band.sharp_end * length, True),
            (start + band.blur_end * length, False),
        )


class _GuideView(QWidget):
    """D&D エリアに重ね、ジオラマのガイドの線を描く（マウス操作は下に通す）。"""

    def __init__(self, area: "DropArea") -> None:
        super().__init__(area)
        self._area = area
        self.guide: DioramaGuide | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        rect = self._area.image_rect()
        if self.guide is None or rect.isEmpty():
            return
        painter = QPainter(self)
        painter.setClipRect(rect)
        for fraction, solid in self.guide.lines():
            if self.guide.horizontal:
                y = rect.y() + fraction * rect.height()
                start, end = QPointF(rect.left(), y), QPointF(rect.right(), y)
            else:
                x = rect.x() + fraction * rect.width()
                start, end = QPointF(x, rect.top()), QPointF(x, rect.bottom())
            style = Qt.PenStyle.SolidLine if solid else Qt.PenStyle.DashLine
            # 明るい写真でも暗い写真でも見えるよう、影を付けて描く
            shadow = QPen(GUIDE_SHADOW, 3)
            shadow.setStyle(style)
            painter.setPen(shadow)
            painter.drawLine(start, end)
            pen = QPen(GUIDE_COLOR, 1.5)
            pen.setStyle(style)
            painter.setPen(pen)
            painter.drawLine(start, end)
        painter.end()


class DropArea(QWidget):
    """画像ファイルのドロップを受け付け、画像を縦横比を保ってエリアに収めて表示する。

    読み込みは行わず、ドロップされたファイルを files_dropped シグナルで通知する。
    """

    files_dropped = pyqtSignal(list)  # list[Path]
    double_clicked = pyqtSignal(object)  # QPointF（ウィジェット座標）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(200, 200)
        self._source: QImage | None = None
        self._cache: QPixmap | None = None
        self._highlighted = False
        self._checker: QBrush | None = None
        # トリミング範囲の選択（既定は無効）
        self.crop_overlay = CropOverlay(self.image_rect, self)
        # 画像の左上に重ねる表示（「加工前」など）。範囲選択のマスクより手前に出す
        self.badge = QLabel(self)
        self.badge.setStyleSheet(BADGE_STYLE)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge.hide()
        # ジオラマのピントの帯のガイド（範囲選択のマスクより手前、表示・ヒストグラムより奥）
        self._guide_view = _GuideView(self)
        self._guide_view.hide()
        # 右下に重ねるヒストグラム（範囲選択のマスクより手前）
        self.histogram_view = HistogramView(self)
        # 100% 表示（画像 1px = 画面の 1 画素）。表示中の画像と、その左上のウィジェット座標
        self._zoom: QPixmap | None = None
        self._zoom_has_alpha = False
        self._zoom_offset = QPointF(0, 0)
        self._pan_from: tuple[QPointF, QPointF] | None = None  # (押した位置, そのときの左上)

    # --- 画像 ---------------------------------------------------------------

    def set_image(self, image: Image.Image | None) -> None:
        """表示する画像を設定する。None で未読込の表示に戻す。"""
        self._source = None if image is None else pil_to_qimage(image)
        self._cache = None
        self._place_badge()
        self.update()

    def set_badge(self, text: str | None) -> None:
        """画像の左上に text を重ねて表示する。None で消す。"""
        if text is None:
            self.badge.hide()
            return
        self.badge.setText(text)
        self.badge.adjustSize()
        self._place_badge()
        self.badge.show()
        self.badge.raise_()

    def badge_text(self) -> str | None:
        """表示中の text を返す（表示していなければ None）。"""
        return self.badge.text() if self.badge.isVisible() else None

    def set_diorama_guide(self, guide: DioramaGuide | None) -> None:
        """ジオラマのピントの帯のガイドを重ねて表示する。None で消す。"""
        view = self._guide_view
        if guide == view.guide and view.isVisible() == (guide is not None):
            return
        view.guide = guide
        view.setVisible(guide is not None)
        if guide is not None:
            view.raise_()
            # バッジ・ヒストグラムはガイドより手前に出す
            self.badge.raise_()
            self.histogram_view.raise_()
        view.update()

    def diorama_guide(self) -> DioramaGuide | None:
        """表示中のガイドを返す（表示していなければ None）。"""
        return self._guide_view.guide if self._guide_view.isVisible() else None

    def set_histogram(self, histogram: Histogram | None) -> None:
        """右下にヒストグラムを重ねて表示する。None で消す。"""
        self.histogram_view.set_histogram(histogram)
        self._place_histogram()
        if histogram is not None:
            self.histogram_view.raise_()

    def _place_histogram(self) -> None:
        view = self.histogram_view
        view.move(
            max(0, self.width() - view.width() - MARGIN),
            max(0, self.height() - view.height() - MARGIN),
        )

    def _place_badge(self) -> None:
        image_rect = self.image_rect()
        if image_rect.isEmpty():
            origin = QRectF(self.rect()).topLeft()
        else:
            # 100% 表示で画像が左上にはみ出していても、見える位置に出す
            origin = QPointF(max(image_rect.x(), 0), max(image_rect.y(), 0))
        self.badge.move(round(origin.x()) + BADGE_MARGIN, round(origin.y()) + BADGE_MARGIN)

    def set_zoom_image(
        self, image: Image.Image | None, center: tuple[float, float] | None = None
    ) -> None:
        """100% 表示（画像 1px = 画面の 1 画素）にする。None で画面に合わせた表示に戻す。

        center（画像の座標）を渡すと、その点が表示の中央に来るようにする。渡さなければ、
        同じ大きさの画像を表示中なら見ている場所を保ち、そうでなければ画像の中央を見せる。
        100% 表示の間は、ドラッグとスクロールで見る場所を動かせる。
        """
        if image is None:
            self._zoom = None
            self._pan_from = None
            self.unsetCursor()
        else:
            previous = self._zoom_logical_size() if self._zoom is not None else None
            pixmap = QPixmap.fromImage(pil_to_qimage(image))
            pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            self._zoom = pixmap
            self._zoom_has_alpha = pixmap.hasAlphaChannel()
            size = self._zoom_logical_size()
            if center is not None or previous != size:
                ratio = self.devicePixelRatioF()
                cx, cy = center if center is not None else (image.width / 2, image.height / 2)
                self._zoom_offset = QPointF(
                    self.width() / 2 - cx / ratio, self.height() / 2 - cy / ratio
                )
            self._clamp_zoom_offset()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._place_badge()
        self.update()

    def is_zoomed(self) -> bool:
        """100% 表示中かを返す。"""
        return self._zoom is not None

    def zoom_offset(self) -> QPointF:
        """100% 表示の画像の左上（ウィジェット座標）を返す。"""
        return QPointF(self._zoom_offset)

    def zoom_center(self) -> tuple[float, float] | None:
        """100% 表示で、表示の中央に見えている点（画像の座標）を返す。"""
        if self._zoom is None:
            return None
        ratio = self.devicePixelRatioF()
        return (
            (self.width() / 2 - self._zoom_offset.x()) * ratio,
            (self.height() / 2 - self._zoom_offset.y()) * ratio,
        )

    def has_image(self) -> bool:
        """画像が設定されているかを返す。"""
        return self._source is not None

    def is_highlighted(self) -> bool:
        """ドラッグ中のハイライト表示中かを返す。"""
        return self._highlighted

    def image_rect(self) -> QRectF:
        """画像を描画する範囲（ウィジェット座標、論理ピクセル）を返す。画像がなければ空。

        100% 表示中は、表示している画像全体の範囲（ウィジェットからはみ出すこともある）。
        """
        if self._zoom is not None:
            return QRectF(self._zoom_offset, QSizeF(self._zoom_logical_size()))
        if self._source is None:
            return QRectF()
        area = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        if area.width() <= 0 or area.height() <= 0:
            return QRectF()
        scale = min(
            area.width() / self._source.width(),
            area.height() / self._source.height(),
        )
        width = self._source.width() * scale
        height = self._source.height() * scale
        return QRectF(
            area.x() + (area.width() - width) / 2,
            area.y() + (area.height() - height) / 2,
            width,
            height,
        )

    def display_pixmap(self) -> QPixmap | None:
        """表示用に縮小した pixmap を返す（Retina では実ピクセルで作る）。画像がなければ None。"""
        rect = self.image_rect()
        if self._source is None or rect.isEmpty():
            return None
        ratio = self.devicePixelRatioF()
        target = QSize(max(1, round(rect.width() * ratio)), max(1, round(rect.height() * ratio)))
        # 縮小はサイズが変わったときだけやり直す
        if self._cache is None or self._cache.size() != target:
            scaled = self._source.scaled(
                target,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._cache = QPixmap.fromImage(scaled)
            self._cache.setDevicePixelRatio(ratio)
        return self._cache

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.crop_overlay.setGeometry(self.rect())
        self._guide_view.setGeometry(self.rect())
        if self._zoom is not None:
            self._clamp_zoom_offset()
        self._place_badge()
        self._place_histogram()

    # --- 描画 ---------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(MARGIN / 2, MARGIN / 2, -MARGIN / 2, -MARGIN / 2)
        palette = self.palette()
        highlight = palette.highlight().color()

        pixmap = self._zoom if self._zoom is not None else self.display_pixmap()
        has_alpha = (
            self._zoom_has_alpha
            if self._zoom is not None
            else self._source is not None and self._source.hasAlphaChannel()
        )
        if pixmap is not None:
            image_rect = self.image_rect()
            if has_alpha:
                # 透過部分が分かるよう、画像の範囲にだけ市松模様を敷いてから重ねる
                painter.setBrushOrigin(image_rect.topLeft())
                painter.fillRect(image_rect, self._checker_brush())
            painter.drawPixmap(image_rect.topLeft(), pixmap)
        else:
            pen = QPen(highlight if self._highlighted else palette.mid().color(), 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(frame, BORDER_RADIUS, BORDER_RADIUS)
            painter.setPen(palette.windowText().color())
            painter.drawText(frame, Qt.AlignmentFlag.AlignCenter, PLACEHOLDER_TEXT)

        if self._highlighted:
            fill = QColor(highlight)
            fill.setAlpha(HIGHLIGHT_FILL_ALPHA)
            painter.setPen(QPen(highlight, 3))
            painter.setBrush(fill)
            painter.drawRoundedRect(frame, BORDER_RADIUS, BORDER_RADIUS)
        painter.end()

    # --- 100% 表示の移動 ---------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if (
            self._zoom is not None
            and event is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._pan_from = (event.position(), QPointF(self._zoom_offset))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if self._zoom is not None and self._pan_from is not None and event is not None:
            start, offset = self._pan_from
            self._zoom_offset = offset + (event.position() - start)
            self._clamp_zoom_offset()
            self._place_badge()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if self._pan_from is not None:
            self._pan_from = None
            if self._zoom is not None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(event.position())
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if self._zoom is None or event is None:
            super().wheelEvent(event)
            return
        delta = event.pixelDelta()
        if delta.isNull():
            delta = event.angleDelta() / 4  # マウスのホイール（1 段 = 120）は 30px
        self._zoom_offset += QPointF(delta.x(), delta.y())
        self._clamp_zoom_offset()
        self._place_badge()
        self.update()
        event.accept()

    def _zoom_logical_size(self) -> QSize:
        if self._zoom is None:
            return QSize()
        ratio = self.devicePixelRatioF()
        return QSize(round(self._zoom.width() / ratio), round(self._zoom.height() / ratio))

    def _clamp_zoom_offset(self) -> None:
        """画像が表示より小さい向きは中央にそろえ、大きい向きははみ出し過ぎないよう止める。"""
        size = self._zoom_logical_size()
        x, y = self._zoom_offset.x(), self._zoom_offset.y()
        if size.width() <= self.width():
            x = (self.width() - size.width()) / 2
        else:
            x = min(0.0, max(float(self.width() - size.width()), x))
        if size.height() <= self.height():
            y = (self.height() - size.height()) / 2
        else:
            y = min(0.0, max(float(self.height() - size.height()), y))
        self._zoom_offset = QPointF(x, y)

    def _checker_brush(self) -> QBrush:
        """市松模様のブラシを返す。Retina でもぼやけないよう実ピクセルでタイルを作る。"""
        ratio = self.devicePixelRatioF()
        if self._checker is None or self._checker.texture().devicePixelRatio() != ratio:
            cell = round(CHECKER_SIZE * ratio)
            tile = QPixmap(cell * 2, cell * 2)
            tile.fill(CHECKER_LIGHT)
            tile_painter = QPainter(tile)
            tile_painter.fillRect(cell, 0, cell, cell, CHECKER_DARK)
            tile_painter.fillRect(0, cell, cell, cell, CHECKER_DARK)
            tile_painter.end()
            tile.setDevicePixelRatio(ratio)
            self._checker = QBrush(tile)
        return self._checker

    # --- D&D ----------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if event is not None and _accepts(event.mimeData()):
            event.acceptProposedAction()
            self._set_highlighted(True)
        elif event is not None:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        if event is not None and self._highlighted:
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent | None) -> None:
        self._set_highlighted(False)

    def dropEvent(self, event: QDropEvent | None) -> None:
        self._set_highlighted(False)
        if event is None or not _accepts(event.mimeData()):
            if event is not None:
                event.ignore()
            return
        event.acceptProposedAction()
        self.files_dropped.emit(local_paths(event.mimeData()))

    def _set_highlighted(self, highlighted: bool) -> None:
        if self._highlighted != highlighted:
            self._highlighted = highlighted
            self.update()


def local_paths(mime: QMimeData | None) -> list[Path]:
    """ドロップ・クリップボードの内容のうち、ローカルのファイルのパスを返す。"""
    if mime is None or not mime.hasUrls():
        return []
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


def _accepts(mime: QMimeData | None) -> bool:
    """先頭のローカルファイルが対応形式なら True（先頭の 1 枚だけを読み込むため）。"""
    paths = local_paths(mime)
    return bool(paths) and is_supported(paths[0])
