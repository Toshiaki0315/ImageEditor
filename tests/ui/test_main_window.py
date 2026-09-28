from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QSplitter

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
    assert window.statusBar().currentMessage() != ""


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
