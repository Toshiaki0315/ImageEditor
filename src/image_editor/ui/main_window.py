"""メインウィンドウ。"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QFrame, QLabel, QMainWindow, QSplitter, QVBoxLayout, QWidget

WINDOW_TITLE = "Image Editor"
INITIAL_SIZE = (1200, 800)
MINIMUM_SIZE = (900, 600)
SETTINGS_PANEL_WIDTH = 320


class MainWindow(QMainWindow):
    """左に D&D エリア、右に設定パネル、下にステータスバーを持つメインウィンドウ。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*INITIAL_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        # D&D エリア・設定パネルは後続 Issue で差し替えるプレースホルダ
        self.drop_area = self._create_placeholder("ここに画像をドロップしてください")
        self.drop_area.setObjectName("dropAreaPlaceholder")
        self.settings_panel = self._create_placeholder("設定パネル")
        self.settings_panel.setObjectName("settingsPanelPlaceholder")
        self.settings_panel.setMinimumWidth(SETTINGS_PANEL_WIDTH)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.drop_area)
        splitter.addWidget(self.settings_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([INITIAL_SIZE[0] - SETTINGS_PANEL_WIDTH, SETTINGS_PANEL_WIDTH])
        self.setCentralWidget(splitter)

        self._create_menus()
        self.statusBar().showMessage("画像が読み込まれていません")

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")

        self.open_action = QAction("開く…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        # 読み込み処理は後続 Issue で接続する
        file_menu.addAction(self.open_action)

        file_menu.addSeparator()

        self.quit_action = QAction("終了", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.quit_action.triggered.connect(self.close)
        file_menu.addAction(self.quit_action)

    @staticmethod
    def _create_placeholder(text: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return frame
