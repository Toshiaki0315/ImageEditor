"""重いフィルター（ぼかしなど）を、画像を帯に分けて並列にかける。

Pillow はフィルターの計算中に GIL を外すので、帯ごとにスレッドで処理すると速くなる。
帯の上下には、ぼかしが届く分の「のりしろ」を付けて処理し、のりしろを除いて
つなぎ合わせるので、結果は画像全体に一度にかけたときと同じになる。
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageFilter

# 並列に処理するスレッドの数（CPU の数まで、多くても 8）
WORKERS = max(1, min(8, os.cpu_count() or 1))
# これより画素数が少ない画像は、分けずに一度にかける（分ける手間のほうが大きい）
MIN_PIXELS = 256 * 256
# のりしろ（px）= 半径 × この倍率 + 2。ガウスぼかし（3 回の箱ぼかし）が届く範囲より広く取る
MARGIN_PER_RADIUS = 4

_executor = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="image-filter")

RadiusFilter = ImageFilter.GaussianBlur | ImageFilter.BoxBlur | ImageFilter.UnsharpMask


def filter_image(image: Image.Image, image_filter: RadiusFilter) -> Image.Image:
    """image に image_filter をかけた新しい画像を返す（入力画像は変更しない）。

    大きい画像は帯に分けて並列に処理する。結果は image.filter(image_filter) と同じ。
    """
    width, height = image.size
    strips = min(WORKERS, height)
    if strips <= 1 or width * height < MIN_PIXELS:
        return image.filter(image_filter)

    margin = math.ceil(_radius(image_filter) * MARGIN_PER_RADIUS) + 2
    step = math.ceil(height / strips)

    def work(top: int) -> tuple[int, Image.Image]:
        bottom = min(height, top + step)
        outer_top, outer_bottom = max(0, top - margin), min(height, bottom + margin)
        filtered = image.crop((0, outer_top, width, outer_bottom)).filter(image_filter)
        inner = (0, top - outer_top, width, top - outer_top + (bottom - top))
        return top, filtered.crop(inner)

    result = Image.new(image.mode, image.size)
    for top, strip in _executor.map(work, range(0, height, step)):
        result.paste(strip, (0, top))
    return result


def _radius(image_filter: RadiusFilter) -> float:
    radius = image_filter.radius
    # GaussianBlur / BoxBlur は (横, 縦) の組でも指定できる
    return float(max(radius) if isinstance(radius, tuple | list) else radius)
