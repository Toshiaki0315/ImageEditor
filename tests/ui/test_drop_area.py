from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from image_editor.core.diorama import DioramaSettings, diorama_band
from image_editor.ui.drop_area import DioramaGuide, DropArea


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


# --- 左上の表示（「加工前」など） -----------------------------------------------


def test_badge(qtbot):
    area = DropArea()
    qtbot.addWidget(area)
    area.resize(632, 432)
    area.show()
    qtbot.waitExposed(area)
    area.set_image(Image.new("RGB", (1200, 800)))
    assert area.badge_text() is None

    area.set_badge("加工前")

    assert area.badge_text() == "加工前"
    # 画像の左上から少し内側で、範囲選択のマスクより手前
    image_rect = area.image_rect()
    assert area.badge.x() >= image_rect.x()
    assert area.badge.y() >= image_rect.y()
    children = area.children()
    assert children.index(area.badge) > children.index(area.crop_overlay)

    area.set_badge(None)
    assert area.badge_text() is None


# --- 100% 表示 ----------------------------------------------------------------------


@pytest.fixture
def zoom_area(qtbot):
    area = DropArea()
    qtbot.addWidget(area)
    area.resize(400, 300)
    area.show()
    qtbot.waitExposed(area)
    area.set_image(Image.new("RGB", (100, 75)))
    return area


def big_image(size=(2000, 1600)) -> Image.Image:
    image = Image.new("RGB", size, (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, size[0] // 2, size[1]))
    return image


def test_zoom_shows_one_image_pixel_per_device_pixel(zoom_area):
    zoom_area.set_zoom_image(big_image())

    assert zoom_area.is_zoomed()
    ratio = zoom_area.devicePixelRatioF()
    rect = zoom_area.image_rect()
    assert rect.width() == pytest.approx(2000 / ratio, abs=1)
    assert rect.height() == pytest.approx(1600 / ratio, abs=1)
    # 最初は画像の中央を見せる
    center = zoom_area.zoom_center()
    assert center == pytest.approx((1000, 800), abs=ratio * 2)
    zoom_area.grab()  # 描画で落ちない


def test_zoom_center_and_keep_position(zoom_area):
    zoom_area.set_zoom_image(big_image(), center=(300, 400))
    assert zoom_area.zoom_center() == pytest.approx((300, 400), abs=4)

    # 同じ大きさの画像で更新しても、見ている場所は変わらない
    zoom_area.set_zoom_image(big_image())
    assert zoom_area.zoom_center() == pytest.approx((300, 400), abs=4)


def test_zoom_offset_is_clamped(zoom_area):
    zoom_area.set_zoom_image(big_image(), center=(0, 0))
    offset = zoom_area.zoom_offset()
    assert (offset.x(), offset.y()) == (0, 0)  # 左上より外は見せない

    zoom_area.set_zoom_image(Image.new("RGB", (50, 40)))  # 表示より小さい画像は中央
    rect = zoom_area.image_rect()
    assert rect.center().x() == pytest.approx(200, abs=1)
    assert rect.center().y() == pytest.approx(150, abs=1)


def test_zoom_drag_pans(qtbot, zoom_area):
    zoom_area.set_zoom_image(big_image())
    before = zoom_area.zoom_offset()

    qtbot.mousePress(zoom_area, Qt.MouseButton.LeftButton, pos=QPoint(200, 150))
    qtbot.mouseMove(zoom_area, QPoint(150, 120))
    qtbot.mouseRelease(zoom_area, Qt.MouseButton.LeftButton, pos=QPoint(150, 120))

    after = zoom_area.zoom_offset()
    assert (after.x() - before.x(), after.y() - before.y()) == (-50, -30)


def test_zoom_wheel_pans(zoom_area):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent

    zoom_area.set_zoom_image(big_image())
    before = zoom_area.zoom_offset()
    event = QWheelEvent(
        QPointF(200, 150),
        QPointF(200, 150),
        QPoint(0, -40),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )

    zoom_area.wheelEvent(event)

    assert zoom_area.zoom_offset().y() == before.y() - 40


def test_leave_zoom(zoom_area):
    zoom_area.set_zoom_image(big_image())
    zoom_area.set_zoom_image(None)
    assert not zoom_area.is_zoomed()
    assert zoom_area.image_rect().width() <= 400


def test_double_click_signal(qtbot, zoom_area):
    with qtbot.waitSignal(zoom_area.double_clicked) as blocker:
        qtbot.mouseDClick(zoom_area, Qt.MouseButton.LeftButton, pos=QPoint(10, 20))
    assert (blocker.args[0].x(), blocker.args[0].y()) == (10, 20)


def test_accepts_heic(qtbot, tmp_path):
    from image_editor.ui.drop_area import _accepts

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "IMG_0001.HEIC"))])
    assert _accepts(mime)


# --- ジオラマのガイド ---------------------------------------------------------------


def make_guide(horizontal: bool = True) -> DioramaGuide:
    band = diorama_band(DioramaSettings(position=50, width=20))
    return DioramaGuide(area=(0.0, 0.5, 1.0, 0.5), horizontal=horizontal, band=band)


def test_guide_lines_are_relative_to_photo_area():
    lines = make_guide().lines()
    # 写真は下半分 (0.5〜1.0)。帯は写真の 40〜60% → 画像の 0.7〜0.8
    assert [solid for _, solid in lines] == [False, True, True, False]
    assert [f for f, solid in lines if solid] == pytest.approx([0.7, 0.8])


def test_set_and_clear_guide(area):
    area.set_image(Image.new("RGB", (300, 200), (40, 40, 40)))
    assert area.diorama_guide() is None

    guide = make_guide()
    area.set_diorama_guide(guide)
    assert area.diorama_guide() == guide

    # 帯の端（画像の 70% の高さ）に、ガイドの色の線が描かれる
    rect = area.image_rect()
    y = round(rect.y() + 0.7 * rect.height())
    x = round(rect.center().x())
    pixels = area.grab().toImage()
    ratio = pixels.devicePixelRatio()
    colors = {
        pixels.pixelColor(round(x * ratio), round((y + dy) * ratio)).getRgb()[:3]
        for dy in (-1, 0, 1)
    }
    assert any(r > 200 and g > 150 and b < 100 for r, g, b in colors)

    area.set_diorama_guide(None)
    assert area.diorama_guide() is None


def test_guide_does_not_block_mouse(area):
    area.set_image(Image.new("RGB", (300, 200)))
    area.set_diorama_guide(make_guide(horizontal=False))
    assert area._guide_view.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
