---
title: アプリ雛形とメインウィンドウ
labels: type:feature,area:ui
milestone: M1 基盤
---
## 目的
`python -m image_editor` で空のメインウィンドウが起動する状態を作る。

## 作業内容
- `src/image_editor/app.py` の雛形を拡張（QApplication 生成・起動）
- `ui/main_window.py`: 左に D&D エリア用のプレースホルダ、右に設定パネル用のプレースホルダ、下にステータスバー
- ウィンドウタイトル「Image Editor」、初期サイズ 1200×800、最小 900×600
- `core/` `ui/` のパッケージ（空の `__init__.py`）を作成
- メニュー「ファイル」に「開く…(⌘O)」「終了(⌘Q)」を配置（開くは未実装でよい）

## 受け入れ条件
- [ ] `python -m image_editor` でウィンドウが表示される
- [ ] pytest-qt でメインウィンドウを生成・表示するテストがある
- [ ] CI が緑

## 参照
docs/requirements.md §4
