# CLAUDE.md

このファイルは Claude Code がこのリポジトリで作業するときの前提・ルールです。
仕様の詳細は `docs/requirements.md`、作業の順番は `docs/development-plan.md` を参照すること。

## プロジェクト概要

画像をドラッグ＆ドロップし、リサイズ・フィルター・トリミングを適用して保存する macOS (Apple Silicon) 向けデスクトップアプリ。

- 言語: Python 3.11+
- GUI: PyQt6
- 画像処理: Pillow（必要になった場合のみ numpy を追加してよい。OpenCV は追加しない）
- テスト: pytest / pytest-qt
- Lint/Format: ruff
- 構成管理: GitHub（Issue → ブランチ → PR）

## コマンド

```bash
source .venv/bin/activate          # 仮想環境（毎回）
pip install -e ".[dev]"            # 依存インストール
python -m image_editor             # アプリ起動
pytest                             # テスト
ruff check . && ruff format --check .   # Lint / フォーマット確認
ruff format .                      # 自動整形
```

GUI を伴うテストはヘッドレスで動かす: `QT_QPA_PLATFORM=offscreen pytest`

## ディレクトリ構成（目標）

```
src/image_editor/
  __init__.py
  __main__.py            # python -m image_editor のエントリポイント
  app.py                 # QApplication の生成と起動
  core/                  # ★ Qt に依存しない純粋な画像処理層
    io.py                # 読み込み・保存・モード変換・EXIF 回転補正
    filters.py           # フィルター（PIL.Image -> PIL.Image の純粋関数）
    transform.py         # リサイズ・トリミング
    pipeline.py          # EditSettings (dataclass) と apply_edits()
  ui/                    # PyQt6 のウィジェット
    main_window.py
    drop_area.py         # D&D + プレビュー表示
    settings_panel.py
    crop_overlay.py      # プレビュー上のドラッグ範囲選択
    qt_image.py          # PIL.Image <-> QPixmap 変換
tests/
  core/                  # core は必ずユニットテストを書く
  ui/                    # pytest-qt によるスモークテスト
```

## 設計ルール（必ず守る）

1. **core は Qt を import しない。** 画像処理はすべて `core/` の純粋関数で行い、UI からは `apply_edits(image, settings)` を呼ぶだけにする。
2. **元画像は不変。** 読み込んだ原本 (`PIL.Image`) は保持し、プレビュー・保存のたびに原本から処理し直す。フィルターの重ね掛けをしない。
3. **処理順は固定:** EXIF 回転補正 → トリミング → リサイズ → フィルター（ポラロイドの白枠はフィルターの最後に付与）。
4. **プレビューは縮小版で処理する。** 長辺 1600px 程度に縮小した画像に設定を適用して表示し、保存時のみ原寸で処理する。トリミング座標は常に**原画像の座標系**で保持し、プレビュー表示時に換算する。
5. **重い処理は UI スレッドで行わない。** 原寸処理・保存は `QThreadPool` / `QRunnable` 等で実行し、完了をシグナルで UI に返す。
6. 型ヒントを付ける。公開関数には日本語で短い docstring を書く。
7. 依存パッケージを増やすときは `pyproject.toml` に追記し、PR 説明に理由を書く。

## Git / GitHub ワークフロー

作業は GitHub Issue 単位で行う。`gh` CLI が使える前提。

1. `gh issue view <番号>` で受け入れ条件を確認する
2. `main` を最新化してブランチを切る: `git switch main && git pull && git switch -c feat/<番号>-<短い英語名>`
   - 種別: `feat/` `fix/` `refactor/` `docs/` `test/` `chore/`
3. 実装 → テスト追加 → `ruff format .` → `ruff check .` → `pytest` がすべて通ることを確認
4. コミットは Conventional Commits、本文は日本語で可:
   `feat(filters): セピアフィルターを追加 (#5)`
5. `git push -u origin HEAD` → `gh pr create --fill` し、PR 本文に `Closes #<番号>` と確認手順を書く
6. **マージはユーザーが行う。** Claude は `main` へ直接 push しない、`git push --force` しない、PR をマージしない。

## 完了の定義 (Definition of Done)

- Issue の受け入れ条件をすべて満たす
- `core/` の変更にはユニットテストがある
- `ruff check` / `ruff format --check` / `pytest` が通る（CI も緑）
- GUI 変更は PR に手動確認手順を書く（可能ならスクリーンショット）
- 仕様を変えた場合は `docs/requirements.md` も更新する

## 注意点・既知の落とし穴

- JPEG は透過を持てない。RGBA / P / LA 画像を JPEG 保存するときは白背景に合成して RGB 化する。
- GIF は初版では**先頭フレームのみ**扱う。アニメーション GIF を読み込んだ場合はステータスバーで通知する。複数ページ TIFF も先頭ページのみ。
- 16bit 画像 (`I;16`) や CMYK は読み込み時に RGB/RGBA へ変換する。
- `Image.open` は遅延読み込みなので、ファイルを閉じる前に `.load()` または `.copy()` する。
- Retina 表示ではプレビュー用 `QPixmap` に `setDevicePixelRatio` を設定してぼやけを防ぐ。
- 画素ごとの Python ループは禁止（遅い）。`Image.point` / `ImageOps` / `ImageEnhance` / `Image.merge` などを使う。
