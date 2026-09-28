# Image Editor

画像をドラッグ＆ドロップして、リサイズ・フィルター（セピア / モノトーン / ハイトーン / ポラロイド風）・トリミングを行い保存する macOS (Apple Silicon) 向けデスクトップアプリ。

Python + PyQt6 + Pillow。開発は Claude Code と GitHub Issue / PR で進める。

## クイックスタート

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m image_editor
```

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
