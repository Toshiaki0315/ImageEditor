import pytest
from PIL import Image
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QSplitter

from image_editor.app import create_window
from image_editor.ui.main_window import MainWindow


def test_window_opens(qtbot):
    window = create_window()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert isinstance(window, MainWindow)
    assert window.isVisible()
    assert window.windowTitle() == "Image Editor"


def test_window_size(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert (window.width(), window.height()) == (1200, 800)
    assert (window.minimumWidth(), window.minimumHeight()) == (900, 600)


def test_layout_has_placeholders_and_status_bar(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    splitter = window.centralWidget()
    assert isinstance(splitter, QSplitter)
    assert splitter.widget(0) is window.drop_area
    assert splitter.widget(1) is window.settings_panel
    assert window.status_label.text() == "画像が読み込まれていません"


def test_file_menu_actions(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    menus = [a.menu() for a in window.menuBar().actions() if a.menu()]
    assert [m.title() for m in menus] == ["ファイル"]
    texts = [a.text() for a in menus[0].actions() if not a.isSeparator()]
    assert texts == ["開く…", "終了"]
    assert window.open_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Open)
    assert window.quit_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Quit)


def test_quit_action_closes_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    window.quit_action.trigger()

    assert not window.isVisible()


# --- 画像の読み込み -----------------------------------------------------------


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@pytest.fixture
def warnings(monkeypatch):
    """QMessageBox.warning を差し替え、表示された内容を記録する。"""
    shown: list[tuple[str, str]] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        shown.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    return shown


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".gif", ".tif", ".bmp"])
def test_load_file_shows_preview(window, tmp_path, warnings, suffix):
    path = tmp_path / f"photo{suffix}"
    Image.new("RGB", (300, 200), (255, 0, 0)).save(path)

    assert window.load_file(path)

    assert window.loaded is not None
    assert window.loaded.path == path
    assert window.drop_area.has_image()
    assert window.drop_area.display_pixmap() is not None
    assert window.status_label.text() == f"photo{suffix} — 300×200 px"
    assert warnings == []


def test_load_corrupt_file_shows_dialog(window, tmp_path, warnings):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")

    assert not window.load_file(path)

    assert len(warnings) == 1
    assert "broken.png" in warnings[0][1]
    assert window.loaded is None
    assert not window.drop_area.has_image()
    assert window.isVisible()


def test_failed_load_keeps_previous_image(window, tmp_path, warnings):
    good = tmp_path / "good.png"
    Image.new("RGB", (10, 10)).save(good)
    window.load_file(good)

    window.load_file(tmp_path / "missing.png")

    assert len(warnings) == 1
    assert window.loaded is not None and window.loaded.path == good
    assert window.status_label.text().startswith("good.png")


def test_unexpected_error_does_not_crash(window, tmp_path, warnings, monkeypatch):
    def boom(path):
        raise MemoryError("too big")

    monkeypatch.setattr("image_editor.ui.main_window.load_image", boom)

    assert not window.load_file(tmp_path / "a.png")
    assert len(warnings) == 1


def test_animated_gif_is_notified(window, tmp_path, warnings):
    path = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (8, 8), c) for c in [(255, 0, 0), (0, 255, 0)]]
    frames[0].save(path, save_all=True, append_images=frames[1:])

    window.load_file(path)

    assert "先頭フレームのみ" in window.status_label.text()


def test_drop_multiple_files_loads_first(window, tmp_path, warnings):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGB", (10, 10)).save(first)
    Image.new("RGB", (20, 20)).save(second)

    window.drop_area.files_dropped.emit([first, second])

    assert window.loaded is not None and window.loaded.path == first
    assert "2 件中、先頭の 1 枚のみ" in window.status_label.text()


def test_open_action_loads_selected_file(window, tmp_path, warnings, monkeypatch):
    path = tmp_path / "opened.jpg"
    Image.new("RGB", (40, 30)).save(path)
    calls = []

    def fake_dialog(parent, caption, directory, file_filter):
        calls.append(file_filter)
        return str(path), file_filter

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_dialog)

    window.open_action.trigger()

    assert window.loaded is not None and window.loaded.path == path
    assert "*.png" in calls[0] and "*.tiff" in calls[0]


def test_open_action_cancel_does_nothing(window, warnings, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))

    window.open_action.trigger()

    assert window.loaded is None
    assert warnings == []
