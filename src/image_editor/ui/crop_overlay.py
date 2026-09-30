"""プレビュー上のドラッグによるトリミング範囲の選択。"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from image_editor.core.transform import CropRect, aspect_drag_rect, clamp_crop, oriented

MASK_COLOR = QColor(0, 0, 0, 120)
HANDLE_SIZE = 8  # ハンドルの描画サイズ（論理ピクセル）
HANDLE_HIT = 10  # ハンドルの当たり判定の半径


# --- 座標換算 -----------------------------------------------------------------


def widget_to_image(
    point: QPointF, image_rect: QRectF, image_size: tuple[int, int]
) -> tuple[int, int]:
    """ウィジェット座標を原画像の座標に換算する。画像外の点は画像の端にクランプする。"""
    width, height = image_size
    x = (point.x() - image_rect.x()) * width / image_rect.width()
    y = (point.y() - image_rect.y()) * height / image_rect.height()
    return (min(max(round(x), 0), width), min(max(round(y), 0), height))


def image_to_widget(x: float, y: float, image_rect: QRectF, image_size: tuple[int, int]) -> QPointF:
    """原画像の座標をウィジェット座標に換算する。"""
    width, height = image_size
    return QPointF(
        image_rect.x() + x * image_rect.width() / width,
        image_rect.y() + y * image_rect.height() / height,
    )


def crop_to_widget_rect(rect: CropRect, image_rect: QRectF, image_size: tuple[int, int]) -> QRectF:
    """トリミング範囲（原画像座標）をウィジェット上の矩形に換算する。"""
    top_left = image_to_widget(rect.x, rect.y, image_rect, image_size)
    bottom_right = image_to_widget(
        rect.x + rect.width, rect.y + rect.height, image_rect, image_size
    )
    return QRectF(top_left, bottom_right)


def rect_from_points(a: tuple[int, int], b: tuple[int, int]) -> CropRect:
    """2 点（原画像座標）を対角とする範囲を返す。"""
    left, right = sorted((a[0], b[0]))
    top, bottom = sorted((a[1], b[1]))
    return CropRect(left, top, right - left, bottom - top)


def move_rect(rect: CropRect, dx: int, dy: int, image_size: tuple[int, int]) -> CropRect:
    """範囲を大きさを保ったまま移動する。画像からはみ出さないよう位置を補正する。"""
    width, height = image_size
    x = min(max(rect.x + dx, 0), max(width - rect.width, 0))
    y = min(max(rect.y + dy, 0), max(height - rect.height, 0))
    return CropRect(x, y, rect.width, rect.height)


# --- ウィジェット -------------------------------------------------------------


class _DragMode(Enum):
    NEW = auto()
    MOVE = auto()
    RESIZE = auto()


@dataclass
class _Drag:
    mode: _DragMode
    anchor: tuple[int, int]  # NEW / RESIZE: 固定する点、MOVE: 押した点（原画像座標）
    start_rect: CropRect | None = None


class CropOverlay(QWidget):
    """プレビューの上に重ねて、ドラッグでトリミング範囲を選択するウィジェット。

    範囲外のドラッグで新規選択、範囲内のドラッグで移動、四隅のハンドルでサイズ変更する。
    縦横比が指定されていれば、新規選択とサイズ変更で比を保つ。
    範囲は原画像の座標系で扱い、変更のたびに crop_changed(CropRect | None) を発行する。
    """

    crop_changed = pyqtSignal(object)  # CropRect | None

    def __init__(self, image_rect: Callable[[], QRectF], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_rect = image_rect
        self._image_size: tuple[int, int] | None = None
        self._crop: CropRect | None = None
        self._drag: _Drag | None = None
        self._aspect: tuple[float, float] | None = None
        self._free_orientation = False
        self.setMouseTracking(True)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        """範囲選択を有効にする。無効の間はマウス操作を下のウィジェットに通す。"""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not active)
        self.setVisible(active)
        self._drag = None
        if active:
            self.raise_()

    def is_active(self) -> bool:
        """範囲選択が有効かを返す。"""
        return self.isVisible()

    def set_image_size(self, size: tuple[int, int] | None) -> None:
        """原画像のサイズを設定する。"""
        self._image_size = size
        self._crop = None
        self.update()

    def set_crop(self, rect: CropRect | None) -> None:
        """表示する範囲を設定する（シグナルは発行しない）。画像外は補正して表示する。"""
        if rect is not None and self._image_size is not None:
            rect = clamp_crop(rect, self._image_size)
        self._crop = rect
        self.update()

    def set_aspect(
        self, aspect: tuple[float, float] | None, free_orientation: bool = False
    ) -> None:
        """ドラッグで保つ縦横比 (幅, 高さ) を設定する。None なら自由。

        free_orientation なら向き（横長・縦長）はドラッグの形に合わせる（新規選択は
        ドラッグした方向、サイズ変更は元の範囲の向き）。
        """
        self._aspect = aspect
        self._free_orientation = free_orientation

    def aspect(self) -> tuple[float, float] | None:
        """ドラッグで保つ縦横比を返す。"""
        return self._aspect

    def crop(self) -> CropRect | None:
        """現在の範囲を返す。"""
        return self._crop

    def is_dragging(self) -> bool:
        """ドラッグ操作中かを返す。"""
        return self._drag is not None

    # --- マウス ---------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None or event.button() != Qt.MouseButton.LeftButton:
            return
        point = self._to_image(event.position())
        if point is None:
            return
        corner = self._hit_corner(event.position())
        if corner is not None and self._crop is not None:
            self._drag = _Drag(
                _DragMode.RESIZE, anchor=self._opposite_corner(corner), start_rect=self._crop
            )
        elif self._crop is not None and self._widget_crop_rect().contains(event.position()):
            self._drag = _Drag(_DragMode.MOVE, anchor=point, start_rect=self._crop)
        elif self._image_rect().contains(event.position()):
            self._drag = _Drag(_DragMode.NEW, anchor=point)
            self._set_crop_and_emit(None)
        # 画像の外（余白）からは選択を始めない

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._drag is None:
            self._update_cursor(event.position())
            return
        point = self._to_image(event.position())
        if point is None or self._image_size is None:
            return
        if self._drag.mode is _DragMode.MOVE:
            assert self._drag.start_rect is not None
            dx, dy = point[0] - self._drag.anchor[0], point[1] - self._drag.anchor[1]
            rect: CropRect | None = move_rect(self._drag.start_rect, dx, dy, self._image_size)
        elif self._aspect is not None:
            aspect = self._drag_aspect(self._aspect, point)
            rect = aspect_drag_rect(self._drag.anchor, point, aspect, self._image_size)
        else:
            rect = rect_from_points(self._drag.anchor, point)
        self._set_crop_and_emit(rect)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None or event.button() != Qt.MouseButton.LeftButton or self._drag is None:
            return
        # 離した位置まで反映する（移動イベントが間引かれても取りこぼさない）
        self.mouseMoveEvent(event)
        self._drag = None
        # 幅・高さが 0（クリックしただけ）ならトリミングなし
        if self._crop is not None and (self._crop.width <= 0 or self._crop.height <= 0):
            self._set_crop_and_emit(None)

    # --- 描画 ---------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        image_rect = self._image_rect()
        if self._image_size is None or image_rect.isEmpty() or self._crop is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selection = self._widget_crop_rect()

        # 範囲外を暗くする
        mask = QPainterPath()
        mask.addRect(image_rect)
        hole = QPainterPath()
        hole.addRect(selection)
        painter.fillPath(mask.subtracted(hole), MASK_COLOR)

        # 枠（明るい背景でも暗い背景でも見えるよう白線の外側に黒線）
        painter.setPen(QPen(QColor(0, 0, 0, 160), 3))
        painter.drawRect(selection)
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawRect(selection)

        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
        for corner in _corners(selection):
            painter.drawRect(
                QRectF(
                    corner.x() - HANDLE_SIZE / 2,
                    corner.y() - HANDLE_SIZE / 2,
                    HANDLE_SIZE,
                    HANDLE_SIZE,
                )
            )
        painter.end()

    # --- 内部 -----------------------------------------------------------------

    def _to_image(self, point: QPointF) -> tuple[int, int] | None:
        image_rect = self._image_rect()
        if self._image_size is None or image_rect.isEmpty():
            return None
        return widget_to_image(point, image_rect, self._image_size)

    def _drag_aspect(
        self, aspect: tuple[float, float], point: tuple[int, int]
    ) -> tuple[float, float]:
        """ドラッグ中に保つ縦横比を返す（向きを自由にするときは向きを決める）。"""
        if not self._free_orientation or self._drag is None:
            return aspect
        start = self._drag.start_rect
        if self._drag.mode is _DragMode.RESIZE and start is not None:
            landscape = start.width >= start.height
        else:
            anchor_x, anchor_y = self._drag.anchor
            landscape = abs(point[0] - anchor_x) >= abs(point[1] - anchor_y)
        return oriented(aspect, landscape)

    def _widget_crop_rect(self) -> QRectF:
        if self._crop is None or self._image_size is None:
            return QRectF()
        return crop_to_widget_rect(self._crop, self._image_rect(), self._image_size)

    def _hit_corner(self, point: QPointF) -> int | None:
        """point が四隅のハンドル上なら角の番号（左上から時計回り 0〜3）を返す。"""
        if self._crop is None:
            return None
        for index, corner in enumerate(_corners(self._widget_crop_rect())):
            if (
                abs(point.x() - corner.x()) <= HANDLE_HIT
                and abs(point.y() - corner.y()) <= HANDLE_HIT
            ):
                return index
        return None

    def _opposite_corner(self, corner: int) -> tuple[int, int]:
        assert self._crop is not None
        rect = self._crop
        left, top = rect.x, rect.y
        right, bottom = rect.x + rect.width, rect.y + rect.height
        return [(right, bottom), (left, bottom), (left, top), (right, top)][corner]

    def _update_cursor(self, point: QPointF) -> None:
        corner = self._hit_corner(point)
        if corner in (0, 2):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif corner in (1, 3):
            shape = Qt.CursorShape.SizeBDiagCursor
        elif self._crop is not None and self._widget_crop_rect().contains(point):
            shape = Qt.CursorShape.SizeAllCursor
        elif self._image_rect().contains(point):
            shape = Qt.CursorShape.CrossCursor
        else:
            shape = Qt.CursorShape.ArrowCursor
        self.setCursor(shape)

    def _set_crop_and_emit(self, rect: CropRect | None) -> None:
        if rect == self._crop:
            return
        self._crop = rect
        self.update()
        self.crop_changed.emit(rect)


def _corners(rect: QRectF) -> list[QPointF]:
    """左上・右上・右下・左下の順に角を返す。"""
    return [rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]
