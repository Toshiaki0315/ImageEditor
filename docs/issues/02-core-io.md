---
title: 画像の読み込み・保存 (core/io)
labels: type:feature,area:core
milestone: M2 画像処理コア
---
## 目的
対応 5 形式の読み込み・保存を Qt 非依存の関数として実装する。

## 作業内容
- `load_image(path) -> LoadedImage`（`image: PIL.Image`, `format`, `is_animated`, `path` を持つ dataclass）
  - EXIF Orientation を補正（`ImageOps.exif_transpose`）
  - CMYK / I;16 / P / LA などを RGB または RGBA に正規化
  - GIF・TIFF は先頭フレームのみ。アニメーションなら `is_animated=True`
  - `.load()` してからファイルを閉じる
- `save_image(image, path, quality=90)`
  - 拡張子から形式を判定（大文字小文字無視）
  - JPEG / BMP で透過がある場合は白背景に合成して RGB 化
- `SUPPORTED_EXTENSIONS` 定数と `is_supported(path)`
- 非対応・破損ファイルは独自例外 `UnsupportedImageError` を送出

## 受け入れ条件
- [ ] 5 形式それぞれの読み込み・保存の往復テスト（テスト画像は tmp_path に Pillow で生成）
- [ ] RGBA → JPEG 保存で例外にならず白背景になるテスト
- [ ] EXIF Orientation=6 の画像が回転補正されるテスト
- [ ] 破損ファイルで `UnsupportedImageError` になるテスト
- [ ] `core/io.py` が PyQt6 を import していない

## 参照
FR-IO-01〜10
