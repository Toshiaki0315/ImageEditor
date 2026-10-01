"""簡易ベンチマーク: 12MP 画像で読み込み・プレビュー・原寸処理・保存の時間を計測する。

使い方:
    python scripts/bench.py                 # 4000x3000 の JPEG を生成して計測
    python scripts/bench.py --image 写真.jpg  # 手元の画像で計測
    python scripts/bench.py --repeat 5      # 各処理を 5 回計測して最小値を出す
"""

from __future__ import annotations

import argparse
import platform
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from PIL import Image
from PyQt6.QtCore import QSize, Qt

from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType
from image_editor.core.io import load_image, save_image
from image_editor.core.pipeline import (
    EditSettings,
    apply_edits,
    make_preview,
    render_preview_with_histogram,
)
from image_editor.core.shapes import ShapeType
from image_editor.core.text import TextSettings
from image_editor.core.transform import CropRect
from image_editor.ui.qt_image import pil_to_qimage

T = TypeVar("T")

# プレビュー表示エリアのおおよその大きさ（1200x800 のウィンドウ、Retina 2x）
DISPLAY_SIZE = QSize(850 * 2, 740 * 2)
# NFR-01 / NFR-02 の目標値（秒）
TARGET_LOAD_TO_PREVIEW = 1.0
TARGET_PREVIEW_UPDATE = 0.2

# 効果をほぼすべてかけた重い設定（プレビュー更新がいちばん遅くなる組み合わせ）
HEAVY_SETTINGS = EditSettings(
    exposure=0.5,
    brightness=10,
    contrast=20,
    temperature=5000,
    saturation=20,
    sharpen=50,
    blur=10,
    denoise=50,
    filter=FilterType.HDR,
    vignette=50,
    aging=30,
    frame=FrameType.POLAROID,
    shape=ShapeType.ROUNDED,
    corner_radius=20,
    text=TextSettings(text="© 2026"),
)


def measure(func: Callable[[], T], repeat: int) -> tuple[float, T]:
    """func を repeat 回実行し、最小の所要時間（秒）と最後の戻り値を返す。"""
    times = []
    result: T
    for _ in range(repeat):
        start = time.perf_counter()
        result = func()
        times.append(time.perf_counter() - start)
    return min(times), result


def make_sample_jpeg(path: Path, size: tuple[int, int]) -> None:
    """ノイズとグラデーションを重ねた（圧縮しにくい）JPEG を作る。"""
    width, height = size
    gradient = Image.linear_gradient("L").resize(size)
    noise = Image.effect_noise(size, 40)
    channels = [
        Image.blend(gradient, noise, 0.5),
        Image.blend(gradient.rotate(90).resize(size), noise, 0.3),
        noise,
    ]
    Image.merge("RGB", channels).save(path, quality=90)
    print(f"サンプル画像を生成: {path.name} ({width}×{height})")


def main() -> None:
    """ベンチマークを実行して結果を表示する。"""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", type=Path, help="計測に使う画像（省略時は生成）")
    parser.add_argument("--repeat", type=int, default=3, help="各処理の計測回数（最小値を採用）")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        path = args.image
        if path is None:
            path = tmp_dir / "sample_12mp.jpg"
            make_sample_jpeg(path, (4000, 3000))

        env = f"{platform.platform()} / {platform.machine()} / Python {platform.python_version()}"
        print(f"環境: {env}")
        print(f"計測回数: {args.repeat}（最小値）\n")
        rows: list[tuple[str, float]] = []

        # --- 読み込み → プレビュー表示 (NFR-01) ---
        t_load, loaded = measure(lambda: load_image(path), args.repeat)
        original = loaded.image
        t_shrink, (preview, factor) = measure(lambda: make_preview(original), args.repeat)

        def to_display() -> object:
            qimage = pil_to_qimage(preview)
            return qimage.scaled(
                DISPLAY_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        t_display, _ = measure(to_display, args.repeat)
        rows += [
            (f"読み込み ({original.width}×{original.height})", t_load),
            (f"縮小版の作成 (→ {preview.width}×{preview.height})", t_shrink),
            ("Qt 画像への変換と表示用縮小", t_display),
        ]
        load_to_preview = t_load + t_shrink + t_display
        rows.append(("★ 読み込み → プレビュー表示 合計", load_to_preview))

        # --- 設定変更 → プレビュー更新 (NFR-02) ---
        print_rows("読み込み", rows)
        rows = []
        preview_times = []
        crop = (original.width // 10, original.height // 10)
        cases = [
            (
                filter_type.label,
                EditSettings(
                    crop=None
                    if filter_type is FilterType.NONE
                    else _crop_rect(crop, original.size),
                    width=original.width // 2,
                    filter=filter_type,
                ),
            )
            for filter_type in FilterType
        ]
        cases.append(("★ 重い設定（効果をほぼすべて）", HEAVY_SETTINGS))
        for label, settings in cases:
            for trimmed in (False, True):
                # アプリと同じく、プレビューとヒストグラムを描いて Qt の画像にする
                def update(s: EditSettings = settings, t: bool = trimmed) -> object:
                    image, _ = render_preview_with_histogram(preview, s, factor, trimmed=t)
                    return pil_to_qimage(image)

                elapsed, _ = measure(update, args.repeat)
                preview_times.append(elapsed)
                view = "切り抜き表示" if trimmed else "全体表示"
                rows.append((f"プレビュー更新: {label}（{view}）", elapsed))
        print_rows("プレビュー更新（縮小版）", rows)

        # --- 原寸処理と保存 (NFR-03 はワーカースレッドで実行) ---
        rows = []
        for filter_type in FilterType:
            settings = EditSettings(filter=filter_type)
            elapsed, _ = measure(lambda s=settings: apply_edits(original, s), args.repeat)
            rows.append((f"原寸処理: {filter_type.label}", elapsed))
        elapsed, _ = measure(lambda: apply_edits(original, HEAVY_SETTINGS), args.repeat)
        rows.append(("原寸処理: ★ 重い設定（効果をほぼすべて）", elapsed))
        edited = apply_edits(original, EditSettings(filter=FilterType.SEPIA))
        for suffix in (".jpg", ".png"):
            out = tmp_dir / f"out{suffix}"
            elapsed, _ = measure(lambda o=out: save_image(edited, o), args.repeat)
            rows.append((f"保存 {suffix}", elapsed))
        print_rows("原寸処理・保存（ワーカースレッドで実行）", rows)

        print("判定")
        judge("NFR-01 読み込み→プレビュー表示", load_to_preview, TARGET_LOAD_TO_PREVIEW)
        judge("NFR-02 プレビュー更新（最大）", max(preview_times), TARGET_PREVIEW_UPDATE)
        print(f"  （プレビュー更新の中央値 {statistics.median(preview_times) * 1000:.0f} ms）")


def _crop_rect(margin: tuple[int, int], size: tuple[int, int]) -> CropRect:
    """周囲に margin の余白を残すトリミング範囲を返す。"""
    return CropRect(margin[0], margin[1], size[0] - margin[0] * 2, size[1] - margin[1] * 2)


def print_rows(title: str, rows: list[tuple[str, float]]) -> None:
    """計測結果を表形式で表示する。"""
    print(f"## {title}")
    for label, seconds in rows:
        print(f"  {label:<48} {seconds * 1000:8.0f} ms")
    print()


def judge(label: str, seconds: float, target: float) -> None:
    """目標値との比較を表示する。"""
    mark = "OK" if seconds <= target else "NG"
    print(f"  [{mark}] {label}: {seconds * 1000:.0f} ms（目標 {target * 1000:.0f} ms 以内）")


if __name__ == "__main__":
    main()
