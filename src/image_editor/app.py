"""QApplication の生成と起動。"""

import sys

from PyQt6.QtWidgets import QApplication

from image_editor.ui.main_window import WINDOW_TITLE, MainWindow


def create_window() -> MainWindow:
    """メインウィンドウを生成する。"""
    return MainWindow()


def main() -> int:
    """アプリを起動し、終了コードを返す。"""
    app = QApplication(sys.argv)
    app.setApplicationName(WINDOW_TITLE)
    window = create_window()
    window.show()
    return app.exec()
