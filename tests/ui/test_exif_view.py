from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication

from image_editor.core.exif_info import ExifEntry, ExifGroup, ExifInfo, GpsPosition
from image_editor.ui.exif_view import NO_EXIF_TEXT, ExifView

INFO = ExifInfo(
    (
        ExifEntry(ExifGroup.IMAGE, "Make", "Canon"),
        ExifEntry(ExifGroup.IMAGE, "Model", "Canon EOS R5"),
        ExifEntry(ExifGroup.EXIF, "ExposureTime", "1/125"),
        ExifEntry(ExifGroup.GPS, "GPSLatitude", "35° 39′ 21.87″ N（35.656075）"),
        ExifEntry(ExifGroup.MAKERNOTE, "Tag 0x7777", "5"),
        ExifEntry(ExifGroup.THUMBNAIL, "Compression", "JPEG (old-style)"),
    ),
    maker_note="Canon",
    gps=GpsPosition(35.656075, 139.758333),
)


def make_view(qtbot) -> ExifView:
    view = ExifView()
    qtbot.addWidget(view)
    view.resize(400, 500)
    return view


def group_titles(view: ExifView) -> list[str]:
    tree = view.tree
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_shows_groups_and_labels(qtbot):
    view = make_view(qtbot)
    view.set_info(INFO)

    assert group_titles(view) == [
        "画像  2 項目",
        "撮影  1 項目",
        "位置情報 (GPS)  1 項目",
        "MakerNote（Canon）  1 項目",
        "サムネイル  1 項目",
    ]
    image = view.tree.topLevelItem(0)
    assert image.child(0).text(0) == "Make（メーカー）"
    assert image.child(0).text(1) == "Canon"
    assert view.tree.topLevelItem(3).child(0).text(0) == "Tag 0x7777"
    assert image.isExpanded()
    assert not view.tree.topLevelItem(4).isExpanded()  # サムネイルは閉じておく
    assert "6 項目" in view.summary_label.text()
    assert "MakerNote: Canon" in view.summary_label.text()


def test_empty_info(qtbot):
    view = make_view(qtbot)
    view.set_info(INFO)
    view.set_info(ExifInfo())
    assert view.info() is None
    assert view.tree.topLevelItemCount() == 0
    assert view.summary_label.text() == NO_EXIF_TEXT
    assert not view.map_button.isEnabled()


def test_copy_selected_rows(qtbot):
    view = make_view(qtbot)
    view.set_info(INFO)
    image = view.tree.topLevelItem(0)
    image.child(1).setSelected(True)
    view.tree.topLevelItem(1).child(0).setSelected(True)

    view.copy_selected()

    assert QApplication.clipboard().text() == (
        "Model（機種）: Canon EOS R5\nExposureTime（露出時間）: 1/125"
    )


def test_copy_whole_group(qtbot):
    view = make_view(qtbot)
    view.set_info(INFO)
    group = view.tree.topLevelItem(0)
    group.setSelected(True)
    group.child(0).setSelected(True)  # グループと中の行を両方選んでも重ねない

    assert view.selected_text() == "Make（メーカー）: Canon\nModel（機種）: Canon EOS R5"


def test_map_button_opens_maps(qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    view = make_view(qtbot)
    view.set_info(INFO)
    assert view.map_button.isEnabled()

    view.map_button.click()

    assert opened == ["maps://?ll=35.656075,139.758333&q=35.656075,139.758333"]


def test_map_button_disabled_without_gps(qtbot):
    view = make_view(qtbot)
    view.set_info(ExifInfo((ExifEntry(ExifGroup.IMAGE, "Make", "Canon"),)))
    assert not view.map_button.isEnabled()
