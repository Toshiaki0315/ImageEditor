"""メインウィンドウのアンドゥ／リドゥ。"""

from __future__ import annotations

from image_editor.ui.panel_parts import PanelState


class HistoryMixin:
    """メインウィンドウのアンドゥ／リドゥ。

    MainWindow に混ぜて使う（属性は MainWindow の __init__ で作る）。
    """

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
