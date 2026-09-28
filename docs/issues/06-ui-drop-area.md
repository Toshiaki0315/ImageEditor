---
title: D&D エリアとプレビュー表示
labels: type:feature,area:ui
milestone: M3 UI
---
## 作業内容
- `ui/drop_area.py`: 未読込時は点線枠と案内文、対応形式のドラッグ時にハイライト
- ドロップ・メニューの「開く…」で `core.io.load_image` を呼ぶ
- `ui/qt_image.py`: `PIL.Image` → `QPixmap` 変換（RGBA 対応、Retina の devicePixelRatio 考慮）
- プレビューは縦横比を保ってエリアに収め、ウィンドウリサイズに追従
- 複数ファイル・アニメーション GIF・読み込みエラーはステータスバー／ダイアログで通知

## 受け入れ条件
- [ ] 5 形式をドロップしてプレビューされる（手動確認手順を PR に記載）
- [ ] 非対応ファイルでアプリが落ちない
- [ ] pytest-qt で「画像セット → pixmap が表示される」テスト

## 参照
FR-UI-01〜05, FR-IO-10
