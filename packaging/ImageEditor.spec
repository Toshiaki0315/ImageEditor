# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller の設定: `Image Editor.app` をビルドする。

scripts/build_app.sh から実行する（アイコンの生成・署名の確認も行う）。
"""

import re
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH は PyInstaller が定義する
SRC = ROOT / "src"
ICON = ROOT / "build" / "icon" / "ImageEditor.icns"

APP_NAME = "Image Editor"
BUNDLE_ID = "io.github.toshiaki0315.imageeditor"
VERSION = re.search(
    r'__version__ = "([^"]+)"', (SRC / "image_editor" / "__init__.py").read_text()
).group(1)

# 対応 5 形式 (FR-IO-01〜05) の UTI。Finder の「このアプリケーションで開く」と Dock へのドロップ用
DOCUMENT_TYPES = [
    {
        "CFBundleTypeName": "Image",
        "CFBundleTypeRole": "Editor",
        "LSHandlerRank": "Alternate",
        "LSItemContentTypes": [
            "public.png",
            "public.jpeg",
            "com.compuserve.gif",
            "public.tiff",
            "com.microsoft.bmp",
        ],
    }
]

a = Analysis(
    [str(SRC / "image_editor" / "__main__.py")],
    pathex=[str(SRC)],
    excludes=["tkinter", "pytest", "pytestqt"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ImageEditor",
    console=False,
    # Finder からのファイルは Qt が QFileOpenEvent として受け取るので、argv への変換はしない
    argv_emulation=False,
    codesign_identity=None,  # ad-hoc 署名
)
coll = COLLECT(exe, a.binaries, a.datas, name="ImageEditor")
app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ICON) if ICON.exists() else None,
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleDocumentTypes": DOCUMENT_TYPES,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # ダークモード対応
    },
)
