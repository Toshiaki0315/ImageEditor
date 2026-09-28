import pytest

from image_editor.app import ImageEditorApplication


@pytest.fixture(scope="session")
def qapp_cls():
    """テストでもアプリ本体と同じ QApplication のサブクラスを使う。"""
    return ImageEditorApplication
