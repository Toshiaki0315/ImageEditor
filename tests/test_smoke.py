from image_editor.app import create_window


def test_window_opens(qtbot):
    window = create_window()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "Image Editor"
