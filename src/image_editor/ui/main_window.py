"""メインウィンドウ。"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QWidget,
)

from image_editor.core.io import (
    SUPPORTED_EXTENSIONS,
    LoadedImage,
    UnsupportedImageError,
    is_supported,
    load_image,
    save_image,
)
from image_editor.core.pipeline import EditSettings, apply_edits, output_size
from image_editor.ui.drop_area import DropArea
from image_editor.ui.settings_panel import SettingsPanel

WINDOW_TITLE = "Image Editor"
INITIAL_SIZE = (1200, 800)
MINIMUM_SIZE = (900, 600)
SETTINGS_PANEL_WIDTH = 320

NO_IMAGE_MESSAGE = "画像が読み込まれていません"
FORMATS_TEXT = "PNG / JPEG / GIF / TIFF / BMP"
OPEN_DIALOG_FILTER = "画像ファイル ({})".format(
    " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
)
# 保存ダイアログの形式ごとのフィルター（読み込み時の形式名 -> フィルター文字列）
SAVE_DIALOG_FILTERS: dict[str, str] = {
    "PNG": "PNG (*.png)",
    "JPEG": "JPEG (*.jpg *.jpeg)",
    "GIF": "GIF (*.gif)",
    "TIFF": "TIFF (*.tif *.tiff)",
    "BMP": "BMP (*.bmp)",
}
DISCARD_QUESTION = "保存していない変更があります。破棄してよろしいですか？"


def default_save_path(path: Path) -> Path:
    """保存ダイアログの初期パス `<元の名前>_edited.<元の拡張子>` を返す。"""
    return path.with_name(f"{path.stem}_edited{path.suffix}")


class MainWindow(QMainWindow):
    """左に D&D エリア、右に設定パネル、下にステータスバーを持つメインウィンドウ。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*INITIAL_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        # 読み込んだ原本。プレビュー・保存のたびにここから処理し直す
        self.loaded: LoadedImage | None = None
        # 最後に保存したときの設定（未保存の変更の判定に使う）
        self._saved_settings: EditSettings | None = None
        self._load_notes: list[str] = []

        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._on_files_dropped)
        self.settings_panel = SettingsPanel()
        self.settings_panel.setMinimumWidth(SETTINGS_PANEL_WIDTH)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.crop_mode_toggled.connect(self._set_crop_mode)
        self.drop_area.crop_overlay.crop_changed.connect(self.settings_panel.set_crop)
        self.settings_panel.preview_requested.connect(self.update_preview)
        self.settings_panel.save_requested.connect(self.save_file_dialog)
        self.settings_panel.reset_requested.connect(self.reset)

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
        self._update_actions()

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")

        self.open_action = QAction("開く…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(self.open_action)

        self.save_action = QAction("保存…", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_file_dialog)
        file_menu.addAction(self.save_action)

        file_menu.addSeparator()

        self.quit_action = QAction("終了", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.quit_action.triggered.connect(self.close)
        file_menu.addAction(self.quit_action)

        view_menu = self.menuBar().addMenu("表示")
        self.preview_action = QAction("プレビュー更新", self)
        self.preview_action.setShortcut(QKeySequence("Ctrl+R"))  # macOS では ⌘R
        self.preview_action.triggered.connect(self.update_preview)
        view_menu.addAction(self.preview_action)

    # --- 読み込み -------------------------------------------------------------

    def open_file_dialog(self) -> None:
        """ファイル選択ダイアログを開き、選ばれた画像を読み込む。"""
        path, _ = QFileDialog.getOpenFileName(self, "画像を開く", "", OPEN_DIALOG_FILTER)
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path, notes: list[str] | None = None) -> bool:
        """画像を読み込んでプレビューに表示する。失敗したらダイアログで通知して False を返す。

        未保存の変更があれば確認し、キャンセルされたら読み込まない。
        失敗しても、それまで表示していた画像と設定はそのまま残す。
        """
        if not self._confirm_discard():
            return False
        try:
            loaded = load_image(path)
        except UnsupportedImageError as e:
            self._show_error("画像を読み込めません", str(e), with_formats=True)
            return False
        except Exception as e:  # 想定外の例外でもアプリを落とさない (NFR-04)
            self._show_error(
                "画像を読み込めません",
                f"画像を読み込めません: {path.name}\n({type(e).__name__}: {e})",
                with_formats=True,
            )
            return False

        self.loaded = loaded
        self._saved_settings = None
        self._load_notes = list(notes or [])
        if loaded.is_animated:
            self._load_notes.append("複数フレームの画像のため、先頭フレームのみ扱います")
        self.drop_area.crop_overlay.set_active(False)
        self.drop_area.crop_overlay.set_image_size(loaded.image.size)
        self.settings_panel.set_image_size(loaded.image.size)
        self.drop_area.set_image(loaded.image)
        self._update_status()
        self._update_actions()
        return True

    def _on_files_dropped(self, paths: list[Path]) -> None:
        if not paths:
            return
        notes = []
        if len(paths) > 1:
            notes.append(f"{len(paths)} 件中、先頭の 1 枚のみ読み込みました")
        self.load_file(paths[0], notes)

    # --- プレビュー・保存・リセット -----------------------------------------

    def update_preview(self) -> None:
        """現在の設定を原本に適用してプレビューに表示する。

        範囲指定中なら、範囲指定を終えて編集結果の表示に切り替える。
        """
        if self.loaded is None:
            return
        if self.settings_panel.is_crop_mode():
            # OFF にすると _set_crop_mode(False) からこのメソッドが再び呼ばれる
            self.settings_panel.set_crop_mode(False)
            return
        try:
            edited = apply_edits(self.loaded.image, self.settings_panel.settings())
        except Exception as e:  # NFR-04
            self._show_error("プレビューを更新できません", f"{type(e).__name__}: {e}")
            return
        self.drop_area.set_image(edited)

    def save_file_dialog(self) -> None:
        """保存ダイアログを開き、原寸で処理して書き出す。"""
        if self.loaded is None:
            return
        selected_filter = SAVE_DIALOG_FILTERS.get(self.loaded.format, "")
        path_text, chosen_filter = QFileDialog.getSaveFileName(
            self,
            "保存",
            str(default_save_path(self.loaded.path)),
            ";;".join(SAVE_DIALOG_FILTERS.values()),
            selected_filter,
        )
        if not path_text:
            return
        path = Path(path_text)
        if not path.suffix:
            path = path.with_suffix(_first_extension(chosen_filter or selected_filter))
        if not is_supported(path):
            self._show_error(
                "保存できません",
                f"対応していない拡張子です: {path.suffix}",
                with_formats=True,
            )
            return
        self.save_to(path)

    def save_to(self, path: Path) -> bool:
        """現在の設定を原寸で適用して保存する。処理中はボタンを無効化する。"""
        if self.loaded is None:
            return False
        settings = self.settings_panel.settings()
        self.settings_panel.set_busy(True)
        self._update_actions(busy=True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            save_image(apply_edits(self.loaded.image, settings), path)
        except Exception as e:  # NFR-04
            self._show_error("保存できません", f"{path.name}\n({type(e).__name__}: {e})")
            return False
        finally:
            QApplication.restoreOverrideCursor()
            self.settings_panel.set_busy(False)
            self._update_actions()
        self._saved_settings = settings
        self._update_status(f"保存しました: {path.name}")
        return True

    def reset(self) -> None:
        """画像と設定を未読込の状態に戻す。未保存の変更があれば確認する。"""
        if not self._confirm_discard():
            return
        self.loaded = None
        self._saved_settings = None
        self._load_notes = []
        self.drop_area.crop_overlay.set_active(False)
        self.drop_area.crop_overlay.set_image_size(None)
        self.drop_area.set_image(None)
        self.settings_panel.set_image_size(None)
        self._update_status()
        self._update_actions()

    def has_unsaved_changes(self) -> bool:
        """初期状態から設定を変えていて、その設定でまだ保存していなければ True。"""
        if self.loaded is None:
            return False
        settings = self.settings_panel.settings()
        return settings != EditSettings() and settings != self._saved_settings

    # --- 内部 -----------------------------------------------------------------

    def _on_settings_changed(self, settings: EditSettings) -> None:
        overlay = self.drop_area.crop_overlay
        # ドラッグ中の変更はオーバーレイ自身が発生源なので書き戻さない
        if not overlay.is_dragging():
            overlay.set_crop(settings.crop)
        self._update_status()

    def _set_crop_mode(self, enabled: bool) -> None:
        """ON なら原画像全体と選択範囲を表示してドラッグ可能にし、OFF なら編集結果を表示する。"""
        if self.loaded is None:
            return
        overlay = self.drop_area.crop_overlay
        if enabled:
            self.drop_area.set_image(self.loaded.image)
            overlay.set_crop(self.settings_panel.settings().crop)
            overlay.set_active(True)
        else:
            overlay.set_active(False)
            self.update_preview()

    def _confirm_discard(self) -> bool:
        if not self.has_unsaved_changes():
            return True
        answer = QMessageBox.question(
            self,
            "未保存の変更",
            DISCARD_QUESTION,
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def _update_status(self, extra: str | None = None) -> None:
        """ステータスバーにファイル名・原寸・出力予定サイズを表示する。"""
        if self.loaded is None:
            self.status_label.setText(NO_IMAGE_MESSAGE)
            return
        width, height = self.loaded.image.size
        parts = [self.loaded.path.name, f"原寸 {width}×{height} px"]
        try:
            out_width, out_height = output_size(
                self.loaded.image.size, self.settings_panel.settings()
            )
            parts.append(f"出力 {out_width}×{out_height} px")
        except ValueError:
            parts.append("出力 —")
        message = " ｜ ".join(parts)
        notes = [*self._load_notes, *([extra] if extra else [])]
        if notes:
            message += "（" + "／".join(notes) + "）"
        self.status_label.setText(message)

    def _update_actions(self, busy: bool = False) -> None:
        enabled = self.loaded is not None and not busy
        self.save_action.setEnabled(enabled)
        self.preview_action.setEnabled(enabled)

    def _show_error(self, title: str, message: str, with_formats: bool = False) -> None:
        if with_formats:
            message += f"\n\n対応形式: {FORMATS_TEXT}"
        QMessageBox.warning(self, title, message)


def _first_extension(dialog_filter: str) -> str:
    """「JPEG (*.jpg *.jpeg)」のようなフィルター文字列から最初の拡張子を返す。"""
    start = dialog_filter.find("*.")
    if start < 0:
        return ".png"
    return dialog_filter[start + 1 :].split()[0].rstrip(")")
