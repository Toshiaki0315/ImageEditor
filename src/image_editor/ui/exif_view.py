"""設定パネルの「EXIF」タブの中身（EXIF・位置情報・MakerNote の一覧）。"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from image_editor.core.exif_info import ExifEntry, ExifGroup, ExifInfo

NO_EXIF_TEXT = "この画像には EXIF がありません"
MAP_BUTTON_TEXT = "マップで開く"
COPY_TEXT = "コピー"
# 項目名の列の幅の上限（それより長い項目名は省略し、ツールチップで全体を見せる）
LABEL_COLUMN_MAX = 230
# 最初は閉じておくグループ（項目が多く、あまり見ないもの）
COLLAPSED_GROUPS = frozenset({ExifGroup.INTEROP, ExifGroup.THUMBNAIL})
_ENTRY_ROLE = Qt.ItemDataRole.UserRole


class ExifView(QWidget):
    """EXIF の項目をグループごとに一覧にし、選んだ行のコピーと、撮影地をマップで開く操作を持つ。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info: ExifInfo | None = None

        self.summary_label = QLabel(NO_EXIF_TEXT)
        self.summary_label.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["項目", "値"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.tree)
        copy.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy.activated.connect(self.copy_selected)

        self.map_button = QPushButton(MAP_BUTTON_TEXT)
        self.map_button.setToolTip("撮影した場所を macOS のマップアプリで開きます")
        self.map_button.clicked.connect(self.open_map)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.map_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        self.set_info(None)

    # --- 公開 API -------------------------------------------------------------

    def set_info(self, info: ExifInfo | None) -> None:
        """表示する EXIF を設定する。None・空なら一覧を消す。"""
        self._info = info if info is not None and not info.is_empty() else None
        self.tree.clear()
        info = self._info
        if info is None:
            self.summary_label.setText(NO_EXIF_TEXT)
            self.map_button.setEnabled(False)
            return
        for group, entries in info.groups():
            title = group.value
            if group is ExifGroup.MAKERNOTE and info.maker_note:
                title = f"{title}（{info.maker_note}）"
            parent = QTreeWidgetItem(self.tree, [f"{title}  {len(entries)} 項目"])
            parent.setFirstColumnSpanned(True)
            for entry in entries:
                item = QTreeWidgetItem(parent, [entry.label, entry.value])
                item.setData(0, _ENTRY_ROLE, entry)
                item.setToolTip(0, entry.label)
                item.setToolTip(1, entry.value)
            parent.setExpanded(group not in COLLAPSED_GROUPS)
        self.tree.resizeColumnToContents(0)
        # 項目名が長すぎて値が見えなくならないよう、項目名の列の幅に上限を設ける
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0), LABEL_COLUMN_MAX))
        count = len(info.entries)
        maker = f"・MakerNote: {info.maker_note}" if info.maker_note else ""
        self.summary_label.setText(f"{count} 項目{maker}")
        self.map_button.setEnabled(info.gps is not None)

    def info(self) -> ExifInfo | None:
        """表示中の EXIF（なければ None）。"""
        return self._info

    def selected_text(self) -> str:
        """選んだ行を「項目: 値」の行にした文字列（グループを選んだら、その中の全項目）。"""
        lines: list[str] = []
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            if group is None:
                continue
            whole = group.isSelected()
            for j in range(group.childCount()):
                child = group.child(j)
                if child is None or not (whole or child.isSelected()):
                    continue
                entry = child.data(0, _ENTRY_ROLE)
                if isinstance(entry, ExifEntry):
                    lines.append(f"{entry.label}: {entry.value}")
        return "\n".join(lines)

    def copy_selected(self) -> None:
        """選んだ行をクリップボードにコピーする。"""
        text = self.selected_text()
        clipboard = QApplication.clipboard()
        if text and clipboard is not None:
            clipboard.setText(text)

    def open_map(self) -> None:
        """撮影した場所を macOS のマップアプリで開く（ボタンを押したときだけ）。"""
        if self._info is not None and self._info.gps is not None:
            QDesktopServices.openUrl(QUrl(self._info.gps.map_url()))

    # --- 内部 -----------------------------------------------------------------

    def _show_context_menu(self, position: QPoint) -> None:
        if not self.tree.selectedItems():
            return
        menu = QMenu(self)
        menu.addAction(COPY_TEXT, self.copy_selected)
        menu.exec(self.tree.viewport().mapToGlobal(position))
