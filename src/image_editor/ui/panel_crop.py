"""設定パネルのトリミング・縦横比・回転・反転の処理。"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QPushButton,
    QSpinBox,
)

from image_editor.core.frames import FrameType, window_aspect
from image_editor.core.pipeline import effective_crop
from image_editor.core.shapes import (
    ShapeType,
)
from image_editor.core.transform import (
    MIN_SIZE,
    AspectRatio,
    CropRect,
    Orientation,
    OrientOp,
    clamp_crop,
    constrain_rect,
    fit_aspect,
    transform_rect,
)
from image_editor.ui.panel_parts import (
    EDIT_RANGE_TEXT,
    TRIM_TEXT,
)


class CropMixin:
    """設定パネルのトリミング・縦横比・回転・反転の処理。

    SettingsPanel に混ぜて使う（属性は SettingsPanel の __init__ で作る）。
    """

    def crop_aspect(self) -> tuple[tuple[float, float] | None, bool]:
        """トリミング範囲に保たせる縦横比 (幅, 高さ) と、向きを自由にするかを返す。

        フレームがあれば写真部分の比（チェキは範囲の形に合わせて縦横どちらにもなる）、
        フレームなしの円は 1:1、それ以外は比のプルダウンの選択（自由なら None）。
        """
        size = self._range_size()
        aspect = self._aspect_for(size)
        free = self.frame() is not FrameType.NONE and aspect is not None and aspect[0] != aspect[1]
        return aspect, free

    def is_aspect_locked_by_frame(self) -> bool:
        """フレーム・円に合わせて比を固定しているかを返す。"""
        return self.frame() is not FrameType.NONE or self.shape() is ShapeType.CIRCLE

    def set_crop(self, rect: CropRect | None) -> None:
        """トリミング範囲を設定する（原画像の座標系）。None で解除。

        比を指定しているときは、範囲をその比に直してから設定する。
        """
        if rect is not None and self._image_size is not None:
            aspect = self._aspect_for((rect.width, rect.height))
            if aspect is not None and rect.width > 0 and rect.height > 0:
                rect = constrain_rect(rect, aspect, self._image_size)
        rect = rect or CropRect(0, 0, 0, 0)
        with self._block():
            self.crop_x_spin.setValue(rect.x)
            self.crop_y_spin.setValue(rect.y)
            self.crop_width_spin.setValue(rect.width)
            self.crop_height_spin.setValue(rect.height)
        self._on_crop_edited()

    def clear_crop(self) -> None:
        """トリミングを解除する。"""
        self.set_crop(None)

    def aspect_preset(self) -> AspectRatio:
        """比のプルダウンで選んでいる比（フレーム・円で固定中なら、固定を解いたときに戻る比）。"""
        data = self.aspect_combo.currentData()
        if isinstance(data, AspectRatio):
            return data
        return self.aspect_combo.itemData(self._aspect_index)

    def is_trim_view(self) -> bool:
        """切り抜き後の表示（「トリミング実行」が押された状態）かを返す。"""
        return self.trim_button.isChecked()

    def set_trim_view(self, enabled: bool) -> None:
        """切り抜き後の表示を切り替える（変化すれば trim_view_toggled を発行）。"""
        if enabled and not self.trim_button.isEnabled():
            return
        self.trim_button.setChecked(enabled)

    def orientation(self) -> Orientation:
        """今の向き（回転・反転）を返す。"""
        return self._orientation

    def image_size(self) -> tuple[int, int] | None:
        """回転・反転した後の画像の大きさ（トリミング範囲の座標系）を返す。"""
        return self._image_size

    def apply_orientation(self, op: OrientOp) -> None:
        """表示中の向きに対して回転・反転する。

        同じ写真の部分を指すよう、トリミング範囲も一緒に回す。90° 回すときは、手で変えた
        幅・高さと、比の「縦向き」も入れ替える。変更は 1 回だけ通知する。
        """
        if self._image_size is None:
            return
        old_size = self._image_size
        rect = self._clamped_range()
        self._orientation = self._orientation.apply(op)
        # 今の向きに対する操作なので、90° 回したときだけ幅と高さが入れ替わる
        self._image_size = (old_size[1], old_size[0]) if op.swaps_sides else old_size
        with self._block():
            self._set_crop_limits(self._image_size)
            if rect is not None:
                self._set_crop_spins(transform_rect(rect, old_size, op))
            if op.swaps_sides:
                if self._size_edited:
                    self._set_size_spins((self.height_spin.value(), self.width_spin.value()))
                    self._last_edited = "height" if self._last_edited == "width" else "width"
                if self.portrait_check.isEnabled():
                    self.portrait_check.setChecked(not self.portrait_check.isChecked())
        self._on_crop_edited()

    def _on_aspect_source_changed(self) -> None:
        """比・縦向き・フレーム・形が変わったら、比の表示を更新し、範囲をその比に直す。"""
        if self._updating:
            return
        self._update_aspect_controls()
        self._fit_range_to_aspect()
        self._on_crop_edited()

    def _update_aspect_controls(self) -> None:
        """フレーム・円を選んでいるときは比をそれに固定して操作できなくする。"""
        locked = self.is_aspect_locked_by_frame()
        follow_index = self.aspect_combo.count() - 1
        with self._block():
            if locked:
                if self.aspect_combo.currentIndex() != follow_index:
                    self._aspect_index = self.aspect_combo.currentIndex()
                self.aspect_combo.setCurrentIndex(follow_index)
            elif self.aspect_combo.currentIndex() == follow_index:
                self.aspect_combo.setCurrentIndex(self._aspect_index)
        enabled = self._image_size is not None and not locked
        self.aspect_combo.setEnabled(enabled)
        preset = self.aspect_combo.currentData()
        # 自由と 1:1 には向きがない
        has_orientation = isinstance(preset, AspectRatio) and preset not in (
            AspectRatio.FREE,
            AspectRatio.SQUARE,
        )
        self.portrait_check.setEnabled(enabled and has_orientation)

    def _aspect_for(self, size: tuple[int, int]) -> tuple[float, float] | None:
        """size の範囲に保たせる縦横比を返す（自由なら None）。"""
        frame = self.frame()
        if frame is not FrameType.NONE:
            return window_aspect(frame, size)
        if self.shape() is ShapeType.CIRCLE:
            return (1, 1)
        preset = self.aspect_combo.currentData()
        if not isinstance(preset, AspectRatio):
            return None
        return preset.ratio(portrait=self.portrait_check.isChecked())

    def _range_size(self) -> tuple[int, int]:
        """今の範囲（画像内に収めたもの）の大きさ。範囲がなければ画像の大きさ。"""
        rect = self._clamped_range()
        if rect is not None:
            return (rect.width, rect.height)
        return self._image_size or (MIN_SIZE, MIN_SIZE)

    def _clamped_range(self) -> CropRect | None:
        rect = self._crop_rect()
        if rect is None or self._image_size is None:
            return None
        return clamp_crop(rect, self._image_size)

    def _fit_range_to_aspect(self) -> None:
        """範囲があれば、その中央を今の比に合わせた範囲に直す。"""
        rect = self._clamped_range()
        if rect is None:
            return
        aspect = self._aspect_for((rect.width, rect.height))
        if aspect is None:
            return
        self._set_crop_spins(fit_aspect(rect, aspect))

    def _on_crop_spin_edited(self, name: str) -> None:
        """数値欄の変更。比を指定しているときは、もう一方の辺や位置を直して比を保つ。"""
        if self._updating:
            return
        rect = self._crop_rect()
        size = self._image_size
        previous = self._committed_crop
        aspect = self._aspect_for(
            (previous.width, previous.height) if previous else self._range_size()
        )
        width, height = self.crop_width_spin.value(), self.crop_height_spin.value()
        if aspect is not None and size is not None:
            x, y = self.crop_x_spin.value(), self.crop_y_spin.value()
            aspect_width, aspect_height = aspect
            if name == "width" and width > 0:
                height = max(MIN_SIZE, round(width * aspect_height / aspect_width))
            elif name == "height" and height > 0:
                width = max(MIN_SIZE, round(height * aspect_width / aspect_height))
            elif rect is not None:
                # 位置を変えたときは大きさを保ち、画像からはみ出す分だけ戻す
                x = min(x, max(size[0] - width, 0))
                y = min(y, max(size[1] - height, 0))
            if width > 0 and height > 0:
                fitted = constrain_rect(CropRect(x, y, width, height), aspect, size)
                if fitted is not None:
                    self._set_crop_spins(fitted)
        self._on_crop_edited()

    def _set_crop_spins(self, rect: CropRect) -> None:
        with self._block():
            self.crop_x_spin.setValue(rect.x)
            self.crop_y_spin.setValue(rect.y)
            self.crop_width_spin.setValue(rect.width)
            self.crop_height_spin.setValue(rect.height)

    def _on_trim_toggled(self, checked: bool) -> None:
        self.trim_button.setText(EDIT_RANGE_TEXT if checked else TRIM_TEXT)
        if not self._updating:
            self.trim_view_toggled.emit(checked)

    def _update_trim_button(self) -> None:
        """トリミング範囲・フレーム・形（矩形以外）のどれかがあるときだけ「トリミング実行」を
        押せるようにする。

        どれもなくなったら全体表示に戻す。
        """
        has_crop = self._image_size is not None and (
            self._effective_crop() is not None or self.shape() is not ShapeType.RECTANGLE
        )
        if not has_crop and self.trim_button.isChecked():
            self.trim_button.setChecked(False)
        self.trim_button.setEnabled(has_crop)

    def _crop_rect(self) -> CropRect | None:
        width, height = self.crop_width_spin.value(), self.crop_height_spin.value()
        if width <= 0 or height <= 0:
            return None
        return CropRect(self.crop_x_spin.value(), self.crop_y_spin.value(), width, height)

    def _effective_crop(self) -> CropRect | None:
        if self._image_size is None:
            return None
        return effective_crop(self._image_size, self._crop_rect(), self.frame(), self.shape())

    def _orient_buttons(self) -> tuple[QPushButton, ...]:
        """回転・反転のボタン（OrientOp と同じ順）。"""
        return (
            self.rotate_left_button,
            self.rotate_right_button,
            self.flip_horizontal_button,
            self.flip_vertical_button,
        )

    def _set_crop_limits(self, size: tuple[int, int]) -> None:
        """トリミングの数値欄の上限を画像の大きさに合わせる。"""
        width, height = size
        self.crop_x_spin.setMaximum(max(0, width - 1))
        self.crop_y_spin.setMaximum(max(0, height - 1))
        self.crop_width_spin.setMaximum(width)
        self.crop_height_spin.setMaximum(height)

    def _crop_spins(self) -> tuple[QSpinBox, ...]:
        return (self.crop_x_spin, self.crop_y_spin, self.crop_width_spin, self.crop_height_spin)
