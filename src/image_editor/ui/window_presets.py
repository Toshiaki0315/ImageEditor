"""メインウィンドウのプリセットと文字・透かしのダイアログ。"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QInputDialog,
    QMessageBox,
)

from image_editor.core.presets import (
    Preset,
    PresetError,
    normalize_name,
    preset_from_settings,
    remove_preset,
    save_presets,
    upsert_preset,
)


def default_preset_name(presets: list[Preset]) -> str:
    """まだ使われていない「プリセット 1」「プリセット 2」… の名前を返す。"""
    names = {preset.name for preset in presets}
    number = 1
    while f"プリセット {number}" in names:
        number += 1
    return f"プリセット {number}"


class PresetMixin:
    """メインウィンドウのプリセットと文字・透かしのダイアログ。

    MainWindow に混ぜて使う（属性は MainWindow の __init__ で作る）。
    """

    def open_text_dialog(self) -> None:
        """文字・透かしのダイアログを開く（今の設定を表示する）。"""
        if self.loaded is None:
            return
        self.text_dialog.set_settings(self.settings_panel.text_settings())
        self.text_dialog.show()
        self.text_dialog.raise_()
        self.text_dialog.activateWindow()

    def save_preset_dialog(self) -> None:
        """今の加工を、名前を付けてプリセットとして保存する。同じ名前なら上書きを確認する。"""
        if self.loaded is None:
            return
        presets = self.settings_panel.presets()
        text, ok = QInputDialog.getText(
            self,
            "プリセットを保存",
            "プリセットの名前:",
            text=default_preset_name(presets),
        )
        name = normalize_name(text)
        if not ok or not name:
            return
        if any(preset.name == name for preset in presets):
            answer = QMessageBox.question(
                self,
                "プリセットを保存",
                f"プリセット「{name}」はすでにあります。上書きしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        preset = preset_from_settings(name, self.settings_panel.settings())
        if self._store_presets(upsert_preset(presets, preset)):
            self._update_status(f"プリセット「{name}」を保存しました")

    def delete_preset(self, name: str) -> None:
        """プリセットを確認のうえ削除する。"""
        answer = QMessageBox.question(
            self,
            "プリセットを削除",
            f"プリセット「{name}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._store_presets(remove_preset(self.settings_panel.presets(), name)):
            self._update_status(f"プリセット「{name}」を削除しました")

    def _store_presets(self, presets: list[Preset]) -> bool:
        """プリセットの一覧をファイルに書き、メニューに反映する。失敗したら通知して False。"""
        try:
            save_presets(self._presets_path, presets)
        except PresetError as e:  # NFR-04
            self._show_error("プリセットを保存できません", str(e))
            return False
        self.settings_panel.set_presets(presets)
        return True
