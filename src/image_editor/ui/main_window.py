"""メインウィンドウ。"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from image_editor.core.io import (
    SUPPORTED_EXTENSIONS,
    LoadedImage,
    UnsupportedImageError,
    load_image,
)
from image_editor.ui.drop_area import DropArea

WINDOW_TITLE = "Image Editor"
INITIAL_SIZE = (1200, 800)
MINIMUM_SIZE = (900, 600)
SETTINGS_PANEL_WIDTH = 320

NO_IMAGE_MESSAGE = "画像が読み込まれていません"
FORMATS_TEXT = "PNG / JPEG / GIF / TIFF / BMP"
OPEN_DIALOG_FILTER = "画像ファイル ({})".format(
    " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
)


class MainWindow(QMainWindow):
    """左に D&D エリア、右に設定パネル、下にステータスバーを持つメインウィンドウ。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*INITIAL_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        # 読み込んだ原本。編集はここから毎回処理し直す
        self.loaded: LoadedImage | None = None

        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._on_files_dropped)
        # 設定パネルは後続 Issue で差し替えるプレースホルダ
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

        # showMessage はメニューのヒント表示で消えるため、常設のラベルを使う
        self.status_label = QLabel(NO_IMAGE_MESSAGE)
        self.statusBar().addWidget(self.status_label, 1)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")

        self.open_action = QAction("開く…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(self.open_action)

        file_menu.addSeparator()

        self.quit_action = QAction("終了", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.quit_action.triggered.connect(self.close)
        file_menu.addAction(self.quit_action)

    # --- 読み込み -------------------------------------------------------------

    def open_file_dialog(self) -> None:
        """ファイル選択ダイアログを開き、選ばれた画像を読み込む。"""
        path, _ = QFileDialog.getOpenFileName(self, "画像を開く", "", OPEN_DIALOG_FILTER)
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path, notes: list[str] | None = None) -> bool:
        """画像を読み込んでプレビューに表示する。失敗したらダイアログで通知して False を返す。

        失敗しても、それまで表示していた画像はそのまま残す。
        """
        try:
            loaded = load_image(path)
        except UnsupportedImageError as e:
            self._show_load_error(str(e))
            return False
        except Exception as e:  # 想定外の例外でもアプリを落とさない (NFR-04)
            self._show_load_error(f"画像を読み込めません: {path.name}\n({type(e).__name__}: {e})")
            return False

        self.loaded = loaded
        self.drop_area.set_image(loaded.image)

        notes = list(notes or [])
        if loaded.is_animated:
            notes.append("複数フレームの画像のため、先頭フレームのみ扱います")
        width, height = loaded.image.size
        message = f"{path.name} — {width}×{height} px"
        if notes:
            message += "（" + "／".join(notes) + "）"
        self.status_label.setText(message)
        return True

    def _on_files_dropped(self, paths: list[Path]) -> None:
        if not paths:
            return
        notes = []
        if len(paths) > 1:
            notes.append(f"{len(paths)} 件中、先頭の 1 枚のみ読み込みました")
        self.load_file(paths[0], notes)

    def _show_load_error(self, message: str) -> None:
        QMessageBox.warning(
            self,
            "画像を読み込めません",
            f"{message}\n\n対応形式: {FORMATS_TEXT}",
        )

    @staticmethod
    def _create_placeholder(text: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return frame
