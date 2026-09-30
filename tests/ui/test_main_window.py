from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFileDialog, QLabel, QMenu, QMessageBox, QSplitter

from image_editor.app import create_window
from image_editor.core.filters import FilterType
from image_editor.core.frames import FrameType
from image_editor.core.io import load_image
from image_editor.core.shapes import ShapeType
from image_editor.core.transform import AspectRatio, CropRect
from image_editor.ui.crop_overlay import image_to_widget
from image_editor.ui.main_window import MainWindow, default_save_path, is_same_file


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
    assert [m.title() for m in menus] == ["ファイル"]
    texts = [a.text() for a in menus[0].actions() if not a.isSeparator()]
    assert texts == ["開く…", "保存…", "終了"]
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

    assert panel.width() >= panel.minimumSizeHint().width()
    for label in panel.findChildren(QLabel):
        if label.text() and label.isVisible():
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
