---
title: フィルター (core/filters)
labels: type:feature,area:core
milestone: M2 画像処理コア
---
## 作業内容
- `FilterType` Enum: NONE / SEPIA / MONOTONE / HIGH_TONE / POLAROID（表示名の日本語ラベルも持つ）
- `apply_filter(image, filter_type) -> Image`
- 各フィルターは requirements.md §5.4 の仕様に従う。係数はモジュール先頭の定数にする
- アルファチャンネルは分離して RGB にのみ適用し、最後に戻す（ポラロイドの白枠部分は不透明）
- 画素ごとの Python ループは使わない

## 受け入れ条件
- [ ] 各フィルターについて、出力モード・サイズ・代表画素の色の傾向をテスト
  - セピア: R ≥ G ≥ B
  - モノトーン: R == G == B
  - ポラロイド: 出力サイズが仕様どおり大きくなり、下余白 > 横余白
- [ ] RGBA 入力でアルファが保持されるテスト
- [ ] 入力画像オブジェクトが変更されない（非破壊）テスト

## 参照
FR-FLT-01〜05, FR-PRC-03
