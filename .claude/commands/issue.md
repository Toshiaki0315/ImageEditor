---
description: GitHub Issue を 1 件実装して PR を作成する
argument-hint: <issue番号>
---
GitHub Issue #$ARGUMENTS を実装してください。手順は CLAUDE.md の「Git / GitHub ワークフロー」に従います。

1. `gh issue view $ARGUMENTS` で目的・作業内容・受け入れ条件を確認する。依存 Issue が未完了なら、作業を始めずに報告して止まる。
2. 関連する `docs/requirements.md` の要件 ID を読む。仕様が曖昧な点があれば、推測で進めずに質問する。
3. `git switch main && git pull` の後、`feat/$ARGUMENTS-<短い英語名>` ブランチを作る（種別は内容に合わせる）。
4. 実装とテストを書く。`core/` は Qt を import しないこと。
5. `ruff format .` → `ruff check .` → `QT_QPA_PLATFORM=offscreen pytest` がすべて通るまで直す。
6. Conventional Commits でコミットし、`git push -u origin HEAD`。
7. `gh pr create` で PR を作る。本文は `.github/pull_request_template.md` の形式で、`Closes #$ARGUMENTS`、変更内容、手動確認手順を書く。
8. 受け入れ条件ごとに満たしたかを一覧で報告して終了する。**PR はマージしない。**
