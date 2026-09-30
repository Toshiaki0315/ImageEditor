import pytest
from PyQt6.QtCore import QSettings

from image_editor.app import ImageEditorApplication
from image_editor.ui import main_window


@pytest.fixture(scope="session")
def qapp_cls():
    """テストでもアプリ本体と同じ QApplication のサブクラスを使う。"""
    return ImageEditorApplication


@pytest.fixture(autouse=True)
def preferences(tmp_path, monkeypatch):
    """テストごとに空の環境設定を使う（実際の ~/Library/Preferences を書き換えない）。"""
    store = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_window, "default_preferences", lambda: store)
    return store
