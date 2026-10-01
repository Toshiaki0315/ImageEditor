"""メインウィンドウの表示まわり（加工前との比較・100% 表示・ヒストグラム）。"""

from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    Qt,
)
from PyQt6.QtGui import QKeyEvent

from image_editor.core.diorama import DioramaDirection, diorama_band
from image_editor.core.frames import frame_margins
from image_editor.core.pipeline import (
    EditSettings,
    effective_crop,
    output_size,
)
from image_editor.core.transform import fit_size
from image_editor.ui.drop_area import DioramaGuide
from image_editor.ui.worker import ZoomTask

# 押している間だけ加工前の画像を表示するキー（JIS 配列の ¥ キーも同じ位置にある）
COMPARE_KEYS = (Qt.Key.Key_Backslash, Qt.Key.Key_yen)
COMPARE_BADGE_TEXT = "加工前"
ZOOM_BADGE_TEXT = "100%"
ZOOM_RENDERING_TEXT = "更新中…"
PREF_SHOW_HISTOGRAM = "view/histogram"  # プレビューにヒストグラムを重ねるか


class ViewMixin:
    """メインウィンドウの表示まわり（加工前との比較・100% 表示・ヒストグラム）。

    MainWindow に混ぜて使う（属性は MainWindow の __init__ で作る）。
    """

    def is_histogram_shown(self) -> bool:
        """プレビューにヒストグラムを重ねて表示する設定かを返す。"""
        return self.histogram_action.isChecked()

    def _on_histogram_toggled(self, shown: bool) -> None:
        self._preferences.setValue(PREF_SHOW_HISTOGRAM, shown)
        self._show_histogram()

    def _show_histogram(self) -> None:
        """設定が表示で、画像があればヒストグラムを重ねる。"""
        show = self.is_histogram_shown() and self.loaded is not None
        self.drop_area.set_histogram(self._histogram if show else None)

    def _update_diorama_guide(self) -> None:
        """「ジオラマ」タブを開いている間、プレビューにピントの帯のガイドを重ねる。

        加工前の表示中は出さない。ぼかしが 0 でも、帯の位置を決めやすいよう出す。
        """
        guide = None
        if self.loaded is not None and self.settings_panel.is_diorama_tab() and not self._comparing:
            settings = self.settings_panel.settings()
            guide = DioramaGuide(
                area=self._photo_area(settings),
                horizontal=settings.diorama_direction is DioramaDirection.HORIZONTAL,
                band=diorama_band(settings.diorama()),
            )
        self.drop_area.set_diorama_guide(guide)

    def _photo_area(self, settings: EditSettings) -> tuple[float, float, float, float]:
        """表示している画像の中の、写真（ジオラマの位置の基準）の範囲を割合で返す。

        全体表示では実際に切り抜く範囲（なければ全体）。切り抜き表示と 100% 表示では、
        フレームの余白を除いた写真の部分。
        """
        assert self.loaded is not None
        size = settings.orientation.size(self.loaded.image.size)
        rect = effective_crop(size, settings.crop, settings.frame, settings.shape)
        if not self._zoomed and not self.settings_panel.is_trim_view():
            if rect is None:
                return (0.0, 0.0, 1.0, 1.0)
            width, height = size
            return (rect.x / width, rect.y / height, rect.width / width, rect.height / height)
        photo = (rect.width, rect.height) if rect is not None else size
        if self._zoomed:
            # 100% 表示は保存結果（リサイズ後）。切り抜き表示はリサイズを反映しない
            photo = fit_size(photo, settings.width, settings.height, settings.keep_aspect)
        left, top, right, bottom = frame_margins(settings.frame, photo)
        width, height = photo[0] + left + right, photo[1] + top + bottom
        return (left / width, top / height, photo[0] / width, photo[1] / height)

    def set_comparing(self, comparing: bool) -> None:
        """加工前の画像の表示を切り替える（押している間だけ True にする）。

        加工前は、向き（回転・反転）と表示範囲はそのままで、色の調整・テイスト・周辺減光・
        経年劣化・形・フレームを外したもの。表示中は左上に「加工前」と出す。
        """
        comparing = comparing and self.loaded is not None
        if comparing == self._comparing:
            return
        self._comparing = comparing
        self._update_badge()
        self._update_diorama_guide()
        self.update_preview()
        if self._zoomed:
            self._render_zoom()

    def show_actual_size(self, center: tuple[float, float] | None = None) -> None:
        """100% 表示にする（原寸で処理した保存結果を、画像 1px = 画面の 1 画素で見せる）。

        原寸の処理は裏で行い、終わるまでは前の表示のまま「更新中…」と出す。center は
        表示の中央にしたい点（保存結果の画像の座標）。省略時は画像の中央。
        """
        if self.loaded is None:
            return
        self._zoomed = True
        self._zoom_center = center
        # 100% 表示の間はドラッグで見る場所を動かすので、範囲の選択は止める
        self.drop_area.crop_overlay.set_active(False)
        self._render_zoom()
        self._update_diorama_guide()
        self._update_actions()

    def fit_to_window(self) -> None:
        """画面に合わせた表示に戻す。"""
        if not self._zoomed:
            return
        self._leave_zoom()
        if self.loaded is not None:
            self.drop_area.crop_overlay.set_active(not self.settings_panel.is_trim_view())
        self._update_diorama_guide()
        self._update_actions()

    def is_zoomed(self) -> bool:
        """100% 表示中かを返す。"""
        return self._zoomed

    def is_zoom_rendering(self) -> bool:
        """100% 表示のための原寸の処理中かを返す。"""
        return self._zoom_pending

    def _leave_zoom(self) -> None:
        self._zoomed = False
        self._zoom_generation += 1  # 処理中の結果は使わない
        self._zoom_pending = False
        self._zoom_timer.stop()
        self._zoom_center = None
        self.drop_area.set_zoom_image(None)
        self._update_badge()

    def _render_zoom(self) -> None:
        """今の設定（加工前の表示中なら加工前）で原寸の処理を裏で始める。"""
        self._zoom_timer.stop()
        if not self._zoomed or self.loaded is None:
            return
        settings = self.settings_panel.settings()
        shown = self._before_settings(settings) if self._comparing else settings
        self._zoom_generation += 1
        task = ZoomTask(self.loaded.image, shown, self._zoom_generation)
        task.setAutoDelete(False)  # 完了通知を受け取るまで Python 側で保持する
        task.signals.finished.connect(
            lambda image, generation, task=task: self._on_zoom_finished(task, image, generation)
        )
        task.signals.failed.connect(
            lambda message, generation, task=task: self._on_zoom_failed(task, message, generation)
        )
        self._zoom_tasks.add(task)
        self._zoom_pending = True
        self._update_badge()
        self._thread_pool.start(task)

    def _on_zoom_finished(self, task: ZoomTask, image: Image.Image, generation: int) -> None:
        self._zoom_tasks.discard(task)
        if generation != self._zoom_generation:
            return  # 古い依頼の結果（設定がその後変わった）
        self._zoom_pending = False
        if self._zoomed:
            self.drop_area.set_zoom_image(image, self._zoom_center)
            self._zoom_center = None
        self._update_badge()

    def _on_zoom_failed(self, task: ZoomTask, message: str, generation: int) -> None:
        self._zoom_tasks.discard(task)
        if generation != self._zoom_generation:
            return
        self._zoom_pending = False
        self.fit_to_window()
        self._show_error("100% で表示できません", message)

    def _on_preview_double_clicked(self, point: QPointF) -> None:
        """100% 表示中なら画面に合わせた表示に戻す。切り抜き表示中なら、その点を 100% で見る。

        通常の表示ではクリックで範囲を解除するので、ダブルクリックでは切り替えない。
        """
        if self._zoomed:
            self.fit_to_window()
            return
        if self.loaded is None or not self.settings_panel.is_trim_view():
            return
        rect = self.drop_area.image_rect()
        if rect.isEmpty() or not rect.contains(point):
            return
        width, height = output_size(self.loaded.image.size, self.settings_panel.settings())
        center = (
            (point.x() - rect.x()) / rect.width() * width,
            (point.y() - rect.y()) / rect.height() * height,
        )
        self.show_actual_size(center)

    def _update_badge(self) -> None:
        """左上の表示（「加工前」「100%」「更新中…」）をまとめて出す。"""
        parts = []
        if self._comparing:
            parts.append(COMPARE_BADGE_TEXT)
        if self._zoomed:
            parts.append(ZOOM_BADGE_TEXT)
            if self._zoom_pending:
                parts.append(ZOOM_RENDERING_TEXT)
        self.drop_area.set_badge(" ・ ".join(parts) if parts else None)

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
