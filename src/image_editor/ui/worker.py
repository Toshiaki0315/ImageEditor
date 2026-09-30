"""重い処理（原寸処理・保存）をワーカースレッドで実行する。"""

import threading
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from image_editor.core.batch import BatchOptions, run_batch
from image_editor.core.io import SaveOptions, prepare_exif, save_image
from image_editor.core.pipeline import EditSettings, apply_edits


class SaveSignals(QObject):
    """SaveTask の完了通知。UI スレッドで作るので、接続先はキュー経由で UI スレッドで動く。"""

    finished = pyqtSignal(object)  # Path
    failed = pyqtSignal(object, str)  # Path, エラーメッセージ


class SaveTask(QRunnable):
    """原画像に編集を適用して保存するタスク（QThreadPool で実行する）。"""

    def __init__(
        self,
        original: Image.Image,
        settings: EditSettings,
        path: Path,
        options: SaveOptions | None = None,
        exif: bytes | None = None,
    ) -> None:
        """exif は元画像の EXIF。options.keep_exif のときだけ、整えて書き込む。"""
        super().__init__()
        # UI 側で原本を読み続けても競合しないよう、自分用のコピーを持つ
        self._original = original.copy()
        self._settings = settings
        self._path = path
        self._options = options or SaveOptions()
        self._exif = exif
        self.signals = SaveSignals()

    def run(self) -> None:
        """ワーカースレッドで呼ばれる。結果はシグナルで返す。"""
        try:
            edited = apply_edits(self._original, self._settings)
            exif = None
            if self._options.keep_exif and self._exif is not None:
                exif = prepare_exif(self._exif, edited.size, keep_gps=self._options.keep_gps)
            save_image(edited, self._path, quality=self._options.quality, exif=exif)
        except Exception as e:  # 例外はスレッド外に出さず UI に通知する (NFR-04)
            self.signals.failed.emit(self._path, f"{type(e).__name__}: {e}")
        else:
            self.signals.finished.emit(self._path)


class BatchSignals(QObject):
    """BatchTask の通知。UI スレッドで作るので、接続先はキュー経由で UI スレッドで動く。"""

    progress = pyqtSignal(int, int, str)  # 処理済みの枚数, 全体の枚数, 次の画像の名前
    finished = pyqtSignal(object, bool)  # list[BatchResult], 中止したか


class BatchTask(QRunnable):
    """複数の画像に同じ加工をかけて保存するタスク（QThreadPool で実行する）。

    cancel() を呼ぶと、処理中の 1 枚を終えたところで止まる。
    """

    def __init__(self, sources: list[Path], out_dir: Path, options: BatchOptions) -> None:
        super().__init__()
        self._sources = list(sources)
        self._out_dir = out_dir
        self._options = options
        self._cancel = threading.Event()
        self.signals = BatchSignals()

    def cancel(self) -> None:
        """中止を求める（UI スレッドから呼んでよい）。"""
        self._cancel.set()

    def run(self) -> None:
        """ワーカースレッドで呼ばれる。結果はシグナルで返す。"""
        total = len(self._sources)
        results = run_batch(
            self._sources,
            self._out_dir,
            self._options,
            progress=lambda done, source: self.signals.progress.emit(done, total, source.name),
            cancelled=self._cancel.is_set,
        )
        self.signals.finished.emit(results, self._cancel.is_set() and len(results) < total)
