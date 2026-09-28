"""QApplication の生成と起動。

Issue #1 でメインウィンドウを ui/main_window.py に切り出して差し替える。
"""

import sys

from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow


def create_window() -> QMainWindow:
    """仮のメインウィンドウを生成する。"""
    window = QMainWindow()
    window.setWindowTitle("Image Editor")
    window.resize(1200, 800)
    window.setCentralWidget(QLabel("ここに画像をドロップしてください"))
    return window


def main() -> int:
    """アプリを起動し、終了コードを返す。"""
    app = QApplication(sys.argv)
    window = create_window()
    window.show()
    return app.exec()
