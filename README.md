# Image Editor

画像をドラッグ＆ドロップして、リサイズ・フィルター（セピア / モノトーン / ハイトーン / ポラロイド風）・トリミングを行い保存する macOS (Apple Silicon) 向けデスクトップアプリ。

Python + PyQt6 + Pillow。開発は Claude Code と GitHub Issue / PR で進める。

## クイックスタート

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m image_editor
```

## macOS アプリとして使う

`Image Editor.app` をビルドして、Finder・Launchpad・Dock から起動できます（自分の Mac で使う前提の ad-hoc 署名）。

```bash
source .venv/bin/activate
pip install -e ".[app]"
scripts/build_app.sh --install   # dist/ にビルドし、/Applications にインストール
```

- `--install` を付けなければ `dist/Image Editor.app` を作るだけ（ダブルクリックで起動できる）
- Finder で画像を右クリック →「このアプリケーションで開く」→ Image Editor、または Dock アイコンへのドロップでも開ける
- 予期しないエラーは `~/Library/Logs/ImageEditor/image_editor.log` に記録される
- コードを変更したら `scripts/build_app.sh --install` を再実行して入れ替える

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/setup.md](docs/setup.md) | 開発環境構築・GitHub リポジトリ作成・Issue 一括登録 |
| [docs/requirements.md](docs/requirements.md) | 要件定義（要件 ID 付き） |
| [docs/development-plan.md](docs/development-plan.md) | Issue の順番と Claude Code への指示方法 |
| [CLAUDE.md](CLAUDE.md) | Claude Code 向けのルール（自動で読み込まれる） |

## Claude Code での進め方

```bash
claude          # リポジトリ直下で起動
> /issue 1      # Issue #1 を実装して PR 作成まで
```

PR をレビュー・マージしたら次の Issue へ。
