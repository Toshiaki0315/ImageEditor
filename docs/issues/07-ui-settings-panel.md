---
title: 設定パネルと保存・リセット
labels: type:feature,area:ui
milestone: M3 UI
---
## 作業内容
- `ui/settings_panel.py`: サイズ変更（幅・高さ QSpinBox、縦横比保持チェック）、加工プルダウン、トリミング数値欄と「範囲をクリア」、各ボタン
- パネルは `EditSettings` を組み立ててシグナル `settings_changed(EditSettings)` を発行する
- 縦横比保持 ON 時の幅⇔高さ連動（無限ループしないよう signal をブロック）
- プレビュー更新 (⌘R)、保存 (⌘S、デフォルト名 `<元名>_edited.<拡張子>`)、リセット（未保存確認あり）
- ステータスバーにファイル名・原寸・出力予定サイズを表示

## 受け入れ条件
- [ ] 各フィルターを選んでプレビュー更新すると見た目が変わる
- [ ] 保存したファイルを再度開くと指定サイズ・フィルターが反映されている
- [ ] pytest-qt で縦横比連動と `EditSettings` の生成をテスト

## 参照
FR-UI-10〜42
