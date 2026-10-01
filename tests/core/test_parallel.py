import subprocess
import sys

import pytest
from PIL import Image, ImageChops, ImageFilter

from image_editor.core import parallel
from image_editor.core.parallel import filter_image

FILTERS = [
    ImageFilter.GaussianBlur(0.6),
    ImageFilter.GaussianBlur(3),
    ImageFilter.GaussianBlur(25),
    ImageFilter.GaussianBlur((2, 6)),
    ImageFilter.BoxBlur(4),
    ImageFilter.UnsharpMask(radius=1.5, percent=150, threshold=2),
    ImageFilter.UnsharpMask(radius=20, percent=90, threshold=0),
]


def make_image(size=(900, 701), mode="RGB") -> Image.Image:
    noise = Image.effect_noise(size, 60)
    image = Image.merge("RGB", (noise, noise.rotate(90).resize(size), noise.transpose(0)))
    return image.convert(mode)


@pytest.mark.parametrize("image_filter", FILTERS)
def test_same_as_filtering_at_once(image_filter):
    image = make_image()
    expected = image.filter(image_filter)

    result = filter_image(image, image_filter)

    assert result.size == image.size and result.mode == image.mode
    assert ImageChops.difference(result, expected).getbbox() is None


@pytest.mark.parametrize("mode", ["L", "RGBA"])
def test_other_modes(mode):
    image = make_image(mode=mode)
    image_filter = ImageFilter.GaussianBlur(4)
    assert filter_image(image, image_filter).tobytes() == image.filter(image_filter).tobytes()


@pytest.mark.parametrize("size", [(1, 1), (300, 1), (1, 900), (40, 30)])
def test_small_and_thin_images(size):
    image = make_image(size)
    image_filter = ImageFilter.GaussianBlur(2)
    assert filter_image(image, image_filter).tobytes() == image.filter(image_filter).tobytes()


def test_uses_strips_for_large_images(monkeypatch):
    calls = []
    original = Image.Image.crop

    def crop(self, box=None):
        calls.append(box)
        return original(self, box)

    monkeypatch.setattr(Image.Image, "crop", crop)
    filter_image(make_image((800, 800)), ImageFilter.GaussianBlur(2))

    assert len(calls) >= min(parallel.WORKERS, 2)


def test_input_is_not_modified():
    image = make_image()
    before = image.tobytes()
    filter_image(image, ImageFilter.GaussianBlur(5))
    assert image.tobytes() == before


def test_core_parallel_does_not_import_qt():
    code = (
        "import sys, image_editor.core.parallel; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
