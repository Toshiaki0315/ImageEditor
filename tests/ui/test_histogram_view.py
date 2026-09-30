from PIL import Image
from PyQt6.QtCore import Qt

from image_editor.core.histogram import BINS, Histogram, compute_histogram
from image_editor.ui.drop_area import DropArea
from image_editor.ui.histogram_view import HistogramView, histogram_peak


def flat(value: int = 0) -> tuple[int, ...]:
    return (value,) * BINS


def test_peak_ignores_both_ends():
    red = list(flat(10))
    red[0] = 100000  # 黒つぶれ
    red[255] = 90000  # 白飛び
    red[128] = 50
    histogram = Histogram(tuple(red), flat(), flat(), flat(20))
    assert histogram_peak(histogram) == 50


def test_peak_minimum_is_one():
    assert histogram_peak(Histogram(flat(), flat(), flat(), flat())) == 1


def test_view_shows_and_hides(qtbot):
    view = HistogramView()
    qtbot.addWidget(view)
    assert view.histogram() is None
    assert not view.isVisible()

    histogram = compute_histogram(Image.effect_noise((64, 48), 40).convert("RGB"))
    view.show()
    view.set_histogram(histogram)

    assert view.histogram() == histogram
    assert view.isVisible()
    view.grab()  # 描画で落ちない

    view.set_histogram(None)
    assert not view.isVisible()


def test_drop_area_places_histogram_bottom_right(qtbot):
    area = DropArea()
    qtbot.addWidget(area)
    area.resize(800, 600)
    area.show()
    qtbot.waitExposed(area)
    area.set_image(Image.new("RGB", (400, 300)))

    area.set_histogram(compute_histogram(Image.new("RGB", (4, 4))))

    view = area.histogram_view
    assert view.isVisible()
    assert view.geometry().right() < area.width()
    assert view.geometry().bottom() < area.height()
    assert view.x() > area.width() / 2 and view.y() > area.height() / 2
    # 範囲選択のマスクより手前
    children = area.children()
    assert children.index(view) > children.index(area.crop_overlay)
    # マウス操作（範囲のドラッグ）は下に通す
    assert view.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
