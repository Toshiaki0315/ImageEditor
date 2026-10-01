"""設定パネルの状態の取り出し・戻し、プリセット・文字・加工のリセット。"""

from __future__ import annotations

from image_editor.core.pipeline import EditSettings
from image_editor.core.presets import Preset, apply_preset
from image_editor.core.text import TextSettings
from image_editor.core.transform import (
    CropRect,
    fit_size,
)
from image_editor.ui.panel_parts import (
    PanelState,
)


class StateMixin:
    """設定パネルの状態の取り出し・戻し、プリセット・文字・加工のリセット。

    SettingsPanel に混ぜて使う（属性は SettingsPanel の __init__ で作る）。
    """

    def snapshot(self) -> PanelState:
        """アンドゥ／リドゥ用に今の状態を返す。"""
        return PanelState(
            settings=self.settings(),
            aspect=self.aspect_preset(),
            portrait=self.portrait_check.isChecked(),
        )

    def restore(self, state: PanelState) -> None:
        """snapshot() で取った状態に戻す（画像は変えない）。変更は 1 回だけ通知する。

        比の固定で範囲を直したりせず、取ったときの値をそのまま戻す。
        """
        if self._image_size is None:
            return
        settings = state.settings
        # 回転・反転前の大きさ（向きによる幅と高さの入れ替えは、もう一度かけると元に戻る）
        source_size = self._orientation.size(self._image_size)
        self._orientation = settings.orientation
        self._image_size = settings.orientation.size(source_size)
        crop = settings.crop or CropRect(0, 0, 0, 0)
        with self._block():
            self._set_crop_limits(self._image_size)
            self._set_crop_spins(crop)
            self._committed_crop = self._clamped_range()
            self._set_look_controls(settings)
            self._aspect_index = self.aspect_combo.findData(state.aspect)
            self.aspect_combo.setCurrentIndex(self._aspect_index)
            self.portrait_check.setChecked(state.portrait)
            self.keep_aspect_check.setChecked(settings.keep_aspect)
            # 幅・高さは、指定がなければトリミング後のサイズ、あれば指定から計算した値
            base = self.base_size()
            if settings.width is None and settings.height is None:
                self._size_edited = False
                self._last_edited = "width"
                self._set_size_spins(base)
            else:
                self._size_edited = True
                self._last_edited = "width" if settings.width is not None else "height"
                self._set_size_spins(
                    fit_size(base, settings.width, settings.height, settings.keep_aspect)
                )
        self._update_corner_enabled()
        self._update_aspect_controls()
        self._emit_changed()

    def set_presets(self, presets: list[Preset]) -> None:
        """プリセットの一覧を「プリセット」メニューに反映する。

        メニュー: 一覧（選ぶと当てはめる）／「今の加工を保存…」／「削除」（一覧のサブメニュー）
        """
        self._presets = list(presets)
        menu = self.preset_menu
        menu.clear()
        if presets:
            for preset in presets:
                action = menu.addAction(preset.name)
                action.triggered.connect(lambda _=False, p=preset: self.apply_preset(p))
        else:
            empty = menu.addAction("（保存したプリセットはありません）")
            empty.setEnabled(False)
        menu.addSeparator()
        save = menu.addAction("今の加工をプリセットとして保存…")
        save.triggered.connect(self.preset_save_requested)
        delete_menu = menu.addMenu("削除")
        delete_menu.setEnabled(bool(presets))
        for preset in presets:
            action = delete_menu.addAction(preset.name)
            action.triggered.connect(
                lambda _=False, name=preset.name: self.preset_delete_requested.emit(name)
            )

    def text_settings(self) -> TextSettings:
        """今の文字・透かしの設定を返す。"""
        return self._text

    def set_text_settings(self, settings: TextSettings) -> None:
        """文字・透かしの設定を変える（変われば settings_changed を発行する）。"""
        if self._image_size is None or settings == self._text:
            return
        self._text = settings
        self._emit_changed()

    def presets(self) -> list[Preset]:
        """「プリセット」メニューに出している一覧を返す。"""
        return list(self._presets)

    def apply_preset(self, preset: Preset) -> None:
        """プリセットの加工（テイスト・色の調整・フレーム・形・角丸）を当てはめる。

        サイズ変更・トリミング・回転はそのまま。フレーム・円の比が変われば、フレームや形を
        手で選んだときと同じく範囲をその比に直す。変更は 1 回だけ通知する。
        """
        if self._image_size is None:
            return
        settings = apply_preset(self.settings(), preset)
        with self._block():
            self._set_look_controls(settings)
        self._update_corner_enabled()
        self._on_aspect_source_changed()

    def _set_look_controls(self, settings: EditSettings) -> None:
        """テイスト・フレーム・形・文字・ジオラマとスライダーを settings に合わせる。

        通知はしない（_block の中で呼ぶ）。
        """
        self.filter_combo.setCurrentIndex(self.filter_combo.findData(settings.filter))
        self.frame_combo.setCurrentIndex(self.frame_combo.findData(settings.frame))
        self.shape_combo.setCurrentIndex(self.shape_combo.findData(settings.shape))
        combo = self.diorama_direction_combo
        combo.setCurrentIndex(combo.findData(settings.diorama_direction))
        self._text = settings.text
        for item in self._adjustments:
            item.set_value(getattr(settings, item.field))

    def reset_adjustments(self) -> None:
        """テイストと色のスライダー（露出〜経年劣化）を既定値に戻す。

        画像・サイズ変更・トリミング・フレーム・形・角丸はそのまま残す。変更は 1 回だけ通知する。
        """
        with self._block():
            self.filter_combo.setCurrentIndex(0)
            for slider in self._adjustment_sliders():
                slider.reset()
        self._emit_changed()

    def is_adjusting(self) -> bool:
        """スライダーをドラッグ中かを返す（ドラッグ中の変更は 1 回の操作としてまとめる）。"""
        return any(item.slider.isSliderDown() for item in self._adjustments)
