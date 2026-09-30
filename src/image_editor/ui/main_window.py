"""メインウィンドウ。"""

import os
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QEvent, QObject, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QWidget,
)

from image_editor.core.io import (
    SUPPORTED_EXTENSIONS,
    LoadedImage,
    UnsupportedImageError,
    is_supported,
    load_image,
)
from image_editor.core.pipeline import (
    EditSettings,
    effective_crop,
    make_preview,
    output_size,
    render_preview,
)
from image_editor.ui.drop_area import DropArea
from image_editor.ui.history import History
from image_editor.ui.settings_panel import PanelState, SettingsPanel
from image_editor.ui.worker import SaveTask

WINDOW_TITLE = "Image Editor"
INITIAL_SIZE = (1200, 800)
MINIMUM_SIZE = (900, 600)
SETTINGS_PANEL_WIDTH = 420  # 「加工」のラベル・スライダー (225px)・数値表示が欠けずに収まる幅

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
# 設定変更からプレビューを自動更新するまでの待ち時間 (FR-UI-40)
AUTO_PREVIEW_DELAY_MS = 300
# 設定の変更が落ち着いてから履歴に積むまでの待ち時間（続けて変えた分は 1 回の操作にまとめる）
HISTORY_DELAY_MS = 500
# 押している間だけ加工前の画像を表示するキー（JIS 配列の ¥ キーも同じ位置にある）
COMPARE_KEYS = (Qt.Key.Key_Backslash, Qt.Key.Key_yen)
COMPARE_BADGE_TEXT = "加工前"


SAME_FILE_MESSAGE = "元の画像と同じファイルには保存できません。別のファイル名を指定してください。"


def default_save_path(path: Path) -> Path:
    """保存ダイアログの初期パス `<元の名前>_edited.<元の拡張子>` を返す。

    すでにあれば `_edited_2`、`_edited_3` … と、既存のファイルと重ならない名前にする。
    """
    candidate = path.with_name(f"{path.stem}_edited{path.suffix}")
    number = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_edited_{number}{path.suffix}")
        number += 1
    return candidate


def is_same_file(a: Path, b: Path) -> bool:
    """2 つのパスが同じファイルを指すかを返す。

    macOS のファイルシステムは大文字・小文字を区別しないので、実在するファイルは
    os.path.samefile で判定し、まだ無いファイルは絶対パスを大文字・小文字を無視して比べる。
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return str(a.resolve()).casefold() == str(b.resolve()).casefold()


class MainWindow(QMainWindow):
    """左に D&D エリア、右に設定パネル、下にステータスバーを持つメインウィンドウ。"""

    save_finished = pyqtSignal(object)  # Path
    save_failed = pyqtSignal(object, str)  # Path, エラーメッセージ

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
        # プレビュー用の縮小版（長辺 1600px）と原本に対する縮小率
        self._preview: Image.Image | None = None
        self._preview_factor = 1.0
        # 表示中のプレビューを描いたときの条件（変わったときだけ描き直す）
        self._rendered_key: tuple[object, ...] | None = None
        # 実行中の保存タスクと、そのときの設定
        self._save_task: SaveTask | None = None
        self._saving_settings: EditSettings | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self._auto_preview_timer = QTimer(self)
        self._auto_preview_timer.setSingleShot(True)
        self._auto_preview_timer.setInterval(AUTO_PREVIEW_DELAY_MS)
        self._auto_preview_timer.timeout.connect(self._auto_preview)
        # アンドゥ／リドゥの履歴（設定パネルの状態のスナップショット）
        self._history: History[PanelState] = History(PanelState(EditSettings()))
        self._restoring = False
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(HISTORY_DELAY_MS)
        self._history_timer.timeout.connect(self._commit_history)
        # 加工前の画像を表示中か（\ キーか「加工前」ボタンを押している間）
        self._comparing = False

        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._on_files_dropped)
        self.settings_panel = SettingsPanel()
        self.settings_panel.setMinimumWidth(SETTINGS_PANEL_WIDTH)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.trim_view_toggled.connect(self._on_trim_view_toggled)
        self.drop_area.crop_overlay.crop_changed.connect(self.settings_panel.set_crop)
        self.settings_panel.save_requested.connect(self.save_file_dialog)
        self.settings_panel.reset_requested.connect(self.reset)
        self.settings_panel.compare_toggled.connect(self.set_comparing)
        # どのウィジェットにフォーカスがあっても \ キーで比べられるよう、アプリ全体のキーを見る
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        # 項目が多く、小さいウィンドウでは縦に収まらないので、設定パネルは縦にスクロールできる
        # ようにする（横はスクロールさせず、スクロールバーの分も含めて欠けない幅を確保する）
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidget(self.settings_panel)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_bar_width = self.settings_scroll.verticalScrollBar().sizeHint().width()
        self.settings_scroll.setMinimumWidth(SETTINGS_PANEL_WIDTH + scroll_bar_width)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.drop_area)
        splitter.addWidget(self.settings_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setChildrenCollapsible(False)
        panel_width = self.settings_scroll.minimumWidth()
        splitter.setSizes([INITIAL_SIZE[0] - panel_width, panel_width])
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

        edit_menu = self.menuBar().addMenu("編集")

        self.undo_action = QAction("元に戻す", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        edit_menu.addAction(self.undo_action)

        self.redo_action = QAction("やり直す", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo)
        edit_menu.addAction(self.redo_action)

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
        if self.is_saving() or not self._confirm_discard():
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

        self._comparing = False
        self.drop_area.set_badge(None)
        self.loaded = loaded
        self._preview, self._preview_factor = make_preview(loaded.image)
        self._saved_settings = None
        self._load_notes = list(notes or [])
        if loaded.is_animated:
            self._load_notes.append("複数フレームの画像のため、先頭フレームのみ扱います")
        # 画像の上ではいつでもドラッグでトリミング範囲を指定できる
        self.drop_area.crop_overlay.set_image_size(loaded.image.size)
        self.drop_area.crop_overlay.set_active(True)
        self.settings_panel.set_image_size(loaded.image.size)
        self._auto_preview_timer.stop()
        self.drop_area.set_image(self._preview)
        self._rendered_key = self._preview_key(self.settings_panel.settings())
        self._reset_history()
        # macOS のタイトルバーにファイル名と、クリックで場所を示すアイコンを出す
        self.setWindowTitle(f"{path.name} — {WINDOW_TITLE}")
        self.setWindowFilePath(str(path))
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
        """縮小版の画像にフィルターの色と周辺減光を適用してプレビューに表示する。

        通常は元の画角全体を表示してトリミング範囲をマスクで示し（いつでも選び直せる）、
        「トリミング実行」中は切り抜いた範囲に形とフレームを反映した完成形を表示する。リサイズは
        表示に反映せず、出力サイズはステータスバーに出す。
        """
        self._auto_preview_timer.stop()
        if self.loaded is None or self._preview is None:
            return
        settings = self.settings_panel.settings()
        shown = self._before_settings(settings) if self._comparing else settings
        try:
            rendered = render_preview(
                self._preview,
                shown,
                self._preview_factor,
                trimmed=self.settings_panel.is_trim_view(),
            )
        except Exception as e:  # NFR-04
            self._show_error("プレビューを更新できません", f"{type(e).__name__}: {e}")
            return
        self._rendered_key = self._preview_key(settings)
        self.drop_area.set_image(rendered)

    # --- 加工前との比較 ------------------------------------------------------

    def set_comparing(self, comparing: bool) -> None:
        """加工前の画像の表示を切り替える（押している間だけ True にする）。

        加工前は、向き（回転・反転）と表示範囲はそのままで、色の調整・テイスト・周辺減光・
        経年劣化・形・フレームを外したもの。表示中は左上に「加工前」と出す。
        """
        comparing = comparing and self.loaded is not None
        if comparing == self._comparing:
            return
        self._comparing = comparing
        self.drop_area.set_badge(COMPARE_BADGE_TEXT if comparing else None)
        self.update_preview()

    def is_comparing(self) -> bool:
        """加工前の画像を表示中かを返す。"""
        return self._comparing

    def _before_settings(self, settings: EditSettings) -> EditSettings:
        """加工前の表示用の設定。向きと、実際に切り抜く範囲だけを残す。"""
        assert self.loaded is not None
        size = settings.orientation.size(self.loaded.image.size)
        # フレーム・円の比に合わせた範囲も、そのままの範囲で見比べられるようにする
        crop = effective_crop(size, settings.crop, settings.frame, settings.shape)
        return EditSettings(orientation=settings.orientation, crop=crop)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if (
            isinstance(event, QKeyEvent)
            and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
            and event.key() in COMPARE_KEYS
            and self.isActiveWindow()
            and self.loaded is not None
        ):
            if not event.isAutoRepeat():
                self.set_comparing(event.type() == QEvent.Type.KeyPress)
            return True  # 数値欄などに文字として入らないようにする
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent | None) -> None:
        # キーを押したまま別のウィンドウに切り替えると離したことが届かないので、ここで戻す
        if (
            event is not None
            and event.type() == QEvent.Type.ActivationChange
            and not self.isActiveWindow()
        ):
            self.set_comparing(False)
        super().changeEvent(event)

    def save_file_dialog(self) -> None:
        """保存ダイアログを開き、原寸で処理して書き出す。"""
        if self.loaded is None:
            return
        selected_filter = SAVE_DIALOG_FILTERS.get(self.loaded.format, "")
        # 元の画像と同じファイルが選ばれたら、通知してダイアログを開き直す
        while True:
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
            if not is_same_file(path, self.loaded.path):
                break
            self._show_error("保存できません", SAME_FILE_MESSAGE)
        self.save_to(path)

    def save_to(self, path: Path) -> bool:
        """現在の設定を原寸で適用して保存する処理をワーカースレッドで開始する。

        開始できたら True を返す。完了すると save_finished、失敗すると save_failed を発行する。
        処理中はボタンを無効化する。
        """
        if self.loaded is None or self.is_saving():
            return False
        if is_same_file(path, self.loaded.path):
            # 元の画像は上書きしない
            self._show_error("保存できません", SAME_FILE_MESSAGE)
            return False
        self._saving_settings = self.settings_panel.settings()
        task = SaveTask(self.loaded.image, self._saving_settings, path)
        # 完了通知を受け取るまで Python 側で保持する
        task.setAutoDelete(False)
        task.signals.finished.connect(self._on_save_finished)
        task.signals.failed.connect(self._on_save_failed)
        self._save_task = task
        self._set_busy(True)
        self._update_status(f"保存中… {path.name}")
        self._thread_pool.start(task)
        return True

    def is_saving(self) -> bool:
        """保存処理中かを返す。"""
        return self._save_task is not None

    def _on_save_finished(self, path: Path) -> None:
        self._saved_settings = self._saving_settings
        self._finish_save()
        self._update_status(f"保存しました: {path.name}")
        self.save_finished.emit(path)

    def _on_save_failed(self, path: Path, message: str) -> None:
        self._finish_save()
        self._update_status()
        self._show_error("保存できません", f"{path.name}\n({message})")
        self.save_failed.emit(path, message)

    def _finish_save(self) -> None:
        self._save_task = None
        self._saving_settings = None
        self._set_busy(False)

    def reset(self) -> None:
        """画像と設定を未読込の状態に戻す。未保存の変更があれば確認する。"""
        if self.is_saving() or not self._confirm_discard():
            return
        self._auto_preview_timer.stop()
        self._comparing = False
        self.drop_area.set_badge(None)
        self.loaded = None
        self._preview = None
        self._rendered_key = None
        self._saved_settings = None
        self._load_notes = []
        self.drop_area.crop_overlay.set_active(False)
        self.drop_area.crop_overlay.set_image_size(None)
        self.drop_area.set_image(None)
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFilePath("")
        self.settings_panel.set_image_size(None)
        self._reset_history()
        self._update_status()
        self._update_actions()

    # --- アンドゥ／リドゥ -----------------------------------------------------

    def undo(self) -> None:
        """設定の変更を 1 つ元に戻す（まだ履歴に積んでいない変更があれば、それを戻す）。"""
        if self.loaded is None or self.is_saving():
            return
        self._commit_history(force=True)
        if self._history.can_undo():
            self._restore_history(self._history.undo())

    def redo(self) -> None:
        """元に戻した変更を 1 つやり直す。"""
        if self.loaded is None or self.is_saving():
            return
        self._commit_history(force=True)
        if self._history.can_redo():
            self._restore_history(self._history.redo())

    def _commit_history(self, force: bool = False) -> None:
        """今の状態を履歴に積む。

        スライダーや範囲をドラッグしている間は待つ（ドラッグ全体を 1 回の操作にする）。
        force なら待たずに積む。
        """
        self._history_timer.stop()
        if self.loaded is None:
            return
        dragging = self.settings_panel.is_adjusting() or self.drop_area.crop_overlay.is_dragging()
        if dragging and not force:
            self._history_timer.start()
            return
        self._history.push(self.settings_panel.snapshot())
        self._update_actions()

    def _restore_history(self, state: PanelState) -> None:
        self._restoring = True
        try:
            self.settings_panel.restore(state)
        finally:
            self._restoring = False
        self._history_timer.stop()
        self._update_actions()

    def _reset_history(self) -> None:
        """履歴を消して、今の状態を始まりにする（画像の読み込み・リセット時）。"""
        self._history_timer.stop()
        self._history.reset(self.settings_panel.snapshot())
        self._update_actions()

    def has_unsaved_changes(self) -> bool:
        """初期状態から設定を変えていて、その設定でまだ保存していなければ True。"""
        if self.loaded is None:
            return False
        settings = self.settings_panel.settings()
        return settings != EditSettings() and settings != self._saved_settings

    # --- 内部 -----------------------------------------------------------------

    def _on_settings_changed(self, settings: EditSettings) -> None:
        if self.loaded is not None and not self._restoring:
            # 続けて変えた分は、落ち着いてから 1 回の操作として履歴に積む
            self._history_timer.start()
            self._update_actions()
        overlay = self.drop_area.crop_overlay
        overlay.set_aspect(*self.settings_panel.crop_aspect())
        # 回転・反転で画像の向きが変わったら、範囲選択の座標系も合わせる
        image_size = self.settings_panel.image_size()
        if image_size is not None and overlay.image_size() != image_size:
            overlay.set_image_size(image_size)
        # ドラッグ中の変更はオーバーレイ自身が発生源なので書き戻さない
        if not overlay.is_dragging():
            overlay.set_crop(settings.crop)
        if not self.is_saving():
            self._update_status()
        # 表示に影響する設定が変わったときだけ描き直す
        if self.loaded is not None and self._preview_key(settings) != self._rendered_key:
            rendered = self._rendered_key
            if rendered is not None and rendered[0] != settings.orientation:  # [0] は向き
                # 向きが変わったら、範囲選択の座標系とずれないようすぐに描き直す
                self.update_preview()
            else:
                self._auto_preview_timer.start()

    def _preview_key(self, settings: EditSettings) -> tuple[object, ...]:
        """プレビューの見た目を決める条件。サイズ変更は表示に反映しないので含めない。"""
        trimmed = self.settings_panel.is_trim_view()
        # トリミング範囲・フレーム・形（写真部分や円の比率への切り抜き）は、切り抜き表示中か
        # 周辺減光があるときだけ見た目に影響する
        affects_view = trimmed or bool(settings.vignette)
        crop = settings.crop if affects_view else None
        frame = settings.frame if affects_view else None
        shape = (settings.shape, settings.corner_radius) if affects_view else None
        return (
            settings.orientation,
            settings.filter,
            settings.temperature,
            settings.saturation,
            settings.exposure,
            settings.brightness,
            settings.contrast,
            settings.vignette,
            settings.aging,
            crop,
            frame,
            shape,
            trimmed,
            self._comparing,
        )

    def _on_trim_view_toggled(self, trimmed: bool) -> None:
        """切り抜き後の表示ではドラッグでの範囲選択を止め、全体表示に戻したら再開する。"""
        if self.loaded is None:
            return
        self.drop_area.crop_overlay.set_active(not trimmed)
        self.update_preview()

    def _auto_preview(self) -> None:
        if self.loaded is not None:
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

    def _update_actions(self) -> None:
        busy = self.is_saving()
        enabled = self.loaded is not None and not busy
        self.save_action.setEnabled(enabled)
        self.open_action.setEnabled(not busy)
        self.drop_area.setAcceptDrops(not busy)
        # まだ履歴に積んでいない変更があれば、それを元に戻せる
        pending = self.loaded is not None and (
            self.settings_panel.snapshot() != self._history.current()
        )
        self.undo_action.setEnabled(enabled and (self._history.can_undo() or pending))
        self.redo_action.setEnabled(enabled and self._history.can_redo() and not pending)

    def _set_busy(self, busy: bool) -> None:
        self.settings_panel.set_busy(busy)
        self._update_actions()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        # 保存中のファイルが途中で切れないよう、完了を待ってから閉じる
        if self.is_saving():
            self._thread_pool.waitForDone()
        super().closeEvent(event)

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
