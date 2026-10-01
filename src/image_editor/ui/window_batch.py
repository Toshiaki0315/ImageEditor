"""メインウィンドウのまとめて処理（一括処理）。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    Qt,
)
from PyQt6.QtWidgets import (
    QDialog,
    QMessageBox,
    QProgressDialog,
)

from image_editor.core.batch import BatchOptions, BatchResult
from image_editor.core.presets import (
    preset_from_settings,
)
from image_editor.ui.batch_dialog import BatchDialog
from image_editor.ui.worker import BatchTask

# 画像を開いていないときの、一括処理の長辺の初期値
DEFAULT_BATCH_LONG_SIDE = 2048


class BatchMixin:
    """メインウィンドウのまとめて処理（一括処理）。

    MainWindow に混ぜて使う（属性は MainWindow の __init__ で作る）。
    """

    def batch_dialog(self) -> None:
        """一括処理のダイアログを開き、「開始」なら処理を始める。

        かける加工は「今の加工」かプリセット。開いている画像があれば一覧に入れておく。
        """
        if self.is_busy():
            return
        panel = self.settings_panel
        width, height = panel.width_spin.value(), panel.height_spin.value()
        settings = panel.settings()
        dialog = BatchDialog(
            current_look=preset_from_settings("今の加工", settings),
            presets=panel.presets(),
            long_side=max(width, height) if self.loaded is not None else DEFAULT_BATCH_LONG_SIDE,
            resize=settings.width is not None or settings.height is not None,
            sources=[self.loaded.path] if self.loaded is not None else [],
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        out_dir = dialog.out_dir()
        if out_dir is None or not dialog.sources():
            return
        self.start_batch(dialog.sources(), out_dir, dialog.options(panel.save_options()))

    def start_batch(self, sources: list[Path], out_dir: Path, options: BatchOptions) -> bool:
        """一括処理をワーカースレッドで始め、進み具合と「中止」を出す。始められたら True。"""
        if self.is_busy() or not sources:
            return False
        task = BatchTask(sources, out_dir, options)
        task.setAutoDelete(False)  # 完了通知を受け取るまで Python 側で保持する
        progress = QProgressDialog("まとめて処理しています…", "中止", 0, len(sources), self)
        progress.setWindowTitle("まとめて処理")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)

        def on_cancel() -> None:
            task.cancel()
            progress.setLabelText("中止しています…（処理中の 1 枚が終わるまでお待ちください）")

        def on_progress(done: int, total: int, name: str) -> None:
            progress.setValue(done)
            progress.setLabelText(f"{done + 1} / {total} 枚目を処理しています… {name}")

        progress.canceled.connect(on_cancel)
        task.signals.progress.connect(on_progress)
        task.signals.finished.connect(
            lambda results, cancelled: self._on_batch_finished(results, cancelled, out_dir)
        )
        self._batch_task = task
        self._batch_progress = progress
        self._update_actions()
        self._thread_pool.start(task)
        return True

    def is_batch_running(self) -> bool:
        """一括処理の実行中かを返す。"""
        return self._batch_task is not None

    def _on_batch_finished(
        self, results: list[BatchResult], cancelled: bool, out_dir: Path
    ) -> None:
        if self._batch_progress is not None:
            self._batch_progress.close()
        self._batch_task = None
        self._batch_progress = None
        self._update_actions()
        saved = [r for r in results if r.output is not None]
        failed = [r for r in results if r.error is not None]
        head = "中止しました。" if cancelled else ""
        message = f"{head}{len(saved)} 枚を保存しました。\n保存先: {out_dir}"
        if failed:
            lines = "\n".join(f"・{r.source.name}（{r.error}）" for r in failed[:10])
            more = f"\n…ほか {len(failed) - 10} 枚" if len(failed) > 10 else ""
            message += f"\n\n{len(failed)} 枚は処理できませんでした:\n{lines}{more}"
        self._update_status(f"まとめて処理: {len(saved)} 枚を保存しました")
        QMessageBox.information(self, "まとめて処理", message)
        self.batch_finished.emit(results, cancelled)
