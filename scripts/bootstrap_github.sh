#!/usr/bin/env bash
# GitHub にラベル・マイルストーン・Issue を一括作成する。
# 使い方: リポジトリ直下で ./scripts/bootstrap_github.sh （gh auth login 済みであること）
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "対象リポジトリ: $REPO"

if [ "$(gh issue list --state all --limit 1 --json number -q 'length')" != "0" ]; then
  echo "既に Issue が存在します。重複作成を避けるため中止します。" >&2
  exit 1
fi

echo "== ラベル =="
while IFS='|' read -r name color desc; do
  gh label create "$name" --color "$color" --description "$desc" --force >/dev/null
  echo "  $name"
done <<'LABELS'
type:feature|1D76DB|新機能
type:bug|D73A4A|不具合
type:perf|FBCA04|性能改善
area:core|0E8A16|画像処理コア (Qt非依存)
area:ui|5319E7|PyQt6 UI
LABELS

echo "== マイルストーン =="
for m in "M1 基盤" "M2 画像処理コア" "M3 UI" "M4 品質"; do
  gh api "repos/$REPO/milestones" -f title="$m" >/dev/null 2>&1 || true
  echo "  $m"
done

echo "== Issue =="
for f in docs/issues/*.md; do
  # front matter (--- ... ---) を解析
  title=$(awk '/^---$/{n++; next} n==1 && /^title:/{sub(/^title: */,""); print}' "$f")
  labels=$(awk '/^---$/{n++; next} n==1 && /^labels:/{sub(/^labels: */,""); print}' "$f")
  milestone=$(awk '/^---$/{n++; next} n==1 && /^milestone:/{sub(/^milestone: */,""); print}' "$f")
  body=$(awk '/^---$/{n++; next} n>=2' "$f")
  url=$(gh issue create --title "$title" --label "$labels" --milestone "$milestone" --body "$body")
  echo "  $url"
done

echo "完了。Issue 番号が docs/development-plan.md の # と一致しているか確認してください。"
