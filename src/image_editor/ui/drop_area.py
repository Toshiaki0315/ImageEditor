"""D&D エリアとプレビュー表示。"""

from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QMimeData, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import QLabel, QWidget

from image_editor.core.io import is_supported
from image_editor.ui.crop_overlay import CropOverlay
from image_editor.ui.qt_image import pil_to_qimage

PLACEHOLDER_TEXT = "ここに画像をドロップしてください"
MARGIN = 16
BORDER_RADIUS = 12
HIGHLIGHT_FILL_ALPHA = 40
# 透過部分の市松模様（1 マスの大きさは論理ピクセル）
BADGE_MARGIN = 8  # 画像の左上から「加工前」などの表示までの間隔
BADGE_STYLE = (
    "QLabel { background: rgba(0, 0, 0, 160); color: white; border-radius: 4px; padding: 2px 8px; }"
)
CHECKER_SIZE = 8
CHECKER_LIGHT = QColor(255, 255, 255)
CHECKER_DARK = QColor(204, 204, 204)


class DropArea(QWidget):
    """画像ファイルのドロップを受け付け、画像を縦横比を保ってエリアに収めて表示する。

    読み込みは行わず、ドロップされたファイルを files_dropped シグナルで通知する。
    """

    files_dropped = pyqtSignal(list)  # list[Path]

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

    def _place_badge(self) -> None:
        image_rect = self.image_rect()
        origin = image_rect.topLeft() if not image_rect.isEmpty() else QRectF(self.rect()).topLeft()
        self.badge.move(round(origin.x()) + BADGE_MARGIN, round(origin.y()) + BADGE_MARGIN)

    def has_image(self) -> bool:
        """画像が設定されているかを返す。"""
        return self._source is not None

    def is_highlighted(self) -> bool:
        """ドラッグ中のハイライト表示中かを返す。"""
        return self._highlighted

    def image_rect(self) -> QRectF:
        """画像を描画する範囲（ウィジェット座標、論理ピクセル）を返す。画像がなければ空。"""
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
        self._place_badge()

    # --- 描画 ---------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(MARGIN / 2, MARGIN / 2, -MARGIN / 2, -MARGIN / 2)
        palette = self.palette()
        highlight = palette.highlight().color()

        pixmap = self.display_pixmap()
        if pixmap is not None:
            image_rect = self.image_rect()
            if self._source is not None and self._source.hasAlphaChannel():
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
        self.files_dropped.emit(_local_paths(event.mimeData()))

    def _set_highlighted(self, highlighted: bool) -> None:
        if self._highlighted != highlighted:
            self._highlighted = highlighted
            self.update()


def _local_paths(mime: QMimeData | None) -> list[Path]:
    if mime is None or not mime.hasUrls():
        return []
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


def _accepts(mime: QMimeData | None) -> bool:
    """先頭のローカルファイルが対応形式なら True（先頭の 1 枚だけを読み込むため）。"""
    paths = _local_paths(mime)
    return bool(paths) and is_supported(paths[0])
