#!/usr/bin/env bash
# macOS アプリ (dist/Image Editor.app) をビルドする。
#
# 使い方:
#   scripts/build_app.sh             # ビルドして起動確認まで
#   scripts/build_app.sh --install   # さらに /Applications にインストールする
set -euo pipefail

cd "$(dirname "$0")/.."

APP="dist/Image Editor.app"
INSTALL_TO="/Applications/Image Editor.app"

if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller がありません。先に次を実行してください: pip install -e \".[app]\"" >&2
    exit 1
fi

echo "==> アイコンを生成"
python scripts/make_icon.py build/icon/ImageEditor.icns

echo "==> .app をビルド"
pyinstaller --noconfirm --clean \
    --distpath dist --workpath build/pyinstaller \
    packaging/ImageEditor.spec

echo "==> 署名（ad-hoc）を確認"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "==> 起動確認"
QT_QPA_PLATFORM=offscreen "$APP/Contents/MacOS/ImageEditor" --smoke-test

echo "==> HEIC を開けるかの確認（pillow-heif が .app に入っているか）"
SAMPLE_DIR="$(mktemp -d)"
trap 'rm -rf "$SAMPLE_DIR"' EXIT
python -c "import sys; from PIL import Image; from pillow_heif import register_heif_opener; register_heif_opener(); Image.new('RGB', (64, 48), (200, 60, 30)).save(sys.argv[1], format='HEIF')" "$SAMPLE_DIR/sample.heic"
QT_QPA_PLATFORM=offscreen "$APP/Contents/MacOS/ImageEditor" --smoke-test "$SAMPLE_DIR/sample.heic"

if [[ "${1:-}" == "--install" ]]; then
    echo "==> $INSTALL_TO にインストール"
    rm -rf "$INSTALL_TO"
    ditto "$APP" "$INSTALL_TO"
    # Launch Services に登録して「このアプリケーションで開く」に出るようにする
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$INSTALL_TO"
fi

echo "完了: $APP ($(du -sh "$APP" | cut -f1))"
