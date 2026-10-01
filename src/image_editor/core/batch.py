"""複数の画像に同じ加工をまとめて適用して保存する（一括処理）。"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from image_editor.core.io import (
    SaveOptions,
    edited_names,
    is_same_file,
    is_supported,
    load_image,
    path_key,
    save_edited,
    save_suffix,
)
from image_editor.core.pipeline import EditSettings, apply_edits, effective_crop
from image_editor.core.presets import Preset, apply_preset
from image_editor.core.transform import MAX_SIZE, MIN_SIZE


@dataclass(frozen=True)
class BatchOptions:
    """一括処理の設定。

    look の加工（テイスト・色の調整・フレーム・形・角丸）を各画像にかける。トリミング範囲と
    回転・反転は画像ごとに違うのでかけない（フレーム・円のときは各画像の中央をその比で
    切り抜く）。long_side を指定すると、写真の長辺をその px にリサイズする（フレームは
    その外側に付く）。
    """

    look: Preset
    long_side: int | None = None
    save: SaveOptions = field(default_factory=SaveOptions)


@dataclass(frozen=True)
class BatchResult:
    """1 枚分の結果。成功なら output、失敗なら error を持つ。"""

    source: Path
    output: Path | None = None
    error: str | None = None


def batch_settings(options: BatchOptions, image_size: tuple[int, int]) -> EditSettings:
    """image_size の画像にかける設定を返す（加工と、長辺の指定からリサイズ）。"""
    settings = apply_preset(EditSettings(), options.look)
    if options.long_side is None:
        return settings
    if not MIN_SIZE <= options.long_side <= MAX_SIZE:
        raise ValueError(f"長辺は {MIN_SIZE}〜{MAX_SIZE} で指定してください: {options.long_side}")
    # フレーム・円の比に合わせて切り抜いた後の写真の向きで、長辺を決める
    rect = effective_crop(image_size, None, settings.frame, settings.shape)
    width, height = (rect.width, rect.height) if rect else image_size
    if width >= height:
        return replace(settings, width=options.long_side)
    return replace(settings, height=options.long_side)


def output_path(source: Path, out_dir: Path) -> Path:
    """保存先のパスを返す。out_dir に元と同じ名前・拡張子で保存する。

    元の形式が保存できない（HEIC など）なら拡張子は .jpg にする。同じ名前のファイルが
    すでにある、または元のファイルそのものになる場合は `<名前>_edited`、`_edited_2` … と、
    既存のファイルと重ならない名前にする。
    """
    same_name = out_dir / f"{source.stem}{save_suffix(source)}"
    candidates = itertools.chain([same_name], edited_names(source, out_dir))
    return next(c for c in candidates if not c.exists() and not is_same_file(c, source))


def process_image(source: Path, out_dir: Path, options: BatchOptions) -> Path:
    """1 枚を読み込み、加工して out_dir に保存し、保存先を返す（元の画像は変えない）。"""
    loaded = load_image(source)
    edited = apply_edits(loaded.image, batch_settings(options, loaded.image.size))
    path = output_path(source, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_edited(edited, path, options.save, loaded.exif)
    return path


def run_batch(
    sources: Iterable[Path],
    out_dir: Path,
    options: BatchOptions,
    progress: Callable[[int, Path], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[BatchResult]:
    """画像を順に処理して結果の一覧を返す。

    1 枚ごとに、処理する前に cancelled() を確かめ、True なら残りを処理せずに終える。
    progress(処理済みの枚数, 次の画像) で進み具合を知らせる。読み込めない・保存できない
    画像は結果に error を入れて次に進む。
    """
    results: list[BatchResult] = []
    for index, source in enumerate(sources):
        if cancelled is not None and cancelled():
            break
        if progress is not None:
            progress(index, source)
        try:
            results.append(BatchResult(source, output=process_image(source, out_dir, options)))
        except Exception as e:  # 1 枚の失敗で全体を止めない
            results.append(BatchResult(source, error=f"{type(e).__name__}: {e}"))
    return results


def collect_images(paths: Iterable[Path]) -> list[Path]:
    """ファイルとフォルダの一覧から、対応形式の画像を重複なく集める。

    フォルダは直下の画像だけ（サブフォルダは見ない）を名前順に加える。隠しファイルは除く。
    """
    images: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = path_key(path)
        if key not in seen:
            seen.add(key)
            images.append(path)

    for path in paths:
        if path.is_dir():
            for child in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
                if child.is_file() and is_supported(child) and not child.name.startswith("."):
                    add(child)
        elif path.is_file() and is_supported(path):
            add(path)
    return images
