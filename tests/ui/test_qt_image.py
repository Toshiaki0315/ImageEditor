import pytest
from PIL import Image
from PyQt6.QtGui import QColor, QImage

from image_editor.ui.qt_image import pil_to_qimage, pil_to_qpixmap


def test_rgb_to_qimage():
    image = Image.new("RGB", (30, 20), (10, 20, 30))
    image.putpixel((29, 19), (200, 100, 50))

    qimage = pil_to_qimage(image)

    assert (qimage.width(), qimage.height()) == (30, 20)
    assert not qimage.hasAlphaChannel()
    assert qimage.pixelColor(0, 0) == QColor(10, 20, 30)
    assert qimage.pixelColor(29, 19) == QColor(200, 100, 50)


def test_rgba_to_qimage_keeps_alpha():
    image = Image.new("RGBA", (4, 4), (255, 0, 0, 128))

    qimage = pil_to_qimage(image)

    assert qimage.hasAlphaChannel()
    assert qimage.format() == QImage.Format.Format_RGBA8888
    assert qimage.pixelColor(0, 0) == QColor(255, 0, 0, 128)


@pytest.mark.parametrize("mode", ["L", "P", "LA", "CMYK"])
def test_other_modes_are_converted(mode):
    qimage = pil_to_qimage(Image.new("RGB", (5, 5), (0, 128, 255)).convert(mode))
    assert (qimage.width(), qimage.height()) == (5, 5)


def test_qimage_owns_its_data():
    # 奇数幅（行末パディングが必要な幅）でも崩れず、元画像を消しても使える
    image = Image.new("RGB", (7, 3), (1, 2, 3))
    qimage = pil_to_qimage(image)
    del image

    assert qimage.pixelColor(6, 2) == QColor(1, 2, 3)


def test_pil_to_qpixmap(qtbot):
    pixmap = pil_to_qpixmap(Image.new("RGB", (12, 8)))
    assert (pixmap.width(), pixmap.height()) == (12, 8)
