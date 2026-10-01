"""メインウィンドウ。"""

from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import (
    QSettings,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QScrollArea,
    QSplitter,
    QWidget,
)

from image_editor.core.exif_info import ExifInfo, exif_info_of
from image_editor.core.histogram import Histogram
from image_editor.core.io import (
    SUPPORTED_EXTENSIONS,
    LoadedImage,
    SaveOptions,
    UnsupportedImageError,
    default_save_path,
    is_same_file,
    is_savable,
    load_image,
)
from image_editor.core.pipeline import (
    EditSettings,
    effective_crop,
    make_preview,
    output_size,
    render_preview_with_histogram,
)
from image_editor.core.presets import (
    PresetError,
    load_presets,
)
from image_editor.ui.drop_area import DropArea
from image_editor.ui.history import History
from image_editor.ui.settings_panel import PanelState, SettingsPanel
from image_editor.ui.text_dialog import TextDialog
from image_editor.ui.window_batch import BatchMixin
from image_editor.ui.window_history import HistoryMixin
from image_editor.ui.window_presets import (  # noqa: F401 - 外からも使う
    PresetMixin,
    default_preset_name,
)
from image_editor.ui.window_view import PREF_SHOW_HISTOGRAM, ViewMixin
from image_editor.ui.worker import BatchTask, SaveTask, ZoomTask

WINDOW_TITLE = "Image Editor"
INITIAL_SIZE = (1200, 800)
MINIMUM_SIZE = (900, 600)
SETTINGS_PANEL_WIDTH = 420  # 「加工」のラベル・スライダー (225px)・数値表示が欠けずに収まる幅

NO_IMAGE_MESSAGE = "画像が読み込まれていません"
FORMATS_TEXT = "PNG / JPEG / GIF / TIFF / BMP（HEIC / HEIF は読み込みのみ）"
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


# 保存の設定をアプリの環境設定に残すキー
PREF_JPEG_QUALITY = "save/jpeg_quality"
PREF_KEEP_EXIF = "save/keep_exif"
PREF_KEEP_GPS = "save/keep_gps"
PREF_PANEL_TAB = "panel/tab"  # 設定パネルで最後に開いていたタブ


PRESETS_FILE = Path.home() / "Library" / "Application Support" / "ImageEditor" / "presets.json"


def default_presets_path() -> Path:
    """プリセットの保存先（~/Library/Application Support/ImageEditor/presets.json）。"""
    return PRESETS_FILE


def default_preferences() -> QSettings:
    """アプリの環境設定の保存先（macOS では ~/Library/Preferences の plist）。"""
    return QSettings()


def load_save_options(preferences: QSettings) -> SaveOptions:
    """環境設定から保存の設定を読む。なければ既定値。"""
    default = SaveOptions()
    return SaveOptions(
        quality=int(preferences.value(PREF_JPEG_QUALITY, default.quality, type=int)),
        keep_exif=bool(preferences.value(PREF_KEEP_EXIF, default.keep_exif, type=bool)),
        keep_gps=bool(preferences.value(PREF_KEEP_GPS, default.keep_gps, type=bool)),
    )


def store_save_options(preferences: QSettings, options: SaveOptions) -> None:
    """保存の設定を環境設定に書く（アプリを終了しても残す）。"""
    preferences.setValue(PREF_JPEG_QUALITY, options.quality)
    preferences.setValue(PREF_KEEP_EXIF, options.keep_exif)
    preferences.setValue(PREF_KEEP_GPS, options.keep_gps)


SAME_FILE_MESSAGE = "元の画像と同じファイルには保存できません。別のファイル名を指定してください。"


class MainWindow(ViewMixin, BatchMixin, PresetMixin, HistoryMixin, QMainWindow):
    """左に D&D エリア、右に設定パネル、下にステータスバーを持つメインウィンドウ。"""

    save_finished = pyqtSignal(object)  # Path
    save_failed = pyqtSignal(object, str)  # Path, エラーメッセージ
    batch_finished = pyqtSignal(object, bool)  # list[BatchResult], 中止したか

    def __init__(self, parent: QWidget | None = None, preferences: QSettings | None = None) -> None:
        """preferences は保存の設定を残す先（省略時は default_preferences()）。"""
        super().__init__(parent)
        self._preferences = preferences if preferences is not None else default_preferences()
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
        # 実行中の一括処理と、その進み具合の表示
        self._batch_task: BatchTask | None = None
        self._batch_progress: QProgressDialog | None = None
        # 実行中の保存タスクと、そのときの設定
        self._save_task: SaveTask | None = None
        self._saving_settings: EditSettings | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self._auto_preview_timer = self._single_shot_timer(
            AUTO_PREVIEW_DELAY_MS, self._auto_preview
        )
        # アンドゥ／リドゥの履歴（設定パネルの状態のスナップショット）
        self._history: History[PanelState] = History(PanelState(EditSettings()))
        self._restoring = False
        self._history_timer = self._single_shot_timer(HISTORY_DELAY_MS, self._commit_history)
        # 加工前の画像を表示中か（\ キーか「加工前」ボタンを押している間）
        self._comparing = False
        # 100% 表示: 表示中か、最新の依頼の番号、最新の依頼を処理中か、表示の中央にしたい点
        self._zoomed = False
        self._zoom_generation = 0
        self._zoom_pending = False
        # 実行中のタスクはすべて終わるまで保持する（実行中に Python 側で片付けられると落ちる）
        self._zoom_tasks: set[ZoomTask] = set()
        self._zoom_center: tuple[float, float] | None = None
        self._zoom_timer = self._single_shot_timer(AUTO_PREVIEW_DELAY_MS, self._render_zoom)
        # 表示中のプレビューのヒストグラム（保存される写真の分布）
        self._histogram: Histogram | None = None

        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._on_files_dropped)
        self.settings_panel = SettingsPanel()
        self.settings_panel.setMinimumWidth(SETTINGS_PANEL_WIDTH)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.trim_view_toggled.connect(self._on_trim_view_toggled)
        self.drop_area.crop_overlay.crop_changed.connect(self.settings_panel.set_crop)
        self.settings_panel.save_requested.connect(self.save_file_dialog)
        self.settings_panel.reset_requested.connect(self.reset)
        # 保存の設定（JPEG 品質・EXIF）は画像ごとに戻さず、アプリを終了しても残す
        self.settings_panel.set_save_options(load_save_options(self._preferences))
        self.settings_panel.save_options_changed.connect(
            lambda options: store_save_options(self._preferences, options)
        )
        # 最後に開いていたタブを次に起動したときも開く
        self.settings_panel.set_current_tab(
            int(self._preferences.value(PREF_PANEL_TAB, 0, type=int))
        )
        self.settings_panel.tab_changed.connect(
            lambda index: self._preferences.setValue(PREF_PANEL_TAB, index)
        )
        # 「ジオラマ」タブを開いている間だけ、プレビューにピントの帯のガイドを出す
        self.settings_panel.tab_changed.connect(lambda _: self._update_diorama_guide())
        self.settings_panel.compare_toggled.connect(self.set_comparing)
        # 文字・透かしのダイアログ（開いたまま調整でき、変更はすぐ設定に反映する）
        self.text_dialog = TextDialog(self)
        self.text_dialog.settings_changed.connect(self.settings_panel.set_text_settings)
        self.settings_panel.text_dialog_requested.connect(self.open_text_dialog)
        self.drop_area.double_clicked.connect(self._on_preview_double_clicked)
        # プリセット（名前付きの加工の組み合わせ）
        self._presets_path = default_presets_path()
        self.settings_panel.preset_save_requested.connect(self.save_preset_dialog)
        self.settings_panel.preset_delete_requested.connect(self.delete_preset)
        try:
            self.settings_panel.set_presets(load_presets(self._presets_path))
        except PresetError as e:
            # ウィンドウを出してから知らせる（アプリは使えるようにする）
            message = str(e)
            QTimer.singleShot(0, lambda: self._show_error("プリセットを読み込めません", message))
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

    def _single_shot_timer(self, interval_ms: int, slot: Callable[[], object]) -> QTimer:
        """start() のたびに数え直し、interval_ms 後に 1 回だけ slot を呼ぶタイマーを作る。"""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval_ms)
        timer.timeout.connect(slot)
        return timer

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

        self.batch_action = QAction("まとめて処理…", self)
        self.batch_action.triggered.connect(self.batch_dialog)
        file_menu.addAction(self.batch_action)

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

        edit_menu.addSeparator()
        self.text_action = QAction("文字・透かし…", self)
        self.text_action.setShortcut(QKeySequence("Ctrl+T"))
        self.text_action.triggered.connect(self.open_text_dialog)
        edit_menu.addAction(self.text_action)

        view_menu = self.menuBar().addMenu("表示")

        # ⌘H は macOS で「隠す」なので ⇧⌘H にする
        self.histogram_action = QAction("ヒストグラム", self)
        self.histogram_action.setCheckable(True)
        self.histogram_action.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.histogram_action.setChecked(
            bool(self._preferences.value(PREF_SHOW_HISTOGRAM, True, type=bool))
        )
        self.histogram_action.toggled.connect(self._on_histogram_toggled)
        view_menu.addAction(self.histogram_action)

        view_menu.addSeparator()
        # 100% 表示は、原寸で処理した保存結果を画像 1px = 画面の 1 画素で見せる
        self.zoom_action = QAction("100% で表示", self)
        self.zoom_action.setShortcut(QKeySequence("Ctrl+1"))
        self.zoom_action.triggered.connect(lambda: self.show_actual_size())
        view_menu.addAction(self.zoom_action)

        self.fit_action = QAction("画面に合わせる", self)
        self.fit_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_action.triggered.connect(self.fit_to_window)
        view_menu.addAction(self.fit_action)

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
        self._leave_zoom()
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
        self.settings_panel.set_exif_info(_exif_info(loaded))
        # 初期状態のプレビューとヒストグラムを描く
        self.update_preview()
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

    # --- プレビュー ---------------------------------------------------------------

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
            rendered, histogram = render_preview_with_histogram(
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
        self._histogram = histogram
        self._show_histogram()

    # --- 保存・リセット -----------------------------------------------------------

    def save_file_dialog(self) -> None:
        """保存ダイアログを開き、原寸で処理して書き出す。"""
        if self.loaded is None:
            return
        # 保存できない形式（HEIC など）を開いたときは JPEG で保存する
        selected_filter = SAVE_DIALOG_FILTERS.get(self.loaded.format, SAVE_DIALOG_FILTERS["JPEG"])
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
            if not is_savable(path):
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
        task = SaveTask(
            self.loaded.image,
            self._saving_settings,
            path,
            options=self.settings_panel.save_options(),
            exif=self.loaded.exif,
        )
        # 完了通知を受け取るまで Python 側で保持する
        task.setAutoDelete(False)
        task.signals.finished.connect(self._on_save_finished)
        task.signals.failed.connect(self._on_save_failed)
        self._save_task = task
        self._set_busy(True)
        self._update_status(f"保存中… {path.name}")
        self._thread_pool.start(task)
        return True

    def is_busy(self) -> bool:
        """保存か一括処理の実行中かを返す。"""
        return self.is_saving() or self.is_batch_running()

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
        self._leave_zoom()
        self.loaded = None
        self._preview = None
        self._rendered_key = None
        self._saved_settings = None
        self._load_notes = []
        self.drop_area.crop_overlay.set_active(False)
        self.drop_area.crop_overlay.set_image_size(None)
        self.drop_area.set_image(None)
        self._histogram = None
        self._show_histogram()
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFilePath("")
        self.settings_panel.set_image_size(None)
        self._reset_history()
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
        # アンドゥ・プリセット・画像の読み込みで文字が変わったら、ダイアログの表示も合わせる
        self.text_dialog.set_settings(settings.text)
        if self._zoomed:
            # 100% 表示中は、変更が落ち着いてから原寸で処理し直す
            self._zoom_timer.start()
            self._update_badge()
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
        # 角丸・円は、実際に切り抜く範囲（なければ画像全体）にかけた形をマスクで見せる
        area = None
        if image_size is not None:
            area = effective_crop(image_size, settings.crop, settings.frame, settings.shape)
        overlay.set_shape(settings.shape, settings.corner_radius, area)
        self._update_diorama_guide()
        if not self.is_saving():
            self._update_status()
        # 表示に影響する設定が変わったときだけ描き直す
        if self.loaded is not None and self._preview_key(settings) != self._rendered_key:
            rendered = self._rendered_key
            if rendered is not None and rendered[0].orientation != settings.orientation:
                # 向きが変わったら、範囲選択の座標系とずれないようすぐに描き直す
                self.update_preview()
            else:
                self._auto_preview_timer.start()

    def _preview_key(self, settings: EditSettings) -> tuple[object, ...]:
        """プレビューの見た目（ヒストグラムを含む）を決める条件。

        描画は設定のほぼすべてを使う（トリミング範囲・フレーム・形・角丸はヒストグラムと
        文字の位置に、出力サイズはシャープの効き方に効く）ので、設定全体を条件にする。
        項目を手で選ぶと、項目を足したときに描き直しが漏れる。
        """
        return (settings, self.settings_panel.is_trim_view(), self._comparing)

    def _on_trim_view_toggled(self, trimmed: bool) -> None:
        """切り抜き後の表示ではドラッグでの範囲選択を止め、全体表示に戻したら再開する。"""
        if self.loaded is None:
            return
        self.drop_area.crop_overlay.set_active(not trimmed and not self._zoomed)
        self._update_diorama_guide()
        self.update_preview()

    def _auto_preview(self) -> None:
        if self.loaded is not None:
            self.update_preview()

    def _confirm_discard(self) -> bool:
        if not self.has_unsaved_changes():
            return True
        return self._confirm("未保存の変更", DISCARD_QUESTION, QMessageBox.StandardButton.Discard)

    def _confirm(
        self,
        title: str,
        question: str,
        accept: QMessageBox.StandardButton = QMessageBox.StandardButton.Yes,
    ) -> bool:
        """accept と「キャンセル」の確認ダイアログを出し、accept が押されたら True。

        既定のボタンは「キャンセル」（Return で誤って進まないように）。
        """
        answer = QMessageBox.question(
            self,
            title,
            question,
            accept | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == accept

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
        busy = self.is_busy()
        enabled = self.loaded is not None and not busy
        self.save_action.setEnabled(enabled)
        self.open_action.setEnabled(not busy)
        self.text_action.setEnabled(self.loaded is not None)
        self.zoom_action.setEnabled(self.loaded is not None and not self._zoomed)
        self.fit_action.setEnabled(self._zoomed)
        self.batch_action.setEnabled(not busy)
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
        # 保存中のファイルが途中で切れないよう、完了を待ってから閉じる（一括処理は中止を求める）
        if self._batch_task is not None:
            self._batch_task.cancel()
        if self.is_busy() or self._zoom_tasks:
            self._thread_pool.waitForDone()
        super().closeEvent(event)

    def _show_error(self, title: str, message: str, with_formats: bool = False) -> None:
        if with_formats:
            message += f"\n\n対応形式: {FORMATS_TEXT}"
        QMessageBox.warning(self, title, message)


def _exif_info(loaded: LoadedImage) -> ExifInfo | None:
    """EXIF タブに出す情報。読めなくても画像の読み込みは続ける (NFR-04)。"""
    try:
        return exif_info_of(loaded)
    except Exception:
        return None


def _first_extension(dialog_filter: str) -> str:
    """「JPEG (*.jpg *.jpeg)」のようなフィルター文字列から最初の拡張子を返す。"""
    start = dialog_filter.find("*.")
    if start < 0:
        return ".png"
    return dialog_filter[start + 1 :].split()[0].rstrip(")")
