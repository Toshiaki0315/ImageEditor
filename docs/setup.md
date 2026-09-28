# 開発環境の構築（Apple Silicon Mac）

## 1. 前提ツール

```bash
# Homebrew（未インストールの場合のみ）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python・Git・GitHub CLI
brew install python@3.11 git gh
```

## 2. Claude Code

ネイティブインストーラーが推奨（自動更新される）。Node.js は不要。

```bash
curl -fsSL https://claude.ai/install.sh | bash
# 新しいターミナルを開いて確認
claude --version
```

Homebrew 派なら `brew install --cask claude-code` でも可（自動更新されないので `brew upgrade` が必要）。

初回ログインは `claude` を起動してブラウザの案内に従う（Pro / Max / Team / Enterprise / Console アカウントが必要）。

## 3. GitHub CLI の認証

```bash
gh auth login        # GitHub.com → HTTPS → ブラウザで認証
gh auth status       # 確認
```

## 4. リポジトリの作成と初回 push

このフォルダ一式を展開した場所で実行する。

```bash
cd image-editor-app

git init -b main
git add .
git commit -m "chore: 初期構成（要件定義・CLAUDE.md・CI）"

# GitHub にリポジトリを作成して push（公開するなら --public）
gh repo create image-editor-app --private --source=. --push
```

## 5. Python 仮想環境

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"

pytest               # スモークテストが 1 件通れば OK
```

## 6. ラベル・マイルストーン・Issue の一括作成

```bash
./scripts/bootstrap_github.sh
```

`docs/development-plan.md` の内容で Issue #1〜#9 が作成される（2 回実行すると重複するので注意）。

## 7. ブランチ保護（推奨）

GitHub の Settings → Branches → Add branch ruleset で `main` に以下を設定:

- Require a pull request before merging
- Require status checks to pass → `lint-and-test`
- Block force pushes

これで Claude Code が誤って `main` に直接 push しても弾かれる。
