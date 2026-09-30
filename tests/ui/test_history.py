import subprocess
import sys

import pytest

from image_editor.ui.history import History


def test_initial_state():
    history = History("a")
    assert history.current() == "a"
    assert not history.can_undo()
    assert not history.can_redo()


def test_undo_redo():
    history = History("a")
    history.push("b")
    history.push("c")

    assert history.undo() == "b"
    assert history.undo() == "a"
    assert not history.can_undo()
    assert history.undo() == "a"  # それ以上は戻らない

    assert history.redo() == "b"
    assert history.redo() == "c"
    assert not history.can_redo()
    assert history.redo() == "c"


def test_push_same_state_is_ignored():
    history = History("a")
    assert not history.push("a")
    assert not history.can_undo()
    assert history.push("b")


def test_push_clears_redo():
    history = History("a")
    history.push("b")
    history.undo()

    history.push("c")

    assert not history.can_redo()
    assert history.undo() == "a"


def test_limit_drops_oldest():
    history = History(0, limit=3)
    for value in range(1, 6):
        history.push(value)

    assert [history.undo() for _ in range(3)] == [4, 3, 2]
    assert not history.can_undo()


def test_invalid_limit():
    with pytest.raises(ValueError):
        History("a", limit=0)


def test_reset():
    history = History("a")
    history.push("b")
    history.undo()

    history.reset("z")

    assert history.current() == "z"
    assert not history.can_undo()
    assert not history.can_redo()


def test_history_does_not_import_qt():
    code = (
        "import sys, image_editor.ui.history; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
