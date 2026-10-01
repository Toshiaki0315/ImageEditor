"""PIL.Image <-> Qt の画像の変換。"""

from PIL import Image
from PyQt6.QtGui import QImage, QPixmap

from image_editor.core.io import normalize_mode


def pil_to_qimage(image: Image.Image) -> QImage:
    """PIL 画像を QImage に変換する（RGB / RGBA 以外は先に正規化する）。

    返す QImage は画素データを自前で持つので、元の PIL 画像を解放しても壊れない。
    """
    image = normalize_mode(image)
    if image.mode == "RGBA":
        image_format, channels = QImage.Format.Format_RGBA8888, 4
    else:
        image_format, channels = QImage.Format.Format_RGB888, 3
    width, height = image.size
    data = image.tobytes()
    # QImage(bytes, ...) は data を参照するだけなので copy() で所有させる
    return QImage(data, width, height, width * channels, image_format).copy()


def qimage_to_pil(qimage: QImage) -> Image.Image:
    """QImage を PIL 画像（透過ありなら RGBA、なければ RGB）に変換する。

    返す画像は画素データを自前で持つので、元の QImage を解放しても壊れない。
    """
    if qimage.hasAlphaChannel():
        converted, mode = qimage.convertToFormat(QImage.Format.Format_RGBA8888), "RGBA"
    else:
        converted, mode = qimage.convertToFormat(QImage.Format.Format_RGB888), "RGB"
    width, height = converted.width(), converted.height()
    stride = converted.bytesPerLine()
    bits = converted.constBits()
    if bits is None or width == 0 or height == 0:
        raise ValueError("画像が空です")
    data = bits.asstring(stride * height)
    return Image.frombuffer(mode, (width, height), data, "raw", mode, stride, 1).copy()


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """PIL 画像を QPixmap に変換する。"""
    return QPixmap.fromImage(pil_to_qimage(image))
