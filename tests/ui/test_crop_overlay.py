import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt

from image_editor.core.shapes import ShapeType
from image_editor.core.transform import CropRect
from image_editor.ui.crop_overlay import (
    crop_to_widget_rect,
    image_to_widget,
    move_rect,
    rect_from_points,
    shape_path,
    widget_to_image,
)
from image_editor.ui.drop_area import DropArea

# --- 座標換算 -----------------------------------------------------------------

# 1000x500 の画像を (50, 20) から 400x200 で表示（縮小率 0.4）
IMAGE_RECT = QRectF(50, 20, 400, 200)
IMAGE_SIZE = (1000, 500)


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((50, 20), (0, 0)),
        ((450, 220), (1000, 500)),
        ((250, 120), (500, 250)),
        ((50.4, 20.4), (1, 1)),  # 0.4 / 0.4 = 1
        ((50.1, 20.1), (0, 0)),  # 0.25 → 0
    ],
)
def test_widget_to_image(point, expected):
    assert widget_to_image(QPointF(*point), IMAGE_RECT, IMAGE_SIZE) == expected


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((0, 0), (0, 0)),  # 左上の余白
        ((1000, 1000), (1000, 500)),  # 右下の外
        ((-50, 100), (0, 200)),  # 左の外
        ((300, -10), (625, 0)),  # 上の外
    ],
)
def test_widget_to_image_clamps(point, expected):
    assert widget_to_image(QPointF(*point), IMAGE_RECT, IMAGE_SIZE) == expected


def test_image_to_widget():
    assert image_to_widget(0, 0, IMAGE_RECT, IMAGE_SIZE) == QPointF(50, 20)
    assert image_to_widget(1000, 500, IMAGE_RECT, IMAGE_SIZE) == QPointF(450, 220)
    assert image_to_widget(250, 125, IMAGE_RECT, IMAGE_SIZE) == QPointF(150, 70)


@pytest.mark.parametrize("xy", [(0, 0), (1, 1), (123, 456), (999, 499), (1000, 500)])
def test_round_trip(xy):
    widget_point = image_to_widget(*xy, IMAGE_RECT, IMAGE_SIZE)
    assert widget_to_image(widget_point, IMAGE_RECT, IMAGE_SIZE) == xy


def test_crop_to_widget_rect():
    rect = crop_to_widget_rect(CropRect(100, 50, 500, 250), IMAGE_RECT, IMAGE_SIZE)
    assert rect == QRectF(90, 40, 200, 100)


def test_rect_from_points_normalizes():
    assert rect_from_points((300, 200), (100, 50)) == CropRect(100, 50, 200, 150)
    assert rect_from_points((10, 10), (10, 30)) == CropRect(10, 10, 0, 20)


@pytest.mark.parametrize(
    ("dx", "dy", "expected"),
    [
        (10, 20, CropRect(110, 70, 200, 100)),
        (-500, 0, CropRect(0, 50, 200, 100)),  # 左端で止まる
        (5000, 5000, CropRect(800, 400, 200, 100)),  # 右下で止まる（大きさは維持）
    ],
)
def test_move_rect(dx, dy, expected):
    assert move_rect(CropRect(100, 50, 200, 100), dx, dy, IMAGE_SIZE) == expected


# --- ウィジェット -------------------------------------------------------------


@pytest.fixture
def area(qtbot):
    widget = DropArea()
    qtbot.addWidget(widget)
    widget.resize(632, 432)  # 表示範囲 600x400
    widget.show()
    qtbot.waitExposed(widget)
    # 1200x800 → 600x400 で (16, 16) に表示（縮小率 0.5）
    widget.set_image(Image.new("RGB", (1200, 800)))
    widget.crop_overlay.set_image_size((1200, 800))
    widget.crop_overlay.set_active(True)
    return widget


@pytest.fixture
def emitted(area):
    received: list[CropRect | None] = []
    area.crop_overlay.crop_changed.connect(received.append)
    return received


def at(x: int, y: int) -> QPoint:
    """原画像座標 (x, y) に対応するウィジェット座標（縮小率 0.5、余白 16）。"""
    return QPoint(16 + x // 2, 16 + y // 2)


def drag(qtbot, widget, start: QPoint, end: QPoint, steps: int = 3) -> None:
    qtbot.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
    for i in range(1, steps + 1):
        point = start + (end - start) * (i / steps)
        qtbot.mouseMove(widget, point)
    qtbot.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)


def test_overlay_covers_drop_area(area):
    assert area.crop_overlay.geometry() == area.rect()
    assert area.crop_overlay.is_active()


def test_inactive_overlay_passes_mouse_through(area):
    area.crop_overlay.set_active(False)
    assert area.crop_overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert not area.crop_overlay.isVisible()


def test_drag_creates_selection(qtbot, area, emitted):
    overlay = area.crop_overlay

    drag(qtbot, overlay, at(200, 100), at(800, 500))

    assert overlay.crop() == CropRect(200, 100, 600, 400)
    assert emitted[-1] == CropRect(200, 100, 600, 400)
    assert len(emitted) > 1  # ドラッグ中も逐次通知する
    overlay.grab()  # マスク・ハンドルの描画で落ちない


def test_drag_backwards(qtbot, area):
    drag(qtbot, area.crop_overlay, at(800, 500), at(200, 100))
    assert area.crop_overlay.crop() == CropRect(200, 100, 600, 400)


def test_drag_outside_image_is_clamped(qtbot, area):
    drag(qtbot, area.crop_overlay, at(600, 400), QPoint(700, 500))  # 右下の外まで
    assert area.crop_overlay.crop() == CropRect(600, 400, 600, 400)

    # 画像内から左上の余白までドラッグしても画像の端で止まる
    # （QTest は QPoint(0, 0) をウィジェット中央として扱うので (1, 1) を使う）
    drag(qtbot, area.crop_overlay, at(100, 100), QPoint(1, 1))
    assert area.crop_overlay.crop() == CropRect(0, 0, 100, 100)


def test_drag_from_margin_does_not_start_selection(qtbot, area, emitted):
    overlay = area.crop_overlay
    overlay.set_crop(CropRect(200, 200, 400, 200))

    # 画像の外（上の余白は y < 16）からのドラッグは無視する
    drag(qtbot, overlay, QPoint(300, 5), at(800, 500))

    assert overlay.crop() == CropRect(200, 200, 400, 200)
    assert emitted == []
    assert not overlay.is_dragging()


def test_click_clears_selection(qtbot, area, emitted):
    area.crop_overlay.set_crop(CropRect(0, 0, 100, 100))

    drag(qtbot, area.crop_overlay, at(600, 600), at(600, 600))

    assert area.crop_overlay.crop() is None
    assert emitted[-1] is None


def test_drag_inside_moves_selection(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_crop(CropRect(200, 200, 400, 200))

    drag(qtbot, overlay, at(400, 300), at(500, 400))

    assert overlay.crop() == CropRect(300, 300, 400, 200)


def test_move_stops_at_edge(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_crop(CropRect(200, 200, 400, 200))

    drag(qtbot, overlay, at(400, 300), QPoint(1000, 1000))

    assert overlay.crop() == CropRect(800, 600, 400, 200)


@pytest.mark.parametrize(
    ("corner", "target", "expected"),
    [
        ((200, 200), (100, 100), CropRect(100, 100, 500, 300)),  # 左上
        ((600, 200), (800, 100), CropRect(200, 100, 600, 300)),  # 右上
        ((600, 400), (1000, 600), CropRect(200, 200, 800, 400)),  # 右下
        ((200, 400), (100, 500), CropRect(100, 200, 500, 300)),  # 左下
    ],
)
def test_corner_handle_resizes(qtbot, area, corner, target, expected):
    overlay = area.crop_overlay
    overlay.set_crop(CropRect(200, 200, 400, 200))

    drag(qtbot, overlay, at(*corner), at(*target))

    assert overlay.crop() == expected


def test_corner_drag_past_opposite_flips(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_crop(CropRect(200, 200, 400, 200))

    # 右下のハンドルを左上の角より先まで
    drag(qtbot, overlay, at(600, 400), at(100, 100))

    assert overlay.crop() == CropRect(100, 100, 100, 100)


def test_set_crop_does_not_emit(area, emitted):
    area.crop_overlay.set_crop(CropRect(10, 10, 20, 20))
    assert emitted == []


def test_set_crop_clamps_for_display(area):
    area.crop_overlay.set_crop(CropRect(1100, 700, 500, 500))
    assert area.crop_overlay.crop() == CropRect(1100, 700, 100, 100)


def test_cursor_changes_on_hover(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_crop(CropRect(200, 200, 400, 200))

    qtbot.mouseMove(overlay, at(200, 200))
    assert overlay.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    qtbot.mouseMove(overlay, at(400, 300))
    assert overlay.cursor().shape() == Qt.CursorShape.SizeAllCursor
    qtbot.mouseMove(overlay, at(1000, 700))
    assert overlay.cursor().shape() == Qt.CursorShape.CrossCursor
    qtbot.mouseMove(overlay, QPoint(300, 5))  # 画像の外（余白）
    assert overlay.cursor().shape() == Qt.CursorShape.ArrowCursor


# --- 縦横比 -------------------------------------------------------------------


def test_drag_keeps_aspect(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_aspect((1, 1))

    drag(qtbot, overlay, at(200, 100), at(800, 300))

    # 横に長いドラッグ → 幅 600 に合わせた正方形
    assert overlay.crop() == CropRect(200, 100, 600, 600)


def test_drag_keeps_aspect_at_image_edge(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_aspect((16, 9))

    drag(qtbot, overlay, at(600, 400), QPoint(700, 500))  # 右下の外まで

    rect = overlay.crop()
    assert rect is not None
    assert rect.x + rect.width <= 1200 and rect.y + rect.height <= 800
    assert abs(rect.height - rect.width * 9 / 16) <= 1


def test_handle_resize_keeps_aspect(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_aspect((4, 3))
    overlay.set_crop(CropRect(200, 200, 400, 300))

    drag(qtbot, overlay, at(600, 500), at(1000, 520))  # 右下のハンドルを右へ

    assert overlay.crop() == CropRect(200, 200, 800, 600)


def test_free_orientation_follows_drag(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_aspect((46, 62), free_orientation=True)

    drag(qtbot, overlay, at(100, 100), at(720, 300))  # 横に長いドラッグ
    landscape = overlay.crop()
    drag(qtbot, overlay, at(900, 100), at(1000, 700))  # 縦に長いドラッグ
    portrait = overlay.crop()

    assert landscape is not None and landscape.width > landscape.height
    assert portrait is not None and portrait.height > portrait.width


def test_free_orientation_resize_keeps_orientation(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_aspect((46, 62), free_orientation=True)
    overlay.set_crop(CropRect(100, 100, 460, 620))

    drag(qtbot, overlay, at(560, 720), at(700, 730))  # 右下のハンドルを横へ

    rect = overlay.crop()
    assert rect is not None and rect.height > rect.width


def test_move_ignores_aspect(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_aspect((1, 1))
    overlay.set_crop(CropRect(200, 200, 300, 300))

    drag(qtbot, overlay, at(300, 300), at(400, 350))

    assert overlay.crop() == CropRect(300, 250, 300, 300)


# --- 形（角丸・円）のマスク -------------------------------------------------------


def test_shape_path_rectangle_is_none():
    rect = QRectF(0, 0, 200, 100)
    assert shape_path(rect, ShapeType.RECTANGLE, 30) is None
    assert shape_path(rect, ShapeType.ROUNDED, 0) is None


def test_shape_path_rounded():
    rect = QRectF(10, 20, 200, 100)
    path = shape_path(rect, ShapeType.ROUNDED, 20)  # 半径 = 短辺 100 × 20% = 20

    assert path is not None
    assert path.boundingRect() == rect
    assert not path.contains(QPointF(12, 22))  # 角は外
    assert path.contains(QPointF(10 + 20, 20 + 20))  # 円弧の中心は内
    assert path.contains(QPointF(110, 21))  # 辺の中ほどは内


def test_shape_path_circle_is_centered_on_short_side():
    path = shape_path(QRectF(0, 0, 300, 100), ShapeType.CIRCLE, 10)
    assert path is not None
    assert path.boundingRect() == QRectF(100, 0, 100, 100)


def test_overlay_shows_shape_without_crop(qtbot, area):
    overlay = area.crop_overlay
    assert overlay.shape_outline() is None

    overlay.set_shape(ShapeType.ROUNDED, 25, None)

    outline = overlay.shape_outline()
    assert outline is not None
    assert outline.boundingRect() == area.image_rect()  # 範囲がなければ画像全体
    overlay.grab()  # 範囲なしでもマスク・輪郭の描画で落ちない


def test_overlay_shape_uses_area(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_crop(CropRect(200, 200, 400, 200))

    overlay.set_shape(ShapeType.CIRCLE, 0, CropRect(200, 200, 400, 200))

    outline = overlay.shape_outline()
    assert outline is not None
    # 原画像の (300, 200)〜(500, 400) の正円（縮小率 0.5、余白 16）
    assert outline.boundingRect() == QRectF(16 + 150, 16 + 100, 100, 100)
    overlay.grab()


def test_overlay_drag_still_works_with_shape(qtbot, area):
    overlay = area.crop_overlay
    overlay.set_shape(ShapeType.ROUNDED, 20, None)

    drag(qtbot, overlay, at(200, 100), at(800, 500))

    assert overlay.crop() == CropRect(200, 100, 600, 400)
