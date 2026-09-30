from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtWidgets import QFileDialog

from image_editor.core.io import SaveOptions
from image_editor.core.presets import Preset
from image_editor.ui.batch_dialog import BatchDialog

CURRENT = Preset(name="今の加工", brightness=10)
SEPIA = Preset(name="セピア", saturation=-50)


def make_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30)).save(path)
    return path


@pytest.fixture
def dialog(qtbot):
    widget = BatchDialog(CURRENT, [SEPIA], long_side=1200, resize=True)
    qtbot.addWidget(widget)
    return widget


def test_defaults(dialog):
    assert dialog.windowTitle() == "まとめて処理"
    assert dialog.sources() == []
    assert dialog.out_dir() is None
    assert not dialog.start_button.isEnabled()
    labels = [dialog.look_combo.itemText(i) for i in range(dialog.look_combo.count())]
    assert labels == ["今の加工", "プリセット: セピア"]
    assert dialog.resize_check.isChecked()
    assert dialog.long_side_spin.value() == 1200
    texts = [b.text() for b in dialog.buttons.buttons()]
    assert sorted(texts) == sorted(["開始", "キャンセル"])


def test_initial_sources(qtbot, tmp_path):
    source = make_image(tmp_path / "open.png")
    widget = BatchDialog(CURRENT, [], long_side=100, resize=False, sources=[source])
    qtbot.addWidget(widget)
    assert widget.sources() == [source]
    assert not widget.long_side_spin.isEnabled()


def test_add_files_and_folder(dialog, tmp_path, monkeypatch):
    a = make_image(tmp_path / "a.png")
    folder_images = [make_image(tmp_path / "folder" / name) for name in ("b.jpg", "c.png")]
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([str(a), str(a)], "")
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path / "folder")
    )

    dialog.add_files_button.click()
    dialog.add_folder_button.click()
    dialog.add_files_button.click()  # 同じファイルは二重に加えない

    assert dialog.sources() == [a, *folder_images]


def test_remove_selected(dialog, tmp_path):
    images = [make_image(tmp_path / f"{i}.png") for i in range(3)]
    dialog.add_paths(images)

    dialog.file_list.item(1).setSelected(True)
    dialog.remove_button.click()

    assert dialog.sources() == [images[0], images[2]]


def test_start_needs_files_and_out_dir(dialog, tmp_path, monkeypatch):
    dialog.add_paths([make_image(tmp_path / "a.png")])
    assert not dialog.start_button.isEnabled()

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path / "out")
    )
    dialog.choose_out_dir_button.click()

    assert dialog.out_dir() == tmp_path / "out"
    assert dialog.out_dir_label.text() == str(tmp_path / "out")
    assert dialog.start_button.isEnabled()


def test_options(dialog):
    save = SaveOptions(quality=70)
    assert dialog.options(save).look == CURRENT
    assert dialog.options(save).long_side == 1200
    assert dialog.options(save).save == save

    dialog.look_combo.setCurrentIndex(1)
    dialog.resize_check.setChecked(False)

    options = dialog.options(save)
    assert options.look == SEPIA
    assert options.long_side is None
    assert not dialog.long_side_spin.isEnabled()


def test_cancel_button_rejects(dialog, qtbot):
    cancel = [b for b in dialog.buttons.buttons() if b.text() == "キャンセル"][0]
    with qtbot.waitSignal(dialog.rejected):
        cancel.click()
