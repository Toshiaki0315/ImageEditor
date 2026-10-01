import sys
from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtWidgets import QMessageBox

from image_editor.app import (
    ImageEditorApplication,
    files_from_argv,
    install_excepthook,
)
from image_editor.ui.main_window import MainWindow


@pytest.fixture
def app(qapp):
    """ファイルを開く要求の処理先をテストごとに初期化する。"""
    assert isinstance(qapp, ImageEditorApplication)
    qapp._file_open_handler = None
    qapp._pending_files = []
    yield qapp
    qapp._file_open_handler = None
    qapp._pending_files = []


# --- コマンドライン引数 -------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["ImageEditor"], []),
        (["ImageEditor", "a.png"], [Path("a.png")]),
        (["ImageEditor", "-psn_0_12345", "a.png", "b.jpg"], [Path("a.png"), Path("b.jpg")]),
        (["ImageEditor", "--smoke-test"], []),
    ],
)
def test_files_from_argv(argv, expected):
    assert files_from_argv(argv) == expected


# --- Finder / Dock からのファイルを開く要求 ----------------------------------------


def test_request_before_handler_is_kept(app):
    received = []
    app.request_open(Path("/tmp/early.png"))

    app.set_file_open_handler(received.append)

    assert received == [Path("/tmp/early.png")]


def test_request_after_handler_is_forwarded(app):
    received = []
    app.set_file_open_handler(received.append)

    app.request_open(Path("/tmp/a.png"))
    app.request_open(Path("/tmp/b.png"))

    assert received == [Path("/tmp/a.png"), Path("/tmp/b.png")]


def test_request_opens_image_in_window(app, qtbot, tmp_path):
    path = tmp_path / "from_finder.png"
    Image.new("RGB", (30, 20)).save(path)
    window = MainWindow()
    qtbot.addWidget(window)

    app.set_file_open_handler(window.load_file)
    app.request_open(path)

    assert window.loaded is not None and window.loaded.path == path


# --- 未処理例外 ---------------------------------------------------------------


def test_excepthook_logs_and_shows_dialog(qapp, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # テスト後に元へ戻す
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: shown.append(a[2]))
    log_file = tmp_path / "logs" / "app.log"
    install_excepthook(log_file)

    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    assert "ValueError: boom" in log_file.read_text()
    assert len(shown) == 1 and "boom" in shown[0]


def test_can_load(tmp_path):
    from PIL import Image

    from image_editor.app import can_load

    good = tmp_path / "a.heic"
    Image.new("RGB", (8, 8)).save(good, format="HEIF")
    broken = tmp_path / "broken.heic"
    broken.write_bytes(b"not a heic")

    assert can_load(good)
    assert not can_load(broken)
    assert not can_load(tmp_path / "missing.png")
