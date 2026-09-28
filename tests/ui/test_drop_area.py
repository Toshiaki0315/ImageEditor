from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from image_editor.ui.drop_area import DropArea


@pytest.fixture
def area(qtbot):
    widget = DropArea()
    qtbot.addWidget(widget)
    widget.resize(632, 432)  # 余白 16px を除いた表示範囲は 600x400
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def make_mime(*items: str | Path) -> QMimeData:
    mime = QMimeData()
    urls = [QUrl(i) if isinstance(i, str) else QUrl.fromLocalFile(str(i)) for i in items]
    mime.setUrls(urls)
    return mime


def drag_enter(area: DropArea, mime: QMimeData) -> QDragEnterEvent:
    event = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.setAccepted(False)
    area.dragEnterEvent(event)
    return event


def drop(area: DropArea, mime: QMimeData) -> QDropEvent:
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.setAccepted(False)
    area.dropEvent(event)
    return event


# --- 画像表示 -----------------------------------------------------------------


def test_initially_empty(area):
    assert not area.has_image()
    assert area.image_rect().isEmpty()
    assert area.display_pixmap() is None
    area.grab()  # 未読込の描画（点線枠）で落ちない


def test_set_image_shows_pixmap(area):
    area.set_image(Image.new("RGB", (1200, 400), (255, 0, 0)))

    pixmap = area.display_pixmap()

    assert area.has_image()
    assert pixmap is not None
    ratio = area.devicePixelRatioF()
    assert pixmap.devicePixelRatio() == ratio
    # 600x400 の範囲に 3:1 で収める → 600x200（論理ピクセル）
    assert pixmap.width() == round(600 * ratio)
    assert pixmap.height() == round(200 * ratio)
    area.grab()


def test_image_rect_keeps_aspect_and_centers(area):
    area.set_image(Image.new("RGB", (100, 200)))

    rect = area.image_rect()

    assert (rect.width(), rect.height()) == (200, 400)
    assert (rect.x(), rect.y()) == (16 + 200, 16)


def test_small_image_is_fit_to_area(area):
    area.set_image(Image.new("RGB", (30, 20)))
    rect = area.image_rect()
    assert (rect.width(), rect.height()) == (600, 400)


def test_follows_resize(area, qtbot):
    area.set_image(Image.new("RGB", (400, 400)))
    before = area.display_pixmap()

    area.resize(332, 332)

    rect = area.image_rect()
    assert (rect.width(), rect.height()) == (300, 300)
    after = area.display_pixmap()
    assert after is not None and before is not None
    assert after.size() != before.size()


def test_cache_is_reused(area):
    area.set_image(Image.new("RGB", (400, 400)))
    assert area.display_pixmap() is area.display_pixmap()


def test_set_image_none_clears(area):
    area.set_image(Image.new("RGB", (10, 10)))
    area.set_image(None)
    assert not area.has_image()


def test_rgba_image(area):
    area.set_image(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
    pixmap = area.display_pixmap()
    assert pixmap is not None and pixmap.hasAlphaChannel()


# --- D&D ----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a.png", "a.JPG", "a.jpeg", "a.gif", "a.tiff", "a.bmp"])
def test_drag_supported_file_is_accepted(area, tmp_path, name):
    event = drag_enter(area, make_mime(tmp_path / name))

    assert event.isAccepted()
    assert area.is_highlighted()


@pytest.mark.parametrize(
    "items",
    [
        ("a.webp",),
        ("a.txt", "b.png"),  # 先頭が非対応
        ("https://example.com/a.png",),  # ローカルファイルではない
    ],
)
def test_drag_unsupported_is_rejected(area, tmp_path, items):
    mime = make_mime(*[i if i.startswith("http") else tmp_path / i for i in items])

    event = drag_enter(area, mime)

    assert not event.isAccepted()
    assert not area.is_highlighted()


def test_drag_text_is_rejected(area):
    mime = QMimeData()
    mime.setText("hello")
    assert not drag_enter(area, mime).isAccepted()


def test_drag_leave_clears_highlight(area, tmp_path):
    drag_enter(area, make_mime(tmp_path / "a.png"))
    area.grab()  # ハイライト描画で落ちない

    area.dragLeaveEvent(None)

    assert not area.is_highlighted()


def test_drop_emits_paths(area, qtbot, tmp_path):
    paths = [tmp_path / "a.png", tmp_path / "b.jpg"]
    drag_enter(area, make_mime(*paths))

    with qtbot.waitSignal(area.files_dropped) as blocker:
        event = drop(area, make_mime(*paths))

    assert event.isAccepted()
    assert blocker.args == [paths]
    assert not area.is_highlighted()


def test_drop_unsupported_does_not_emit(area, qtbot, tmp_path):
    with qtbot.assertNotEmitted(area.files_dropped):
        event = drop(area, make_mime(tmp_path / "a.webp"))
    assert not event.isAccepted()


# --- 透過部分の市松模様 ---------------------------------------------------------


def rendered(area):
    """ウィジェットを描画した画像と、論理座標から実ピクセルへの倍率を返す。"""
    pixmap = area.grab()
    return pixmap.toImage(), pixmap.devicePixelRatio()


def color_at(image, ratio, x, y):
    return image.pixelColor(int(x * ratio), int(y * ratio)).getRgb()[:3]


def test_transparent_area_shows_checkerboard(area):
    # 1200x800 → (16, 16) から 600x400 で表示
    area.set_image(Image.new("RGBA", (1200, 800), (0, 0, 0, 0)))

    image, ratio = rendered(area)

    light, dark = (255, 255, 255), (204, 204, 204)
    assert color_at(image, ratio, 16 + 2, 16 + 2) == light
    assert color_at(image, ratio, 16 + 8 + 2, 16 + 2) == dark
    assert color_at(image, ratio, 16 + 2, 16 + 8 + 2) == dark
    assert color_at(image, ratio, 16 + 8 + 2, 16 + 8 + 2) == light
    assert color_at(image, ratio, 16 + 600 - 3, 16 + 400 - 3) in (light, dark)


def test_checkerboard_is_only_inside_image(area):
    # 縦長の画像 → 左右に余白ができる
    area.set_image(Image.new("RGBA", (100, 200), (0, 0, 0, 0)))
    background = area.palette().window().color().getRgb()[:3]

    image, ratio = rendered(area)

    rect = area.image_rect()
    assert color_at(image, ratio, rect.x() - 20, 200) == background
    assert color_at(image, ratio, rect.right() + 20, 200) == background


def test_semi_transparent_shows_checkerboard_through(area):
    area.set_image(Image.new("RGBA", (1200, 800), (255, 0, 0, 128)))

    image, ratio = rendered(area)

    # 赤が半分透けて、白マスと灰マスで色が変わる
    on_light = color_at(image, ratio, 16 + 2, 16 + 2)
    on_dark = color_at(image, ratio, 16 + 8 + 2, 16 + 2)
    assert on_light != on_dark
    assert on_light[0] > on_light[1] and on_dark[0] > on_dark[1]


def test_opaque_image_is_unchanged(area):
    area.set_image(Image.new("RGB", (1200, 800), (10, 120, 200)))

    image, ratio = rendered(area)

    assert color_at(image, ratio, 16 + 2, 16 + 2) == (10, 120, 200)
    assert color_at(image, ratio, 16 + 8 + 2, 16 + 2) == (10, 120, 200)
