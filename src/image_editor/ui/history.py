"""アンドゥ／リドゥの履歴（Qt に依存しない）。"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_LIMIT = 100


class History(Generic[T]):
    """状態のスナップショットを積む履歴。

    current() が今の状態で、undo() で 1 つ前、redo() で 1 つ先の状態に移る。
    新しい状態を push() すると、やり直せる先の状態は捨てる。古い状態は limit 件まで残す。
    """

    def __init__(self, initial: T, limit: int = DEFAULT_LIMIT) -> None:
        if limit < 1:
            raise ValueError(f"limit は 1 以上で指定してください: {limit}")
        self._limit = limit
        self._undo: list[T] = []
        self._current = initial
        self._redo: list[T] = []

    def current(self) -> T:
        """今の状態を返す。"""
        return self._current

    def push(self, state: T) -> bool:
        """新しい状態を積む。今の状態と同じなら何もせず False を返す。"""
        if state == self._current:
            return False
        self._undo.append(self._current)
        if len(self._undo) > self._limit:
            del self._undo[0]
        self._current = state
        self._redo.clear()
        return True

    def can_undo(self) -> bool:
        """元に戻せるかを返す。"""
        return bool(self._undo)

    def can_redo(self) -> bool:
        """やり直せるかを返す。"""
        return bool(self._redo)

    def undo(self) -> T:
        """1 つ前の状態に戻って、その状態を返す。戻せなければ今の状態を返す。"""
        if self._undo:
            self._redo.append(self._current)
            self._current = self._undo.pop()
        return self._current

    def redo(self) -> T:
        """1 つ先の状態に進んで、その状態を返す。進めなければ今の状態を返す。"""
        if self._redo:
            self._undo.append(self._current)
            self._current = self._redo.pop()
        return self._current

    def reset(self, initial: T) -> None:
        """履歴を消して、initial を今の状態にする。"""
        self._undo.clear()
        self._redo.clear()
        self._current = initial
