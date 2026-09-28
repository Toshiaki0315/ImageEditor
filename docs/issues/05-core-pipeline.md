---
title: 編集パイプライン (core/pipeline)
labels: type:feature,area:core
milestone: M2 画像処理コア
---
## 作業内容
- `EditSettings` dataclass（frozen）: `crop: CropRect | None`, `width: int | None`, `height: int | None`, `keep_aspect: bool`, `filter: FilterType`
- `apply_edits(original, settings) -> Image`: トリミング → リサイズ → フィルター の順で適用
- `output_size(original_size, settings) -> tuple[int, int]`: 実際に処理せず最終出力サイズを計算（ステータスバー表示用。ポラロイドの枠を含む）
- `scale_settings(settings, factor) -> EditSettings`: 縮小プレビュー用に座標・サイズを換算

## 受け入れ条件
- [ ] 処理順序が仕様どおりであることのテスト
- [ ] `output_size` と `apply_edits(...).size` が全フィルターで一致するテスト
- [ ] 原画像が変更されないテスト

## 参照
docs/requirements.md §5.1, FR-PRC-01〜02
