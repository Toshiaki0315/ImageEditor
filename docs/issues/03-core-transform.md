---
title: トリミング・リサイズ (core/transform)
labels: type:feature,area:core
milestone: M2 画像処理コア
---
## 作業内容
- `CropRect` dataclass (x, y, width, height)
- `clamp_crop(rect, image_size) -> CropRect | None`: 画像内に収まるよう補正。幅か高さが 0 なら None
- `crop(image, rect) -> Image`
- `fit_size(orig_size, width, height, keep_aspect) -> tuple[int, int]`: 片方だけ指定・両方指定・縦横比保持の計算（四捨五入、最小 1）
- `resize(image, size) -> Image`（LANCZOS）

## 受け入れ条件
- [ ] 画像外にはみ出す範囲・負の座標・0 サイズのテスト
- [ ] `fit_size` の境界値テスト（1px、20000px、片方 None）
- [ ] RGBA のアルファがトリミング・リサイズ後も保持されるテスト

## 参照
FR-TRM-01, FR-RSZ-01〜02, FR-UI-10〜12, FR-UI-32
