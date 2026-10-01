from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSplitter,
)

from image_editor.app import create_window
from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType
from image_editor.core.io import SaveOptions, load_image
from image_editor.core.pipeline import EditSettings
from image_editor.core.shapes import ShapeType
from image_editor.core.transform import AspectRatio, CropRect
from image_editor.ui.crop_overlay import image_to_widget
from image_editor.ui.main_window import MainWindow, default_save_path, is_same_file
from image_editor.ui.settings_panel import ElidedLabel


def test_window_opens(qtbot):
    window = create_window()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert isinstance(window, MainWindow)
    assert window.isVisible()
    assert window.windowTitle() == "Image Editor"


def test_window_size(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert (window.width(), window.height()) == (1200, 800)
    assert (window.minimumWidth(), window.minimumHeight()) == (900, 600)


def test_layout_has_placeholders_and_status_bar(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    splitter = window.centralWidget()
    assert isinstance(splitter, QSplitter)
    assert splitter.widget(0) is window.drop_area
    # 設定パネルは縦にスクロールできる領域に入っている
    assert splitter.widget(1) is window.settings_scroll
    assert window.settings_scroll.widget() is window.settings_panel
    assert window.status_label.text() == "画像が読み込まれていません"


def test_file_menu_actions(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    menus = [a.menu() for a in window.menuBar().actions() if a.menu()]
    assert [m.title() for m in menus] == ["ファイル", "編集", "表示"]
    texts = [a.text() for a in menus[0].actions() if not a.isSeparator()]
    assert texts == ["開く…", "保存…", "まとめて処理…", "終了"]
    assert window.open_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Open)
    assert window.save_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Save)
    assert window.quit_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Quit)


def test_quit_action_closes_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    window.quit_action.trigger()

    assert not window.isVisible()


# --- 画像の読み込み -----------------------------------------------------------


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@pytest.fixture
def warnings(monkeypatch):
    """QMessageBox.warning を差し替え、表示された内容を記録する。"""
    shown: list[tuple[str, str]] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        shown.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    return shown


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".gif", ".tif", ".bmp"])
def test_load_file_shows_preview(window, tmp_path, warnings, suffix):
    path = tmp_path / f"photo{suffix}"
    Image.new("RGB", (300, 200), (255, 0, 0)).save(path)

    assert window.load_file(path)

    assert window.loaded is not None
    assert window.loaded.path == path
    assert window.drop_area.has_image()
    assert window.drop_area.display_pixmap() is not None
    assert window.status_label.text() == f"photo{suffix} ｜ 原寸 300×200 px ｜ 出力 300×200 px"
    assert warnings == []


def test_load_corrupt_file_shows_dialog(window, tmp_path, warnings):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")

    assert not window.load_file(path)

    assert len(warnings) == 1
    assert "broken.png" in warnings[0][1]
    assert window.loaded is None
    assert not window.drop_area.has_image()
    assert window.isVisible()


def test_failed_load_keeps_previous_image(window, tmp_path, warnings):
    good = tmp_path / "good.png"
    Image.new("RGB", (10, 10)).save(good)
    window.load_file(good)

    window.load_file(tmp_path / "missing.png")

    assert len(warnings) == 1
    assert window.loaded is not None and window.loaded.path == good
    assert window.status_label.text().startswith("good.png")


def test_unexpected_error_does_not_crash(window, tmp_path, warnings, monkeypatch):
    def boom(path):
        raise MemoryError("too big")

    monkeypatch.setattr("image_editor.ui.main_window.load_image", boom)

    assert not window.load_file(tmp_path / "a.png")
    assert len(warnings) == 1


def test_animated_gif_is_notified(window, tmp_path, warnings):
    path = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (8, 8), c) for c in [(255, 0, 0), (0, 255, 0)]]
    frames[0].save(path, save_all=True, append_images=frames[1:])

    window.load_file(path)

    assert "先頭フレームのみ" in window.status_label.text()


def test_drop_multiple_files_loads_first(window, tmp_path, warnings):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGB", (10, 10)).save(first)
    Image.new("RGB", (20, 20)).save(second)

    window.drop_area.files_dropped.emit([first, second])

    assert window.loaded is not None and window.loaded.path == first
    assert "2 件中、先頭の 1 枚のみ" in window.status_label.text()


def test_open_action_loads_selected_file(window, tmp_path, warnings, monkeypatch):
    path = tmp_path / "opened.jpg"
    Image.new("RGB", (40, 30)).save(path)
    calls = []

    def fake_dialog(parent, caption, directory, file_filter):
        calls.append(file_filter)
        return str(path), file_filter

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_dialog)

    window.open_action.trigger()

    assert window.loaded is not None and window.loaded.path == path
    assert "*.png" in calls[0] and "*.tiff" in calls[0]


def test_open_action_cancel_does_nothing(window, warnings, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))

    window.open_action.trigger()

    assert window.loaded is None
    assert warnings == []


# --- プレビュー・保存・リセット -------------------------------------------------


@pytest.fixture
def questions(monkeypatch):
    """QMessageBox.question を差し替える。answers に次の回答を積む（既定は破棄）。"""
    state = {"asked": 0, "answer": QMessageBox.StandardButton.Discard}

    def fake_question(*args, **kwargs):
        state["asked"] += 1
        return state["answer"]

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    return state


@pytest.fixture
def loaded_window(window, tmp_path, warnings):
    path = tmp_path / "photo.png"
    image = Image.new("RGB", (400, 300), (40, 120, 200))
    image.paste((220, 60, 30), (0, 0, 200, 300))
    image.save(path)
    window.load_file(path)
    return window


def save_and_wait(qtbot, window, path):
    """保存を開始し、ワーカースレッドでの完了を待つ。"""
    with qtbot.waitSignal(window.save_finished, timeout=10000):
        assert window.save_to(path)


def preview_pixel(window, x, y):
    return window.drop_area._source.pixelColor(x, y).getRgb()[:3]


def test_panel_enabled_after_load(loaded_window):
    panel = loaded_window.settings_panel
    assert panel.save_button.isEnabled()
    assert (panel.width_spin.value(), panel.height_spin.value()) == (400, 300)
    assert loaded_window.save_action.isEnabled()


@pytest.mark.parametrize("filter_type", [f for f in FilterType if f is not FilterType.NONE])
def test_preview_changes_with_filter(loaded_window, filter_type):
    before = preview_pixel(loaded_window, 50, 150)
    panel = loaded_window.settings_panel
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(filter_type))

    loaded_window.update_preview()

    assert preview_pixel(loaded_window, 50, 150) != before


def test_no_preview_button_or_menu(loaded_window):
    # プレビューは自動で更新するので、更新ボタンとメニューは置かない
    panel = loaded_window.settings_panel
    assert not hasattr(panel, "preview_button")
    assert not hasattr(loaded_window, "preview_action")
    texts = [a.text() for m in loaded_window.menuBar().findChildren(QMenu) for a in m.actions()]
    assert "プレビュー更新" not in texts


def test_filter_change_updates_preview_automatically(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.MONOTONE))

    qtbot.waitUntil(lambda: len(set(preview_pixel(loaded_window, 50, 150))) == 1, timeout=2000)


@pytest.mark.parametrize("filter_type", list(FilterType))
@pytest.mark.parametrize("frame", list(FrameType))
def test_preview_keeps_whole_frame(loaded_window, filter_type, frame):
    # トリミング・リサイズ・フレームはプレビューに反映せず、元の画角のまま表示する
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 100, 50))
    panel.width_spin.setValue(20)
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(filter_type))
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(frame))

    loaded_window.update_preview()

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (400, 300)
    # マスクは範囲を示す（フレームを選ぶと範囲は写真部分の比に直る）
    assert loaded_window.drop_area.crop_overlay.crop() == panel.settings().crop
    if frame is FrameType.NONE:
        assert panel.settings().crop == CropRect(0, 0, 100, 50)


def test_status_shows_output_size(loaded_window):
    panel = loaded_window.settings_panel
    panel.width_spin.setValue(200)
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))

    # 正方形 300x300 に切り抜き → 200x200 → ポラロイドの余白 (11, 15, 11, 56)
    assert loaded_window.status_label.text() == ("photo.png ｜ 原寸 400×300 px ｜ 出力 222×271 px")


def test_default_save_path():
    assert default_save_path(Path("/a/b/photo.JPG")) == Path("/a/b/photo_edited.JPG")


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".gif", ".tif", ".bmp"])
def test_saved_file_has_size_and_filter(loaded_window, qtbot, tmp_path, suffix):
    panel = loaded_window.settings_panel
    panel.width_spin.setValue(200)
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.MONOTONE))
    out = tmp_path / f"out{suffix}"

    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image.convert("RGB")
    assert saved.size == (200, 150)
    r, g, b = saved.getpixel((50, 75))
    assert abs(r - g) <= 3 and abs(g - b) <= 3  # モノトーン
    assert "保存しました: " + out.name in loaded_window.status_label.text()
    assert panel.save_button.isEnabled()  # 処理後にボタンが戻る


def test_save_polaroid_frame_output_size(loaded_window, qtbot, tmp_path):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 200, 200))
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))
    out = tmp_path / "out.png"

    save_and_wait(qtbot, loaded_window, out)

    assert load_image(out).image.size == (200 + 11 * 2, 200 + 15 + 56)


@pytest.mark.parametrize("filter_type", [FilterType.POLAROID, FilterType.SEPIA])
def test_save_frame_with_any_filter(loaded_window, qtbot, tmp_path, filter_type):
    panel = loaded_window.settings_panel
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(filter_type))
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.INSTAX_MINI))
    out = tmp_path / "out.png"

    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image.convert("RGB")
    # 横長の写真は横向きのチェキ（写真部分 62:46 → 400x297、広い余白は右）
    assert saved.size == loaded_window_output(loaded_window)
    assert saved.width > saved.height
    assert saved.getpixel((saved.width - 5, saved.height // 2)) == (255, 255, 255)


def test_save_polaroid_filter_without_frame(loaded_window, qtbot, tmp_path):
    panel = loaded_window.settings_panel
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.POLAROID))
    out = tmp_path / "out.png"

    save_and_wait(qtbot, loaded_window, out)

    # 「ポラロイド風」は色だけで、白枠は付かない
    assert load_image(out).image.size == (400, 300)


def loaded_window_output(window: MainWindow) -> tuple[int, int]:
    from image_editor.core.pipeline import output_size

    assert window.loaded is not None
    return output_size(window.loaded.image.size, window.settings_panel.settings())


def test_save_dialog_uses_default_name(loaded_window, qtbot, tmp_path, monkeypatch):
    calls = []
    out = tmp_path / "chosen"  # 拡張子なし → 選んだ形式の拡張子を付ける

    def fake_dialog(parent, caption, directory, filters, selected):
        calls.append((directory, selected))
        return str(out), "JPEG (*.jpg *.jpeg)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_dialog)

    with qtbot.waitSignal(loaded_window.save_finished, timeout=10000):
        loaded_window.save_action.trigger()

    assert calls == [(str(tmp_path / "photo_edited.png"), "PNG (*.png)")]
    assert (tmp_path / "chosen.jpg").exists()


def test_save_dialog_rejects_unsupported_extension(loaded_window, tmp_path, warnings, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "x.webp"), ""))

    loaded_window.settings_panel.save_button.click()

    assert len(warnings) == 1
    assert not (tmp_path / "x.webp").exists()


def test_save_error_is_reported(loaded_window, qtbot, tmp_path, warnings):
    with qtbot.waitSignal(loaded_window.save_failed, timeout=10000):
        assert loaded_window.save_to(tmp_path / "no_such_dir" / "x.png")

    assert len(warnings) == 1
    assert not loaded_window.is_saving()
    assert loaded_window.settings_panel.save_button.isEnabled()


# --- 未保存の変更 ---------------------------------------------------------------


def test_no_unsaved_changes_right_after_load(loaded_window, questions):
    assert not loaded_window.has_unsaved_changes()

    loaded_window.reset()

    assert questions["asked"] == 0
    assert loaded_window.loaded is None
    assert not loaded_window.drop_area.has_image()
    assert loaded_window.status_label.text() == "画像が読み込まれていません"
    assert not loaded_window.settings_panel.save_button.isEnabled()


def test_reset_asks_when_unsaved(loaded_window, questions):
    loaded_window.settings_panel.width_spin.setValue(100)
    questions["answer"] = QMessageBox.StandardButton.Cancel

    loaded_window.settings_panel.reset_button.click()

    assert questions["asked"] == 1
    assert loaded_window.loaded is not None  # キャンセルしたので残る

    questions["answer"] = QMessageBox.StandardButton.Discard
    loaded_window.reset()

    assert loaded_window.loaded is None


def test_no_question_after_save(loaded_window, qtbot, tmp_path, questions):
    loaded_window.settings_panel.width_spin.setValue(100)
    save_and_wait(qtbot, loaded_window, tmp_path / "out.png")

    loaded_window.reset()

    assert questions["asked"] == 0
    assert loaded_window.loaded is None


def test_change_after_save_is_unsaved(loaded_window, qtbot, tmp_path, questions):
    panel = loaded_window.settings_panel
    panel.width_spin.setValue(100)
    save_and_wait(qtbot, loaded_window, tmp_path / "out.png")
    assert not loaded_window.has_unsaved_changes()
    panel.width_spin.setValue(120)

    assert loaded_window.has_unsaved_changes()


def test_loading_another_image_asks_when_unsaved(loaded_window, tmp_path, questions):
    other = tmp_path / "other.png"
    Image.new("RGB", (10, 10)).save(other)
    loaded_window.settings_panel.width_spin.setValue(100)
    questions["answer"] = QMessageBox.StandardButton.Cancel

    assert not loaded_window.load_file(other)

    assert questions["asked"] == 1
    assert loaded_window.loaded.path.name == "photo.png"


# --- プレビュー上のトリミング -------------------------------------------------


def overlay_point(window, x, y):
    """原画像座標 (x, y) に対応するオーバーレイ上の座標。"""
    rect = window.drop_area.image_rect()
    point = image_to_widget(x, y, rect, window.loaded.image.size)
    return QPoint(round(point.x()), round(point.y()))


def drag_on_overlay(qtbot, window, start, end):
    overlay = window.drop_area.crop_overlay
    qtbot.mousePress(overlay, Qt.MouseButton.LeftButton, pos=overlay_point(window, *start))
    qtbot.mouseMove(overlay, overlay_point(window, *end))
    qtbot.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=overlay_point(window, *end))


def test_overlay_is_active_right_after_load(loaded_window):
    assert loaded_window.drop_area.crop_overlay.is_active()


def test_overlay_is_inactive_without_image(window, questions):
    assert not window.drop_area.crop_overlay.is_active()


def test_overlay_is_inactive_after_reset(loaded_window, questions):
    loaded_window.reset()
    assert not loaded_window.drop_area.crop_overlay.is_active()


def test_drop_still_works_with_overlay(loaded_window, tmp_path, qtbot):
    # オーバーレイはドロップを受け付けず、下の DropArea に届く
    overlay = loaded_window.drop_area.crop_overlay
    assert not overlay.acceptDrops()
    assert loaded_window.drop_area.acceptDrops()

    other = tmp_path / "dropped.png"
    Image.new("RGB", (20, 10)).save(other)
    loaded_window.drop_area.files_dropped.emit([other])

    assert loaded_window.loaded.path == other
    assert overlay.is_active()


def test_drag_updates_spin_boxes(loaded_window, qtbot):
    panel = loaded_window.settings_panel

    drag_on_overlay(qtbot, loaded_window, (50, 40), (250, 190))

    rect = panel.settings().crop
    assert rect is not None
    for actual, expected in zip(
        (rect.x, rect.y, rect.width, rect.height), (50, 40, 200, 150), strict=True
    ):
        assert abs(actual - expected) <= 1
    assert (panel.width_spin.value(), panel.height_spin.value()) == (rect.width, rect.height)


def test_spin_boxes_update_overlay(loaded_window):
    panel = loaded_window.settings_panel

    panel.set_crop(CropRect(10, 20, 30, 40))

    assert loaded_window.drop_area.crop_overlay.crop() == CropRect(10, 20, 30, 40)


def test_clear_button_clears_overlay(loaded_window):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(10, 20, 30, 40))

    panel.clear_crop_button.click()

    assert loaded_window.drop_area.crop_overlay.crop() is None


def test_dragged_range_matches_saved_image(loaded_window, qtbot, tmp_path):
    # 元画像は左半分 (x < 200) が赤、右半分が青。境界をまたいで 100〜300 を選ぶ
    drag_on_overlay(qtbot, loaded_window, (100, 50), (300, 250))
    out = tmp_path / "cropped.png"
    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image
    assert abs(saved.width - 200) <= 1 and abs(saved.height - 200) <= 1
    # 切り抜き範囲の左半分が赤、右半分が青
    assert saved.getpixel((10, 100)) == (220, 60, 30)
    assert saved.getpixel((saved.width - 10, 100)) == (40, 120, 200)


def test_drag_outside_is_clamped_in_panel(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    overlay = loaded_window.drop_area.crop_overlay

    qtbot.mousePress(overlay, Qt.MouseButton.LeftButton, pos=overlay_point(loaded_window, 300, 200))
    qtbot.mouseMove(overlay, QPoint(overlay.width() - 1, overlay.height() - 1))
    qtbot.mouseRelease(
        overlay, Qt.MouseButton.LeftButton, pos=QPoint(overlay.width() - 1, overlay.height() - 1)
    )

    assert panel.settings().crop == CropRect(300, 200, 100, 100)


def test_loading_new_image_clears_selection(loaded_window, tmp_path, questions):
    other = tmp_path / "other.png"
    Image.new("RGB", (50, 50)).save(other)
    loaded_window.settings_panel.set_crop(CropRect(0, 0, 10, 10))

    loaded_window.load_file(other)

    assert loaded_window.drop_area.crop_overlay.crop() is None
    assert loaded_window.drop_area.crop_overlay.is_active()


# --- 縮小プレビューとワーカースレッド -------------------------------------------


@pytest.fixture
def wide_window(window, tmp_path, warnings):
    """長辺 1600px を超える画像 (3200x800) を読み込んだウィンドウ。"""
    path = tmp_path / "wide.png"
    image = Image.new("RGB", (3200, 800), (40, 120, 200))
    image.paste((220, 60, 30), (0, 0, 1600, 800))
    image.save(path)
    window.load_file(path)
    return window


def test_preview_uses_downscaled_image(wide_window):
    source = wide_window.drop_area._source
    assert (source.width(), source.height()) == (1600, 400)
    # ステータスバーは原寸
    assert "原寸 3200×800 px" in wide_window.status_label.text()


def test_crop_is_kept_in_original_coordinates(wide_window):
    panel = wide_window.settings_panel
    panel.set_crop(CropRect(1200, 0, 800, 800))

    wide_window.update_preview()

    # プレビューは縮小版の全体、選択範囲と出力サイズは原画像の座標系
    assert wide_window.drop_area._source.width() == 1600
    assert wide_window.drop_area.crop_overlay.crop() == CropRect(1200, 0, 800, 800)
    assert "出力 800×800 px" in wide_window.status_label.text()


def test_drag_on_downscaled_preview(wide_window, qtbot):
    panel = wide_window.settings_panel

    # 縮小表示でも、ドラッグ範囲は原画像の座標系で得られる
    drag_on_overlay(qtbot, wide_window, (400, 100), (2000, 700))

    assert wide_window.drop_area._source.width() == 1600
    rect = panel.settings().crop
    assert rect is not None
    assert abs(rect.x - 400) <= 2 and abs(rect.width - 1600) <= 2


def test_auto_preview_after_debounce(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    before = preview_pixel(loaded_window, 50, 150)

    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.MONOTONE))

    # すぐには更新されず、300ms 後に自動で更新される
    assert preview_pixel(loaded_window, 50, 150) == before
    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 50, 150) != before, timeout=2000)
    r, g, b = preview_pixel(loaded_window, 50, 150)
    assert r == g == b


def test_auto_preview_is_debounced(loaded_window, qtbot, monkeypatch):
    calls = []
    original = loaded_window.update_preview
    monkeypatch.setattr(loaded_window, "update_preview", lambda: (calls.append(1), original()))

    panel = loaded_window.settings_panel
    for filter_type in (FilterType.SEPIA, FilterType.MONOTONE, FilterType.HIGH_TONE):
        panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(filter_type))

    qtbot.wait(600)
    assert len(calls) == 1


def test_no_redraw_when_only_crop_or_size_changes(loaded_window, qtbot, monkeypatch):
    # プレビューに反映されるのはフィルターだけなので、範囲やサイズの変更では描き直さない
    calls = []
    original = loaded_window.update_preview
    monkeypatch.setattr(loaded_window, "update_preview", lambda: (calls.append(1), original()))
    panel = loaded_window.settings_panel

    panel.set_crop(CropRect(0, 0, 100, 100))
    panel.width_spin.setValue(50)
    qtbot.wait(500)

    assert calls == []


def test_save_runs_in_worker_thread(loaded_window, qtbot, tmp_path, monkeypatch):
    import threading

    import image_editor.ui.worker as worker

    started = threading.Event()
    release = threading.Event()
    threads = []
    real_save = worker.save_image

    def slow_save(image, path, *args, **kwargs):
        threads.append(threading.current_thread())
        started.set()
        release.wait(5)
        real_save(image, path, *args, **kwargs)

    monkeypatch.setattr(worker, "save_image", slow_save)
    panel = loaded_window.settings_panel
    out = tmp_path / "slow.png"

    assert loaded_window.save_to(out)  # すぐ戻る
    assert started.wait(5)

    # 保存中: UI は動き続け、ボタン類は無効
    assert loaded_window.is_saving()
    assert not panel.save_button.isEnabled()
    assert not panel.reset_button.isEnabled()
    assert not loaded_window.open_action.isEnabled()
    assert not loaded_window.drop_area.acceptDrops()
    assert "保存中" in loaded_window.status_label.text()
    ticks = []
    QTimer.singleShot(10, lambda: ticks.append(1))
    qtbot.waitUntil(lambda: ticks == [1], timeout=1000)  # イベントループが回っている
    assert not loaded_window.save_to(tmp_path / "second.png")  # 二重保存しない

    with qtbot.waitSignal(loaded_window.save_finished, timeout=5000):
        release.set()

    assert threads[0] is not threading.main_thread()
    assert out.exists()
    assert panel.save_button.isEnabled()
    assert loaded_window.open_action.isEnabled()
    assert loaded_window.drop_area.acceptDrops()


def test_load_is_blocked_while_saving(loaded_window, qtbot, tmp_path, monkeypatch):
    import threading

    import image_editor.ui.worker as worker

    release = threading.Event()
    real_save = worker.save_image
    monkeypatch.setattr(worker, "save_image", lambda *a, **k: (release.wait(5), real_save(*a, **k)))
    other = tmp_path / "other.png"
    Image.new("RGB", (10, 10)).save(other)

    loaded_window.save_to(tmp_path / "out.png")
    assert not loaded_window.load_file(other)

    with qtbot.waitSignal(loaded_window.save_finished, timeout=5000):
        release.set()
    assert loaded_window.loaded.path.name == "photo.png"


def test_close_waits_for_save(loaded_window, tmp_path):
    out = tmp_path / "on_close.png"

    loaded_window.save_to(out)
    loaded_window.close()

    assert out.exists()


def test_window_title_shows_file_name(loaded_window, questions):
    assert loaded_window.windowTitle() == "photo.png — Image Editor"
    assert loaded_window.windowFilePath().endswith("photo.png")

    loaded_window.reset()

    assert loaded_window.windowTitle() == "Image Editor"


# --- 周辺減光・トリミング実行 -----------------------------------------------------


def test_vignette_slider_updates_preview(loaded_window, qtbot):
    corner_before = preview_pixel(loaded_window, 0, 0)
    center_before = preview_pixel(loaded_window, 200, 150)

    loaded_window.settings_panel.vignette_slider.setValue(100)

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 0, 0) != corner_before, timeout=2000)
    assert sum(preview_pixel(loaded_window, 0, 0)) < sum(corner_before)
    assert preview_pixel(loaded_window, 200, 150) == center_before


def test_vignette_follows_crop_in_preview(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.vignette_slider.setValue(100)
    loaded_window.update_preview()
    whole_corner = preview_pixel(loaded_window, 0, 0)

    # 範囲を変えると（周辺減光があるので）描き直され、範囲の中心基準で暗くなる
    panel.set_crop(CropRect(200, 150, 200, 150))
    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 0, 0) != whole_corner, timeout=2000)

    assert preview_pixel(loaded_window, 0, 0) == (220, 60, 30)  # 範囲外は暗くしない
    assert sum(preview_pixel(loaded_window, 200, 150)) < sum((40, 120, 200))  # 範囲の左上


def test_trim_view_shows_cropped_preview(loaded_window):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(100, 50, 200, 100))
    overlay = loaded_window.drop_area.crop_overlay

    panel.trim_button.click()

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (200, 100)
    assert not overlay.is_active()  # 切り抜き後の表示ではドラッグで選ばない
    # 左半分は赤（元画像の x < 200）、右半分は青
    assert preview_pixel(loaded_window, 10, 50) == (220, 60, 30)
    assert preview_pixel(loaded_window, 190, 50) == (40, 120, 200)

    panel.trim_button.click()  # 範囲を編集

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (400, 300)
    assert overlay.is_active()
    assert overlay.crop() == CropRect(100, 50, 200, 100)


def test_trim_view_reflects_filter_and_vignette(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(100, 50, 200, 100))
    panel.trim_button.click()

    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.MONOTONE))
    panel.vignette_slider.setValue(100)
    qtbot.waitUntil(lambda: len(set(preview_pixel(loaded_window, 100, 50))) == 1, timeout=2000)

    assert loaded_window.drop_area._source.width() == 200
    center = preview_pixel(loaded_window, 100, 50)
    corner = preview_pixel(loaded_window, 0, 0)
    assert corner[0] < center[0]


def test_trim_view_follows_crop_edits(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 200, 100))
    panel.trim_button.click()

    panel.crop_width_spin.setValue(100)

    qtbot.waitUntil(lambda: loaded_window.drop_area._source.width() == 100, timeout=2000)


def test_clear_crop_returns_to_whole_view(loaded_window):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 200, 100))
    panel.trim_button.click()

    panel.clear_crop_button.click()

    assert loaded_window.drop_area._source.width() == 400
    assert loaded_window.drop_area.crop_overlay.is_active()


def test_trim_view_shows_frame(loaded_window, qtbot):
    # フレームだけでも「トリミング実行」で完成形（比率の切り抜き + フレーム）を確認できる
    panel = loaded_window.settings_panel
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))

    assert panel.trim_button.isEnabled()
    panel.trim_button.click()

    source = loaded_window.drop_area._source
    # 400x300 → 正方形 300x300 → ポラロイドの余白 (17, 23, 17, 84)
    assert (source.width(), source.height()) == (334, 407)
    assert preview_pixel(loaded_window, 0, 0) == (255, 255, 255)

    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.NONE))

    # 範囲もフレームもなくなったら全体表示に戻る
    assert not panel.is_trim_view()
    assert loaded_window.drop_area._source.width() == 400


def test_trim_view_does_not_affect_save(loaded_window, qtbot, tmp_path):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(100, 50, 200, 100))
    panel.width_spin.setValue(100)
    panel.trim_button.click()
    out = tmp_path / "trimmed.png"

    save_and_wait(qtbot, loaded_window, out)

    assert load_image(out).image.size == (100, 50)


def test_saved_image_has_vignette(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.vignette_slider.setValue(100)
    out = tmp_path / "vignette.png"

    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image
    assert saved.getpixel((200, 150)) == (40, 120, 200)
    assert sum(saved.getpixel((0, 0))) < sum((220, 60, 30)) * 0.4


def test_reset_leaves_trim_view(loaded_window, questions):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 200, 100))
    panel.trim_button.click()

    loaded_window.reset()

    assert not panel.is_trim_view()
    assert not loaded_window.drop_area.crop_overlay.is_active()


# --- 経年劣化 -----------------------------------------------------------------


def test_aging_slider_updates_preview(loaded_window, qtbot):
    before = preview_pixel(loaded_window, 300, 150)  # 青 (40, 120, 200)

    loaded_window.settings_panel.aging_slider.setValue(100)

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 300, 150) != before, timeout=2000)
    r, _, b = preview_pixel(loaded_window, 300, 150)
    assert b - r < before[2] - before[0]  # 青が抜けて黄ばむ


def test_saved_image_has_aging(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.aging_slider.setValue(100)
    out = tmp_path / "aged.png"

    save_and_wait(qtbot, loaded_window, out)

    r, _, b = load_image(out).image.getpixel((300, 150))
    assert b - r < 200 - 40


# --- 色温度 -------------------------------------------------------------------


def test_temperature_slider_updates_preview(loaded_window, qtbot):
    before = preview_pixel(loaded_window, 300, 150)  # 青 (40, 120, 200)

    loaded_window.settings_panel.temperature_slider.setValue(25)  # 2500K

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 300, 150) != before, timeout=2000)
    r, _, b = preview_pixel(loaded_window, 300, 150)
    assert r > before[0] and b < before[2]


def test_saved_image_has_temperature(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.temperature_slider.setValue(100)  # 10000K
    out = tmp_path / "cool.png"

    save_and_wait(qtbot, loaded_window, out)

    r, _, b = load_image(out).image.getpixel((100, 150))  # 赤 (220, 60, 30)
    assert r < 220 and b > 30


# --- 彩度 ---------------------------------------------------------------------


def test_saturation_slider_updates_preview(loaded_window, qtbot):
    before = preview_pixel(loaded_window, 300, 150)  # 青 (40, 120, 200)

    loaded_window.settings_panel.saturation_slider.setValue(-100)

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 300, 150) != before, timeout=2000)
    r, g, b = preview_pixel(loaded_window, 300, 150)
    assert max(r, g, b) - min(r, g, b) <= 1


def test_saved_image_has_saturation(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.saturation_slider.setValue(-100)
    out = tmp_path / "gray.png"

    save_and_wait(qtbot, loaded_window, out)

    r, g, b = load_image(out).image.getpixel((100, 150))
    assert max(r, g, b) - min(r, g, b) <= 1


# --- 明るさ・スライダーの長さ ---------------------------------------------------


def test_brightness_slider_updates_preview(loaded_window, qtbot):
    before = preview_pixel(loaded_window, 300, 150)  # 青 (40, 120, 200)

    loaded_window.settings_panel.brightness_slider.setValue(60)

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 300, 150) != before, timeout=2000)
    assert sum(preview_pixel(loaded_window, 300, 150)) > sum(before)


def test_saved_image_has_brightness(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.brightness_slider.setValue(-60)
    out = tmp_path / "dark.png"

    save_and_wait(qtbot, loaded_window, out)

    assert sum(load_image(out).image.getpixel((300, 150))) < 40 + 120 + 200


@pytest.mark.parametrize("size", [(1200, 800), (900, 600)])
def test_sliders_fit_in_window(window, qtbot, size):
    # 初期サイズ・最小サイズのどちらでも、スライダーが 225px 以上で表示され、プレビューも残る
    window.resize(*size)
    qtbot.wait(50)

    assert window.settings_panel.brightness_slider.width() >= 225
    assert window.drop_area.width() >= 400


# --- コントラスト -------------------------------------------------------------


def test_contrast_slider_updates_preview(loaded_window, qtbot):
    before = preview_pixel(loaded_window, 300, 150)  # 青 (40, 120, 200)

    loaded_window.settings_panel.contrast_slider.setValue(100)

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 300, 150) != before, timeout=2000)
    r, _, b = preview_pixel(loaded_window, 300, 150)
    assert b - r > before[2] - before[0]  # 明暗の差が広がる


def test_saved_image_has_contrast(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.contrast_slider.setValue(-100)
    out = tmp_path / "flat.png"

    save_and_wait(qtbot, loaded_window, out)

    r, _, b = load_image(out).image.getpixel((300, 150))
    assert b - r < 200 - 40


@pytest.mark.parametrize("size", [(1200, 800), (900, 600)])
def test_panel_labels_are_not_cut_off(window, qtbot, size):
    # 「コントラスト」「周辺減光」などのラベルが欠けずに表示される
    window.resize(*size)
    qtbot.wait(50)
    panel = window.settings_panel

    # 失敗したときに、どの部品が幅を広げているか分かるよう各行の最小幅を出す
    layout = panel.layout()
    margins = layout.contentsMargins()
    widths = [
        (type(item.widget() or item.layout()).__name__, item.minimumSize().width())
        for item in (layout.itemAt(i) for i in range(layout.count()))
    ]
    detail = f"margins=({margins.left()}, {margins.right()}) items={widths}"
    assert panel.width() >= panel.minimumSizeHint().width(), detail
    for label in panel.findChildren(QLabel):
        if not (label.text() and label.isVisible()):
            continue
        if isinstance(label, ElidedLabel):
            # 「保存の設定」の要約は、幅が足りなければ「…」で省略する（空にはならない）
            assert label.width() > 0, label.text()
            continue
        assert label.width() >= label.sizeHint().width(), label.text()


# --- 露出・設定パネルのスクロール -------------------------------------------------


def test_exposure_slider_updates_preview(loaded_window, qtbot):
    before = preview_pixel(loaded_window, 300, 150)  # 青 (40, 120, 200)

    loaded_window.settings_panel.exposure_slider.setValue(10)  # +1.0 EV

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 300, 150) != before, timeout=2000)
    assert all(a >= b for a, b in zip(preview_pixel(loaded_window, 300, 150), before, strict=True))


def test_saved_image_has_exposure(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.exposure_slider.setValue(-20)  # -2.0 EV
    out = tmp_path / "under.png"

    save_and_wait(qtbot, loaded_window, out)

    assert sum(load_image(out).image.getpixel((300, 150))) < (40 + 120 + 200) * 0.6


def test_settings_panel_scrolls_in_small_window(window, qtbot):
    window.resize(900, 600)
    qtbot.wait(50)
    scroll = window.settings_scroll
    panel = window.settings_panel

    # 縦に収まらないときはスクロールでき、パネルは本来の高さで表示される（詰まらない）
    assert scroll.verticalScrollBar().maximum() > 0
    assert panel.height() >= panel.minimumSizeHint().height()
    # 一番下の「保存」ボタンまでスクロールで届く
    scroll.ensureWidgetVisible(panel.save_button)
    qtbot.wait(20)
    top_left = panel.save_button.mapTo(scroll.viewport(), panel.save_button.rect().topLeft())
    assert 0 <= top_left.y() <= scroll.viewport().height() - panel.save_button.height()


def test_settings_panel_does_not_scroll_in_large_window(window, qtbot):
    window.resize(1200, 900)
    qtbot.wait(50)
    assert window.settings_scroll.verticalScrollBar().maximum() == 0


# --- 元の画像とは違うファイル名で保存する -----------------------------------------


def test_default_save_path_avoids_existing_files(tmp_path):
    original = tmp_path / "photo.jpg"
    assert default_save_path(original) == tmp_path / "photo_edited.jpg"

    (tmp_path / "photo_edited.jpg").write_bytes(b"x")
    assert default_save_path(original) == tmp_path / "photo_edited_2.jpg"

    (tmp_path / "photo_edited_2.jpg").write_bytes(b"x")
    assert default_save_path(original) == tmp_path / "photo_edited_3.jpg"


def test_is_same_file(tmp_path):
    original = tmp_path / "photo.png"
    original.write_bytes(b"x")

    assert is_same_file(original, tmp_path / "photo.png")
    assert is_same_file(original, tmp_path / "sub" / ".." / "photo.png")
    assert is_same_file(original, tmp_path / "PHOTO.PNG")  # 大文字・小文字の違い
    assert not is_same_file(original, tmp_path / "photo.jpg")  # 拡張子が違えば別
    assert not is_same_file(original, tmp_path / "photo_edited.png")


def test_save_dialog_rejects_original_file_and_reopens(
    loaded_window, qtbot, tmp_path, warnings, monkeypatch
):
    original = loaded_window.loaded.path
    before = original.read_bytes()
    answers = iter([str(original), str(original.with_name("PHOTO.PNG")), ""])
    calls = []

    def fake_dialog(parent, caption, directory, filters, selected):
        calls.append(directory)
        return next(answers), selected

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_dialog)

    loaded_window.settings_panel.save_button.click()

    # 元のファイル、大文字・小文字違いのファイルはどちらも断られ、そのたびにダイアログが開き直される
    assert len(calls) == 3
    assert [title for title, _ in warnings] == ["保存できません", "保存できません"]
    assert "元の画像と同じファイル" in warnings[0][1]
    assert not loaded_window.is_saving()
    assert original.read_bytes() == before


def test_save_dialog_accepts_other_name_after_rejection(
    loaded_window, qtbot, tmp_path, warnings, monkeypatch
):
    original = loaded_window.loaded.path
    other = tmp_path / "edited.png"
    answers = iter([str(original), str(other)])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (next(answers), args[-1]))

    with qtbot.waitSignal(loaded_window.save_finished, timeout=10000):
        loaded_window.save_action.trigger()

    assert other.exists()
    assert len(warnings) == 1


def test_save_with_other_extension_is_allowed(loaded_window, qtbot, tmp_path, warnings):
    other = loaded_window.loaded.path.with_suffix(".jpg")  # photo.png → photo.jpg
    save_and_wait(qtbot, loaded_window, other)
    assert other.exists()
    assert warnings == []


def test_save_to_refuses_original_file(loaded_window, warnings):
    original = loaded_window.loaded.path
    before = original.read_bytes()
    loaded_window.settings_panel.width_spin.setValue(100)

    assert not loaded_window.save_to(original)

    assert not loaded_window.is_saving()
    assert original.read_bytes() == before
    assert len(warnings) == 1


# --- 形 -----------------------------------------------------------------------


def select_shape(window: MainWindow, shape: ShapeType) -> None:
    combo = window.settings_panel.shape_combo
    combo.setCurrentIndex(combo.findData(shape))


def test_trim_view_shows_circle(loaded_window):
    panel = loaded_window.settings_panel
    select_shape(loaded_window, ShapeType.CIRCLE)

    panel.trim_button.click()

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (300, 300)
    assert source.hasAlphaChannel()
    assert source.pixelColor(0, 0).alpha() == 0  # 円の外は透明（市松模様で表示）
    assert source.pixelColor(150, 150).alpha() == 255


def test_whole_view_does_not_show_shape(loaded_window):
    select_shape(loaded_window, ShapeType.ROUNDED)
    loaded_window.update_preview()

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (400, 300)
    assert source.pixelColor(0, 0).alpha() == 255


def test_corner_radius_updates_trim_view(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    select_shape(loaded_window, ShapeType.ROUNDED)
    panel.corner_slider.setValue(0)
    panel.trim_button.click()
    assert loaded_window.drop_area._source.pixelColor(0, 0).alpha() == 255

    panel.corner_slider.setValue(30)

    qtbot.waitUntil(
        lambda: loaded_window.drop_area._source.pixelColor(0, 0).alpha() == 0, timeout=2000
    )


def test_save_circle_png_is_transparent(loaded_window, qtbot, tmp_path):
    select_shape(loaded_window, ShapeType.CIRCLE)
    out = tmp_path / "circle.png"

    save_and_wait(qtbot, loaded_window, out)

    saved = Image.open(out)
    assert saved.size == (300, 300)
    assert saved.mode == "RGBA"
    assert saved.getpixel((0, 0))[3] == 0
    assert saved.getpixel((150, 150))[3] == 255


def test_save_circle_jpeg_is_white_outside(loaded_window, qtbot, tmp_path):
    select_shape(loaded_window, ShapeType.CIRCLE)
    out = tmp_path / "circle.jpg"

    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image
    assert saved.mode == "RGB"
    assert all(v > 245 for v in saved.getpixel((2, 2)))


def test_save_circle_with_frame(loaded_window, qtbot, tmp_path):
    panel = loaded_window.settings_panel
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))
    select_shape(loaded_window, ShapeType.CIRCLE)
    out = tmp_path / "framed.png"

    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image
    assert saved.mode == "RGB"  # 形の外はフレームの白で埋まり、透明にならない
    assert saved.size == loaded_window_output(loaded_window)
    # 写真部分 (17, 23) から 300x300。その左上の角はフレームの白
    assert saved.getpixel((19, 25)) == (255, 255, 255)
    assert saved.getpixel((17 + 150, 23 + 150)) != (255, 255, 255)


# --- トリミングの縦横比 ---------------------------------------------------------


def test_aspect_is_passed_to_overlay(loaded_window):
    panel = loaded_window.settings_panel
    overlay = loaded_window.drop_area.crop_overlay
    assert overlay.aspect() is None

    panel.aspect_combo.setCurrentIndex(panel.aspect_combo.findData(AspectRatio.RATIO_3_2))
    assert overlay.aspect() == (3, 2)

    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))
    assert overlay.aspect() == (79, 79)


def test_drag_with_aspect_updates_panel(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.aspect_combo.setCurrentIndex(panel.aspect_combo.findData(AspectRatio.SQUARE))
    overlay = loaded_window.drop_area.crop_overlay
    image_rect = loaded_window.drop_area.image_rect()

    def to_widget(x, y):
        point = image_to_widget(x, y, image_rect, (400, 300))
        return QPoint(round(point.x()), round(point.y()))

    qtbot.mousePress(overlay, Qt.MouseButton.LeftButton, pos=to_widget(50, 50))
    qtbot.mouseMove(overlay, to_widget(200, 100))
    qtbot.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=to_widget(200, 100))

    crop = panel.settings().crop
    assert crop is not None
    assert abs(crop.width - crop.height) <= 1
    assert overlay.crop() == crop


def test_frame_mask_matches_saved_crop(loaded_window, qtbot, tmp_path):
    # フレームを選ぶとマスクの範囲 = 実際に切り抜かれる範囲
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 300, 100))
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))

    overlay_crop = loaded_window.drop_area.crop_overlay.crop()

    assert overlay_crop == CropRect(100, 0, 100, 100)
    assert panel.base_size() == (100, 100)


# --- 既定値に戻す -------------------------------------------------------------


def test_double_click_slider_updates_preview(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.saturation_slider.setValue(-100)  # 白黒
    loaded_window.update_preview()
    assert len(set(preview_pixel(loaded_window, 50, 150))) == 1

    qtbot.mouseDClick(panel.saturation_slider, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 50, 150) == (220, 60, 30), timeout=2000)


def test_reset_adjustments_keeps_image_and_crop(loaded_window, qtbot, questions):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 200, 100))
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.MONOTONE))
    panel.exposure_slider.setValue(10)
    loaded_window.update_preview()

    panel.reset_adjustments_button.click()

    # 確認ダイアログを出さず、画像とトリミング範囲は残る
    assert questions["asked"] == 0
    assert loaded_window.loaded is not None
    assert panel.settings().crop == CropRect(0, 0, 200, 100)
    assert loaded_window.drop_area.crop_overlay.crop() == CropRect(0, 0, 200, 100)
    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 50, 150) == (220, 60, 30), timeout=2000)


# --- 回転・反転 ---------------------------------------------------------------


def test_rotation_updates_preview_immediately(loaded_window):
    panel = loaded_window.settings_panel

    panel.rotate_right_button.click()

    # 待たずにすぐ描き直し、範囲選択の座標系も回転後に合わせる
    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (300, 400)
    assert loaded_window.drop_area.crop_overlay.image_size() == (300, 400)
    # 左半分が赤の 400x300 → 時計回りに 90° で上半分が赤
    assert preview_pixel(loaded_window, 150, 50) == (220, 60, 30)
    assert preview_pixel(loaded_window, 150, 350) == (40, 120, 200)
    assert "出力 300×400 px" in loaded_window.status_label.text()


def test_overlay_matches_preview_after_several_ops(loaded_window):
    panel = loaded_window.settings_panel
    panel.rotate_right_button.click()
    panel.flip_horizontal_button.click()
    panel.rotate_right_button.click()

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (400, 300)
    assert loaded_window.drop_area.crop_overlay.image_size() == (400, 300)


def test_rotation_moves_overlay_crop(loaded_window):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 100, 50))

    panel.rotate_left_button.click()

    # 反時計回りに 90°: (x, y) → (y, 400 - x - w)
    assert loaded_window.drop_area.crop_overlay.crop() == CropRect(0, 300, 50, 100)


def test_save_rotated(loaded_window, qtbot, tmp_path):
    panel = loaded_window.settings_panel
    panel.rotate_right_button.click()
    panel.flip_vertical_button.click()
    out = tmp_path / "rotated.png"

    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image
    assert saved.size == (300, 400)
    # 上半分が赤 → 上下反転で下半分が赤
    assert saved.getpixel((150, 350)) == (220, 60, 30)
    assert saved.getpixel((150, 50)) == (40, 120, 200)


def test_rotation_counts_as_unsaved_change(loaded_window):
    loaded_window.settings_panel.rotate_right_button.click()
    assert loaded_window.has_unsaved_changes()


def test_new_image_resets_orientation(loaded_window, tmp_path, questions):
    loaded_window.settings_panel.rotate_right_button.click()
    path = tmp_path / "other.png"
    Image.new("RGB", (200, 100)).save(path)

    loaded_window.load_file(path)

    assert loaded_window.drop_area.crop_overlay.image_size() == (200, 100)
    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (200, 100)


# --- アンドゥ／リドゥ -------------------------------------------------------------


def test_edit_menu_actions(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    edit_menu = [a.menu() for a in window.menuBar().actions() if a.menu()][1]
    texts = [a.text() for a in edit_menu.actions() if not a.isSeparator()]
    assert texts == ["元に戻す", "やり直す", "文字・透かし…"]
    assert window.undo_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Undo)
    assert window.redo_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Redo)
    assert not window.undo_action.isEnabled()
    assert not window.redo_action.isEnabled()


def test_undo_redo_filter_size_and_crop(loaded_window):
    panel = loaded_window.settings_panel
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.SEPIA))
    loaded_window._commit_history()
    panel.width_spin.setValue(200)
    loaded_window._commit_history()
    panel.set_crop(CropRect(0, 0, 100, 50))
    loaded_window._commit_history()
    after_crop = panel.settings()

    loaded_window.undo_action.trigger()
    assert panel.settings().crop is None
    assert panel.settings().width == 200

    loaded_window.undo_action.trigger()
    assert panel.settings().width is None
    assert panel.settings().filter is FilterType.SEPIA
    assert (panel.width_spin.value(), panel.height_spin.value()) == (400, 300)

    loaded_window.undo_action.trigger()
    assert panel.settings() == EditSettings()
    assert not loaded_window.undo_action.isEnabled()

    for _ in range(3):
        loaded_window.redo_action.trigger()
    assert panel.settings() == after_crop
    assert loaded_window.drop_area.crop_overlay.crop() == CropRect(0, 0, 100, 50)
    assert not loaded_window.redo_action.isEnabled()


def test_undo_pending_change_immediately(loaded_window):
    # 履歴に積む前（変更の直後）でも ⌘Z で戻せる
    panel = loaded_window.settings_panel
    panel.brightness_slider.setValue(40)
    assert loaded_window.undo_action.isEnabled()

    loaded_window.undo()

    assert panel.brightness_slider.value() == 0
    assert loaded_window.redo_action.isEnabled()
    loaded_window.redo()
    assert panel.brightness_slider.value() == 40


def test_slider_drag_is_one_step(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    slider = panel.saturation_slider

    slider.setSliderDown(True)
    for value in range(-10, -110, -10):
        slider.setValue(value)
        qtbot.wait(60)
    qtbot.wait(700)  # ドラッグ中は時間がたっても積まない
    assert not loaded_window._history.can_undo()
    slider.setSliderDown(False)
    qtbot.waitUntil(lambda: loaded_window._history.can_undo(), timeout=2000)

    loaded_window.undo()

    # 1 回の ⌘Z でドラッグ前に戻る
    assert slider.value() == 0
    assert not loaded_window._history.can_undo()


def test_quick_changes_are_grouped(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    for value in (1, 2, 3):
        panel.contrast_slider.setValue(value)  # キーボードの矢印キーなど
    qtbot.waitUntil(lambda: loaded_window._history.can_undo(), timeout=2000)

    loaded_window.undo()

    assert panel.contrast_slider.value() == 0


def test_crop_drag_is_one_step(loaded_window, qtbot):
    overlay = loaded_window.drop_area.crop_overlay
    image_rect = loaded_window.drop_area.image_rect()

    def to_widget(x, y):
        point = image_to_widget(x, y, image_rect, (400, 300))
        return QPoint(round(point.x()), round(point.y()))

    qtbot.mousePress(overlay, Qt.MouseButton.LeftButton, pos=to_widget(50, 50))
    for x in (100, 150, 200):
        qtbot.mouseMove(overlay, to_widget(x, 150))
        qtbot.wait(300)
    qtbot.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=to_widget(200, 150))
    loaded_window._commit_history()

    loaded_window.undo()

    assert loaded_window.settings_panel.settings().crop is None
    assert not loaded_window._history.can_undo()


def test_undo_rotation(loaded_window):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 100, 50))
    loaded_window._commit_history()
    panel.rotate_right_button.click()

    loaded_window.undo()

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (400, 300)
    assert loaded_window.drop_area.crop_overlay.image_size() == (400, 300)
    assert loaded_window.drop_area.crop_overlay.crop() == CropRect(0, 0, 100, 50)


def test_undo_updates_preview(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.saturation_slider.setValue(-100)
    loaded_window.update_preview()
    assert len(set(preview_pixel(loaded_window, 50, 150))) == 1

    loaded_window.undo()

    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 50, 150) == (220, 60, 30), timeout=2000)


def test_new_change_clears_redo(loaded_window):
    panel = loaded_window.settings_panel
    panel.vignette_slider.setValue(10)
    loaded_window.undo()
    assert loaded_window.redo_action.isEnabled()

    panel.aging_slider.setValue(10)

    assert not loaded_window.redo_action.isEnabled()
    loaded_window._commit_history()
    assert not loaded_window._history.can_redo()


def test_load_clears_history(loaded_window, tmp_path, questions):
    loaded_window.settings_panel.brightness_slider.setValue(30)
    loaded_window._commit_history()
    path = tmp_path / "other.png"
    Image.new("RGB", (50, 40)).save(path)

    loaded_window.load_file(path)

    assert not loaded_window.undo_action.isEnabled()
    assert not loaded_window.redo_action.isEnabled()
    loaded_window.undo()
    assert loaded_window.settings_panel.settings() == EditSettings()


def test_reset_clears_history(loaded_window, questions):
    loaded_window.settings_panel.brightness_slider.setValue(30)
    loaded_window._commit_history()

    loaded_window.reset()

    assert not loaded_window.undo_action.isEnabled()
    assert not loaded_window._history.can_undo()


def test_undo_disabled_while_saving(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.brightness_slider.setValue(30)
    with qtbot.waitSignal(loaded_window.save_finished, timeout=10000):
        assert loaded_window.save_to(tmp_path / "out.png")
        assert not loaded_window.undo_action.isEnabled()
    assert loaded_window.undo_action.isEnabled()


# --- 保存の設定（JPEG 品質・EXIF） ----------------------------------------------

TAG_ORIENTATION = 0x0112
TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825
TAG_DATETIME_ORIGINAL = 0x9003
TAKEN_AT = "2026:01:02 03:04:05"


@pytest.fixture
def exif_window(window, tmp_path):
    """向き 6（時計回りに 90°）・撮影日時・位置情報を持つ 40x20 の JPEG を開いたウィンドウ。"""
    exif = Image.Exif()
    exif[TAG_ORIENTATION] = 6
    exif.get_ifd(TAG_EXIF_IFD)[TAG_DATETIME_ORIGINAL] = TAKEN_AT
    exif.get_ifd(TAG_GPS_IFD)[1] = "N"
    path = tmp_path / "camera.jpg"
    Image.new("RGB", (40, 20), (220, 60, 30)).save(path, exif=exif)
    window.load_file(path)
    return window


def saved_exif(path):
    with Image.open(path) as image:
        exif = image.getexif()
        return exif, dict(exif.get_ifd(TAG_EXIF_IFD)), dict(exif.get_ifd(TAG_GPS_IFD))


def test_save_keeps_exif_without_gps(exif_window, qtbot, tmp_path):
    out = tmp_path / "out.jpg"

    save_and_wait(qtbot, exif_window, out)

    exif, exif_ifd, gps = saved_exif(out)
    assert exif[TAG_ORIENTATION] == 1
    assert exif_ifd[TAG_DATETIME_ORIGINAL] == TAKEN_AT
    assert gps == {}
    # 向きは補正済みで、他のアプリで開いても回転しない
    assert load_image(out).image.size == (20, 40)


def test_save_keeps_gps_when_selected(exif_window, qtbot, tmp_path):
    exif_window.settings_panel.set_save_options(SaveOptions(keep_gps=True))
    out = tmp_path / "out.png"

    save_and_wait(qtbot, exif_window, out)

    assert saved_exif(out)[2] == {1: "N"}


def test_save_without_exif(exif_window, qtbot, tmp_path):
    exif_window.settings_panel.keep_exif_check.setChecked(False)
    out = tmp_path / "out.jpg"

    save_and_wait(qtbot, exif_window, out)

    assert len(saved_exif(out)[0]) == 0


def test_save_uses_quality(loaded_window, qtbot, tmp_path):
    noisy = Image.effect_noise((200, 200), 64).convert("RGB")
    path = tmp_path / "noisy.png"
    noisy.save(path)
    loaded_window.load_file(path)
    low, high = tmp_path / "low.jpg", tmp_path / "high.jpg"

    loaded_window.settings_panel.quality_slider.setValue(10)
    save_and_wait(qtbot, loaded_window, low)
    loaded_window.settings_panel.quality_slider.setValue(95)
    save_and_wait(qtbot, loaded_window, high)

    assert low.stat().st_size < high.stat().st_size


def test_save_options_are_remembered(qtbot, preferences):
    first = MainWindow()
    qtbot.addWidget(first)
    first.settings_panel.set_save_options_expanded(True)
    first.settings_panel.quality_slider.setValue(70)
    first.settings_panel.keep_gps_check.setChecked(True)

    # 次に起動したとき（同じ環境設定を読む）も前回の値を使う
    second = MainWindow()
    qtbot.addWidget(second)

    assert second.settings_panel.save_options() == SaveOptions(quality=70, keep_gps=True)
    assert second.settings_panel.is_save_options_expanded()


def test_save_options_start_with_defaults(window):
    assert window.settings_panel.save_options() == SaveOptions()
    assert not window.settings_panel.is_save_options_expanded()


# --- 加工前との比較 -------------------------------------------------------------

RED = (220, 60, 30)


def make_gray(window):
    window.settings_panel.saturation_slider.setValue(-100)
    window.update_preview()
    assert len(set(preview_pixel(window, 50, 150))) == 1


def test_compare_shows_before_image(loaded_window):
    make_gray(loaded_window)

    loaded_window.set_comparing(True)

    assert loaded_window.is_comparing()
    assert preview_pixel(loaded_window, 50, 150) == RED
    assert loaded_window.drop_area.badge_text() == "加工前"
    # 設定は変わらない
    assert loaded_window.settings_panel.saturation_slider.value() == -100

    loaded_window.set_comparing(False)

    assert len(set(preview_pixel(loaded_window, 50, 150))) == 1
    assert loaded_window.drop_area.badge_text() is None


def test_compare_button_while_pressed(loaded_window, qtbot):
    make_gray(loaded_window)
    button = loaded_window.settings_panel.compare_button

    qtbot.mousePress(button, Qt.MouseButton.LeftButton)
    assert preview_pixel(loaded_window, 50, 150) == RED
    qtbot.mouseRelease(button, Qt.MouseButton.LeftButton)

    assert not loaded_window.is_comparing()
    assert len(set(preview_pixel(loaded_window, 50, 150))) == 1


def activate(window, qtbot):
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)


@pytest.mark.parametrize("key", [Qt.Key.Key_Backslash, Qt.Key.Key_yen])
def test_compare_key_while_pressed(loaded_window, qtbot, key):
    activate(loaded_window, qtbot)
    make_gray(loaded_window)
    spin = loaded_window.settings_panel.width_spin
    spin.setFocus()

    qtbot.keyPress(spin, key)
    assert loaded_window.is_comparing()
    assert preview_pixel(loaded_window, 50, 150) == RED
    qtbot.keyRelease(spin, key)

    assert not loaded_window.is_comparing()
    assert spin.value() == 400  # 数値欄に文字として入らない


def test_compare_key_auto_repeat_is_ignored(loaded_window, qtbot):
    from PyQt6.QtGui import QKeyEvent

    activate(loaded_window, qtbot)
    loaded_window.set_comparing(True)
    target = loaded_window.settings_panel.width_spin
    # 押しっぱなしの自動リピートで届く「離した」は無視する
    repeat_release = QKeyEvent(
        QKeyEvent.Type.KeyRelease,
        Qt.Key.Key_Backslash,
        Qt.KeyboardModifier.NoModifier,
        "\\",
        True,
    )
    QApplication.sendEvent(target, repeat_release)

    assert loaded_window.is_comparing()


def test_compare_keeps_orientation_and_trim_region(loaded_window):
    panel = loaded_window.settings_panel
    panel.rotate_right_button.click()
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))
    panel.shape_combo.setCurrentIndex(panel.shape_combo.findData(ShapeType.CIRCLE))
    panel.trim_button.click()

    loaded_window.set_comparing(True)

    # 回転後 300x400 → 写真部分の比 (正方形) の範囲 300x300。フレーム・形は外す
    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (300, 300)
    assert not source.hasAlphaChannel() or source.pixelColor(0, 0).alpha() == 255


def test_compare_follows_setting_changes(loaded_window, qtbot):
    loaded_window.set_comparing(True)
    loaded_window.settings_panel.rotate_right_button.click()

    source = loaded_window.drop_area._source
    assert (source.width(), source.height()) == (300, 400)
    assert preview_pixel(loaded_window, 150, 50) == RED  # 回転は反映、色はそのまま


def test_compare_ends_when_window_deactivates(loaded_window, monkeypatch):
    # キーを押したまま別のウィンドウに移ると「離した」が届かないので、非アクティブ時に戻す
    from PyQt6.QtCore import QEvent

    loaded_window.set_comparing(True)
    monkeypatch.setattr(loaded_window, "isActiveWindow", lambda: False)

    loaded_window.changeEvent(QEvent(QEvent.Type.ActivationChange))

    assert not loaded_window.is_comparing()


def test_compare_key_ignored_when_inactive(loaded_window, qtbot, monkeypatch):
    monkeypatch.setattr(loaded_window, "isActiveWindow", lambda: False)
    qtbot.keyPress(loaded_window.settings_panel.width_spin, Qt.Key.Key_Backslash)
    assert not loaded_window.is_comparing()


def test_compare_ignored_without_image(window):
    window.set_comparing(True)
    assert not window.is_comparing()
    assert window.drop_area.badge_text() is None


def test_load_ends_compare(loaded_window, tmp_path, questions):
    loaded_window.set_comparing(True)
    path = tmp_path / "other.png"
    Image.new("RGB", (50, 40)).save(path)

    loaded_window.load_file(path)

    assert not loaded_window.is_comparing()
    assert loaded_window.drop_area.badge_text() is None


# --- 通常の表示での形（角丸・円）のマスク -------------------------------------------


def select_shape_in(window: MainWindow, shape: ShapeType) -> None:
    combo = window.settings_panel.shape_combo
    combo.setCurrentIndex(combo.findData(shape))


def widget_rect(window: MainWindow, rect: CropRect):
    from image_editor.ui.crop_overlay import crop_to_widget_rect

    return crop_to_widget_rect(rect, window.drop_area.image_rect(), (400, 300))


def test_whole_view_shows_rounded_mask(loaded_window):
    overlay = loaded_window.drop_area.crop_overlay

    select_shape_in(loaded_window, ShapeType.ROUNDED)

    outline = overlay.shape_outline()
    assert outline is not None
    assert outline.boundingRect() == loaded_window.drop_area.image_rect()
    # 通常の表示のまま（切り抜き表示には切り替えない）
    assert not loaded_window.settings_panel.is_trim_view()
    assert overlay.is_active()


def test_corner_radius_updates_mask_immediately(loaded_window):
    overlay = loaded_window.drop_area.crop_overlay
    select_shape_in(loaded_window, ShapeType.ROUNDED)
    panel = loaded_window.settings_panel
    image_rect = loaded_window.drop_area.image_rect()
    near_corner = image_rect.topLeft() + QPointF(8, 8)

    panel.corner_slider.setValue(0)
    assert overlay.shape_outline() is None  # 半径 0 は矩形と同じ

    panel.corner_slider.setValue(50)
    outline = overlay.shape_outline()
    assert outline is not None
    assert not outline.contains(near_corner)


def test_circle_mask_matches_saved_crop(loaded_window):
    # フレームなしの円は中央の正方形 (50, 0, 300, 300) に内接する円
    select_shape_in(loaded_window, ShapeType.CIRCLE)

    outline = loaded_window.drop_area.crop_overlay.shape_outline()

    assert outline is not None
    expected = widget_rect(loaded_window, CropRect(50, 0, 300, 300))
    assert outline.boundingRect().toRect() == expected.toRect()


def test_circle_mask_inside_frame_window(loaded_window):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 400, 300))
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.INSTAX_MINI))
    select_shape_in(loaded_window, ShapeType.CIRCLE)

    outline = loaded_window.drop_area.crop_overlay.shape_outline()

    # チェキの写真部分（範囲）の中に、短辺を直径とする円
    crop = panel.settings().crop
    assert crop is not None
    window_rect = widget_rect(loaded_window, crop)
    assert outline is not None
    bounds = outline.boundingRect()
    assert round(bounds.height()) == round(min(window_rect.width(), window_rect.height()))
    assert bounds.center().toPoint() == window_rect.center().toPoint()


def test_rectangle_has_no_mask(loaded_window):
    select_shape_in(loaded_window, ShapeType.ROUNDED)
    select_shape_in(loaded_window, ShapeType.RECTANGLE)
    assert loaded_window.drop_area.crop_overlay.shape_outline() is None


# --- プリセット -------------------------------------------------------------------


def test_default_preset_name():
    from image_editor.core.presets import Preset
    from image_editor.ui.main_window import default_preset_name

    assert default_preset_name([]) == "プリセット 1"
    assert default_preset_name([Preset(name="プリセット 1")]) == "プリセット 2"


def fake_input(monkeypatch, name, ok=True):
    calls = []

    def get_text(parent, title, label, text=""):
        calls.append(text)
        return name, ok

    monkeypatch.setattr(QInputDialog, "getText", get_text)
    return calls


def test_save_preset_and_reload(loaded_window, qtbot, monkeypatch, presets_path):
    from image_editor.core.presets import load_presets

    panel = loaded_window.settings_panel
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(FilterType.SEPIA))
    panel.vignette_slider.setValue(50)
    calls = fake_input(monkeypatch, "  セピア＋減光  ")

    loaded_window.save_preset_dialog()

    assert calls == ["プリセット 1"]  # 名前の初期値
    (saved,) = load_presets(presets_path)
    assert saved.name == "セピア＋減光"
    assert (saved.filter, saved.vignette) == (FilterType.SEPIA, 50)
    assert [p.name for p in panel.presets()] == ["セピア＋減光"]
    assert "プリセット「セピア＋減光」を保存しました" in loaded_window.status_label.text()

    # アプリを再起動しても呼び出せる
    second = MainWindow()
    qtbot.addWidget(second)
    assert [p.name for p in second.settings_panel.presets()] == ["セピア＋減光"]


def test_save_preset_cancel(loaded_window, monkeypatch, presets_path):
    fake_input(monkeypatch, "何か", ok=False)
    loaded_window.save_preset_dialog()
    fake_input(monkeypatch, "   ")
    loaded_window.save_preset_dialog()
    assert not presets_path.exists()


def test_save_preset_overwrite_asks(loaded_window, monkeypatch, questions):
    fake_input(monkeypatch, "同じ名前")
    loaded_window.save_preset_dialog()
    loaded_window.settings_panel.brightness_slider.setValue(40)

    questions["answer"] = QMessageBox.StandardButton.Cancel
    loaded_window.save_preset_dialog()
    assert questions["asked"] == 1
    assert loaded_window.settings_panel.presets()[0].brightness == 0

    questions["answer"] = QMessageBox.StandardButton.Yes
    loaded_window.save_preset_dialog()
    assert loaded_window.settings_panel.presets()[0].brightness == 40


def test_delete_preset_asks(loaded_window, monkeypatch, questions, presets_path):
    from image_editor.core.presets import load_presets

    fake_input(monkeypatch, "消すもの")
    loaded_window.save_preset_dialog()

    questions["answer"] = QMessageBox.StandardButton.Cancel
    loaded_window.delete_preset("消すもの")
    assert len(load_presets(presets_path)) == 1

    questions["answer"] = QMessageBox.StandardButton.Yes
    loaded_window.delete_preset("消すもの")
    assert load_presets(presets_path) == []
    assert loaded_window.settings_panel.presets() == []


def test_apply_preset_updates_preview(loaded_window, qtbot):
    from image_editor.core.presets import Preset

    loaded_window.settings_panel.set_presets([Preset(name="白黒", saturation=-100)])

    loaded_window.settings_panel.preset_menu.actions()[0].trigger()

    qtbot.waitUntil(lambda: len(set(preview_pixel(loaded_window, 50, 150))) == 1, timeout=2000)
    assert loaded_window.has_unsaved_changes()
    loaded_window.undo()  # プリセットの当てはめも 1 回の操作として戻せる
    assert loaded_window.settings_panel.saturation_slider.value() == 0


def test_save_preset_error_is_shown(loaded_window, monkeypatch, warnings):
    from image_editor.core.presets import PresetError
    from image_editor.ui import main_window as module

    def fail(path, presets):
        raise PresetError("書き込めません")

    monkeypatch.setattr(module, "save_presets", fail)
    fake_input(monkeypatch, "失敗")

    loaded_window.save_preset_dialog()

    assert warnings and "書き込めません" in warnings[-1][1]
    assert loaded_window.settings_panel.presets() == []


def test_broken_presets_file_is_reported(qtbot, presets_path, warnings):
    presets_path.parent.mkdir(parents=True)
    presets_path.write_text("{", encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: bool(warnings), timeout=2000)

    assert warnings[-1][0] == "プリセットを読み込めません"
    assert window.settings_panel.presets() == []


# --- まとめて処理 -----------------------------------------------------------------


def make_images(folder, count, size=(400, 300)):
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        path = folder / f"img{i}.png"
        Image.new("RGB", size, (220, 60, 30)).save(path)
        paths.append(path)
    return paths


def run_batch_and_wait(qtbot, window, sources, out_dir, options):
    with qtbot.waitSignal(window.batch_finished, timeout=20000) as blocker:
        assert window.start_batch(sources, out_dir, options)
        assert window.is_batch_running()
        assert not window.batch_action.isEnabled()  # 実行中は始められない
    return blocker.args


def test_batch_applies_look_and_resize(window, qtbot, tmp_path, monkeypatch):
    from image_editor.core.batch import BatchOptions
    from image_editor.core.presets import Preset

    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(args[2]))
    sources = make_images(tmp_path / "in", 3) + make_images(tmp_path / "tall", 1, (300, 400))

    results, cancelled = run_batch_and_wait(
        qtbot,
        window,
        sources,
        tmp_path / "out",
        BatchOptions(look=Preset(name="白黒", saturation=-100), long_side=100),
    )

    assert not cancelled
    assert [r.error for r in results] == [None] * 4
    for result in results:
        saved = load_image(result.output).image
        assert max(saved.size) == 100  # 横長も縦長も長辺が 100
        r, g, b = saved.getpixel((10, 10))
        assert abs(r - g) <= 3 and abs(g - b) <= 3
    assert "4 枚を保存しました" in infos[-1]
    assert not window.is_batch_running()
    assert window.batch_action.isEnabled()


def test_batch_reports_failures(window, qtbot, tmp_path, monkeypatch):
    from image_editor.core.batch import BatchOptions
    from image_editor.core.presets import Preset

    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(args[2]))
    broken = tmp_path / "in" / "broken.png"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"x")

    run_batch_and_wait(
        qtbot,
        window,
        [broken, *make_images(tmp_path / "in2", 1)],
        tmp_path / "out",
        BatchOptions(look=Preset(name="なし")),
    )

    assert "1 枚を保存しました" in infos[-1]
    assert "1 枚は処理できませんでした" in infos[-1]
    assert "broken.png" in infos[-1]


def test_batch_cancel_from_progress_dialog(window, qtbot, tmp_path, monkeypatch):
    from image_editor.core.batch import BatchOptions
    from image_editor.core.presets import Preset

    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(args[2]))
    sources = make_images(tmp_path / "in", 30, size=(1500, 1000))

    with qtbot.waitSignal(window.batch_finished, timeout=60000) as blocker:
        window.start_batch(sources, tmp_path / "out", BatchOptions(look=Preset(name="なし")))
        window._batch_progress.canceled.emit()  # 「中止」を押す

    results, cancelled = blocker.args
    assert cancelled
    assert len(results) < len(sources)
    assert infos[-1].startswith("中止しました。")


def test_batch_task_cancel_before_run(tmp_path):
    from image_editor.core.batch import BatchOptions
    from image_editor.core.presets import Preset
    from image_editor.ui.worker import BatchTask

    task = BatchTask(make_images(tmp_path / "in", 2), tmp_path / "out", BatchOptions(Preset("x")))
    received = []
    task.signals.finished.connect(lambda results, cancelled: received.append((results, cancelled)))

    task.cancel()
    task.run()

    assert received == [([], True)]


def test_batch_dialog_uses_current_look_and_image(loaded_window, qtbot, tmp_path, monkeypatch):
    from image_editor.ui.batch_dialog import BatchDialog

    panel = loaded_window.settings_panel
    panel.brightness_slider.setValue(25)
    panel.width_spin.setValue(200)
    started = []
    monkeypatch.setattr(
        loaded_window,
        "start_batch",
        lambda sources, out, options: started.append((sources, out, options)),
    )

    def fake_exec(dialog):
        assert dialog.sources() == [loaded_window.loaded.path]
        assert dialog.resize_check.isChecked()
        assert dialog.long_side_spin.value() == 200  # 今の出力の長辺
        dialog.set_out_dir(tmp_path / "out")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BatchDialog, "exec", fake_exec)

    loaded_window.batch_action.trigger()

    ((sources, out, options),) = started
    assert sources == [loaded_window.loaded.path]
    assert out == tmp_path / "out"
    assert options.look.brightness == 25
    assert options.long_side == 200
    assert options.save == panel.save_options()


def test_batch_dialog_cancel_does_nothing(window, monkeypatch):
    from image_editor.ui.batch_dialog import BatchDialog

    monkeypatch.setattr(BatchDialog, "exec", lambda dialog: QDialog.DialogCode.Rejected)
    window.batch_dialog()
    assert not window.is_batch_running()


# --- ディテール --------------------------------------------------------------------


def test_detail_updates_preview(loaded_window, qtbot):
    before = loaded_window.drop_area._source.pixelColor(200, 150).getRgb()
    # 左半分が赤、右半分が青の境目がぼける
    loaded_window.settings_panel.blur_slider.setValue(100)

    qtbot.waitUntil(
        lambda: loaded_window.drop_area._source.pixelColor(199, 150).getRgb() != before,
        timeout=2000,
    )


def test_detail_expanded_is_remembered(qtbot, preferences):
    first = MainWindow()
    qtbot.addWidget(first)
    # 画像を開いていないとボタンは押せないので、状態を直接切り替える（押したときと同じ通知が出る）
    first.settings_panel.detail_toggle.setChecked(True)

    second = MainWindow()
    qtbot.addWidget(second)
    assert second.settings_panel.is_detail_expanded()


def test_saved_image_has_detail(loaded_window, qtbot, tmp_path):
    loaded_window.settings_panel.blur_slider.setValue(100)
    out = tmp_path / "blur.png"

    save_and_wait(qtbot, loaded_window, out)

    saved = load_image(out).image
    # 境目 (x = 200) の近くが赤と青の中間の色になる
    r, _, b = saved.getpixel((199, 150))
    assert 40 < r < 220 and 30 < b < 200


# --- ヒストグラム ------------------------------------------------------------------


def test_histogram_shown_after_load(loaded_window):
    view = loaded_window.drop_area.histogram_view
    assert loaded_window.is_histogram_shown()  # 既定は表示
    assert view.isVisible()
    histogram = view.histogram()
    assert histogram is not None
    assert histogram.total() == 400 * 300


def test_histogram_updates_with_adjustments(loaded_window, qtbot):
    view = loaded_window.drop_area.histogram_view
    before = view.histogram()

    loaded_window.settings_panel.exposure_slider.setValue(20)  # +2.0 EV

    qtbot.waitUntil(lambda: view.histogram() != before, timeout=2000)
    after = view.histogram()
    assert after is not None and before is not None
    brightest_before = max(v for v in range(256) if before.luma[v])
    brightest_after = max(v for v in range(256) if after.luma[v])
    assert brightest_after > brightest_before


def test_histogram_counts_crop_range(loaded_window, qtbot):
    loaded_window.settings_panel.set_crop(CropRect(0, 0, 100, 100))
    loaded_window.settings_panel.vignette_slider.setValue(1)  # 範囲が見た目に影響する設定
    loaded_window.update_preview()
    assert loaded_window.drop_area.histogram_view.histogram().total() == 100 * 100


def test_histogram_toggle_is_remembered(loaded_window, qtbot, preferences):
    action = loaded_window.histogram_action
    assert action.shortcut() == QKeySequence("Ctrl+Shift+H")

    action.trigger()  # 隠す

    assert not loaded_window.is_histogram_shown()
    assert not loaded_window.drop_area.histogram_view.isVisible()
    second = MainWindow()
    qtbot.addWidget(second)
    assert not second.is_histogram_shown()

    action.trigger()  # 表示する
    assert loaded_window.drop_area.histogram_view.isVisible()


def test_histogram_hidden_without_image(qtbot, loaded_window, questions):
    empty = MainWindow()
    qtbot.addWidget(empty)
    assert not empty.drop_area.histogram_view.isVisible()

    loaded_window.reset()
    assert not loaded_window.drop_area.histogram_view.isVisible()


def test_histogram_follows_compare(loaded_window):
    loaded_window.settings_panel.saturation_slider.setValue(-100)
    loaded_window.update_preview()
    gray = loaded_window.drop_area.histogram_view.histogram()

    loaded_window.set_comparing(True)

    before = loaded_window.drop_area.histogram_view.histogram()
    assert before != gray
    assert before.red[220] > 0  # 加工前は赤 (220, 60, 30) が残る


# --- 文字・透かし -------------------------------------------------------------------


def test_text_menu_opens_dialog(loaded_window):
    from image_editor.core.text import TextSettings

    assert loaded_window.text_action.shortcut() == QKeySequence("Ctrl+T")
    loaded_window.settings_panel.set_text_settings(TextSettings(text="既にある文字"))

    loaded_window.text_action.trigger()

    assert loaded_window.text_dialog.isVisible()
    assert loaded_window.text_dialog.settings().text == "既にある文字"
    loaded_window.text_dialog.close()


def test_text_button_opens_dialog(loaded_window):
    loaded_window.settings_panel.text_button.click()
    assert loaded_window.text_dialog.isVisible()
    loaded_window.text_dialog.close()


def test_text_action_disabled_without_image(window):
    assert not window.text_action.isEnabled()
    window.open_text_dialog()
    assert not window.text_dialog.isVisible()


def test_text_dialog_updates_preview_and_save(loaded_window, qtbot, tmp_path):
    from image_editor.core.text import TextPosition

    loaded_window.open_text_dialog()
    dialog = loaded_window.text_dialog
    dialog.opacity_slider.setValue(100)
    dialog.set_color((0, 255, 0))
    dialog.position_combo.setCurrentIndex(dialog.position_combo.findData(TextPosition.CENTER))
    dialog.size_spin.setValue(20)
    dialog.text_edit.setPlainText("■")

    assert loaded_window.settings_panel.text_settings().text == "■"
    qtbot.waitUntil(lambda: preview_pixel(loaded_window, 200, 150) == (0, 255, 0), timeout=2000)

    out = tmp_path / "text.png"
    save_and_wait(qtbot, loaded_window, out)
    assert load_image(out).image.getpixel((200, 150)) == (0, 255, 0)
    dialog.close()


def test_text_change_can_be_undone_and_syncs_dialog(loaded_window):
    loaded_window.open_text_dialog()
    loaded_window.text_dialog.text_edit.setPlainText("あとで戻す")

    loaded_window.undo()

    assert loaded_window.settings_panel.text_settings().text == ""
    assert loaded_window.text_dialog.text_edit.toPlainText() == ""
    loaded_window.text_dialog.close()


def test_text_is_part_of_preset(loaded_window):
    from image_editor.core.presets import Preset
    from image_editor.core.text import TextSettings

    panel = loaded_window.settings_panel
    panel.set_text_settings(TextSettings(text="透かし"))
    assert panel.snapshot().settings.text.text == "透かし"

    panel.apply_preset(Preset(name="別の透かし", text=TextSettings(text="© 別")))

    assert panel.text_settings().text == "© 別"


def test_new_image_resets_text(loaded_window, tmp_path, questions):
    from image_editor.core.text import TextSettings

    loaded_window.settings_panel.set_text_settings(TextSettings(text="消える"))
    path = tmp_path / "other.png"
    Image.new("RGB", (40, 30)).save(path)

    loaded_window.load_file(path)

    assert loaded_window.settings_panel.text_settings() == TextSettings()


# --- 100% 表示 ----------------------------------------------------------------------


def wait_zoom(qtbot, window):
    qtbot.waitUntil(
        lambda: window.drop_area.is_zoomed() and not window.is_zoom_rendering(), timeout=5000
    )


def test_zoom_menu_shortcuts(loaded_window):
    assert loaded_window.zoom_action.shortcut() == QKeySequence("Ctrl+1")
    assert loaded_window.fit_action.shortcut() == QKeySequence("Ctrl+0")
    assert loaded_window.zoom_action.isEnabled()
    assert not loaded_window.fit_action.isEnabled()


def test_zoom_shows_saved_result(loaded_window, qtbot):
    from image_editor.core.pipeline import apply_edits

    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 200, 150))
    panel.frame_combo.setCurrentIndex(panel.frame_combo.findData(FrameType.POLAROID))
    panel.sharpen_slider.setValue(40)

    loaded_window.zoom_action.trigger()

    assert loaded_window.is_zoomed()
    assert not loaded_window.drop_area.crop_overlay.is_active()  # ドラッグで見る場所を動かす
    assert loaded_window.drop_area.badge_text() == "100% ・ 更新中…"
    wait_zoom(qtbot, loaded_window)
    assert loaded_window.drop_area.badge_text() == "100%"
    expected = apply_edits(loaded_window.loaded.image, panel.settings())
    shown = loaded_window.drop_area._zoom.toImage()
    assert (shown.width(), shown.height()) == expected.size
    assert shown.pixelColor(100, 100).getRgb()[:3] == expected.getpixel((100, 100))
    assert loaded_window.fit_action.isEnabled()


def test_zoom_follows_setting_changes(loaded_window, qtbot):
    loaded_window.show_actual_size()
    wait_zoom(qtbot, loaded_window)

    loaded_window.settings_panel.saturation_slider.setValue(-100)

    qtbot.waitUntil(
        lambda: (
            not loaded_window.is_zoom_rendering()
            and len(set(loaded_window.drop_area._zoom.toImage().pixelColor(50, 50).getRgb()[:3]))
            == 1
        ),
        timeout=5000,
    )


def test_old_zoom_result_is_ignored(loaded_window, qtbot):
    loaded_window.show_actual_size()
    old = loaded_window._zoom_generation
    old_task = next(iter(loaded_window._zoom_tasks))
    loaded_window._render_zoom()  # 設定が変わって依頼し直した

    loaded_window._on_zoom_finished(old_task, Image.new("RGB", (5, 5)), old)

    assert loaded_window.is_zoom_rendering()  # 古い結果では終わらない
    wait_zoom(qtbot, loaded_window)


def test_running_zoom_tasks_are_kept_until_finished(loaded_window, qtbot):
    # 依頼し直しても、実行中の古いタスクは終わるまで保持する（片付けられると落ちる）
    loaded_window.show_actual_size()
    for _ in range(5):
        loaded_window._render_zoom()
    assert len(loaded_window._zoom_tasks) >= 1

    qtbot.waitUntil(lambda: not loaded_window._zoom_tasks, timeout=10000)
    assert not loaded_window.is_zoom_rendering()


def test_zoom_compare_shows_before(loaded_window, qtbot):
    loaded_window.settings_panel.saturation_slider.setValue(-100)
    loaded_window.show_actual_size()
    wait_zoom(qtbot, loaded_window)

    loaded_window.set_comparing(True)

    assert loaded_window.drop_area.badge_text().startswith("加工前 ・ 100%")
    wait_zoom(qtbot, loaded_window)
    assert loaded_window.drop_area._zoom.toImage().pixelColor(50, 50).getRgb()[:3] == (
        220,
        60,
        30,
    )
    loaded_window.set_comparing(False)


def test_fit_to_window_restores_view(loaded_window, qtbot):
    loaded_window.show_actual_size()
    wait_zoom(qtbot, loaded_window)

    loaded_window.fit_action.trigger()

    assert not loaded_window.is_zoomed()
    assert not loaded_window.drop_area.is_zoomed()
    assert loaded_window.drop_area.crop_overlay.is_active()
    assert loaded_window.drop_area.badge_text() is None


def test_double_click_in_zoom_returns_to_fit(loaded_window, qtbot):
    loaded_window.show_actual_size()
    wait_zoom(qtbot, loaded_window)

    qtbot.mouseDClick(loaded_window.drop_area, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))

    assert not loaded_window.is_zoomed()


def test_double_click_in_trim_view_zooms_at_point(loaded_window, qtbot):
    panel = loaded_window.settings_panel
    panel.set_crop(CropRect(0, 0, 400, 300))
    panel.trim_button.click()
    rect = loaded_window.drop_area.image_rect()
    point = QPoint(round(rect.left() + rect.width() * 0.25), round(rect.center().y()))

    qtbot.mouseDClick(loaded_window.drop_area, Qt.MouseButton.LeftButton, pos=point)

    assert loaded_window.is_zoomed()
    wait_zoom(qtbot, loaded_window)
    center = loaded_window.drop_area.zoom_center()
    assert center is not None
    # 画像の左から 1/4 あたりが中央（表示より画像が小さいときは中央にそろう）
    assert center[0] <= 400 * 0.5 + 2


def test_double_click_in_whole_view_does_not_zoom(loaded_window, qtbot):
    overlay = loaded_window.drop_area.crop_overlay
    qtbot.mouseDClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    assert not loaded_window.is_zoomed()


def test_load_leaves_zoom(loaded_window, qtbot, tmp_path, questions):
    loaded_window.show_actual_size()
    wait_zoom(qtbot, loaded_window)
    path = tmp_path / "other.png"
    Image.new("RGB", (40, 30)).save(path)

    loaded_window.load_file(path)

    assert not loaded_window.is_zoomed()
    assert not loaded_window.drop_area.is_zoomed()
    assert loaded_window.drop_area.crop_overlay.is_active()
