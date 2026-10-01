"""一括処理の設定ダイアログ（画像・かける加工・リサイズ・保存先を選ぶ）。"""

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from image_editor.core.batch import BatchOptions, collect_images
from image_editor.core.io import SUPPORTED_EXTENSIONS, SaveOptions
from image_editor.core.presets import Preset
from image_editor.core.transform import MAX_SIZE, MIN_SIZE

CURRENT_LOOK_TEXT = "今の加工"
NO_OUTPUT_TEXT = "（まだ選んでいません）"
ELIDED_LABEL_MIN_WIDTH = 80


class ElidedLabel(QLabel):
    """入りきらない文字を途中で「…」に省略して表示するラベル（text() は全体のまま）。

    長いパスでもダイアログの幅を広げない。
    """

    def sizeHint(self) -> QSize:
        """幅は文字の長さに合わせて広げない。"""
        return QSize(ELIDED_LABEL_MIN_WIDTH, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        """幅は文字の長さに合わせて広げない。"""
        return self.sizeHint()

    def displayed_text(self) -> str:
        """今の幅で実際に表示する（省略した）文字。"""
        rect = self.contentsRect()
        return self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideMiddle, rect.width()
        )

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(self.contentsRect(), align, self.displayed_text())


NOTE_TEXT = (
    "トリミング範囲と回転・反転はかけません（フレーム・円のときは各画像の中央をその比で"
    "切り抜きます）。元と同じ名前・形式で保存し、同じ名前があれば _edited を付けて"
    "上書きしません。JPEG 品質・EXIF は「保存の設定」に従います。"
)
OPEN_FILTER = "画像ファイル ({})".format(
    " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
)


class BatchDialog(QDialog):
    """一括処理の設定を選ぶダイアログ。「開始」で閉じたら options() などで設定を読む。"""

    def __init__(
        self,
        current_look: Preset,
        presets: list[Preset],
        long_side: int,
        resize: bool,
        sources: list[Path] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("まとめて処理")
        self._out_dir: Path | None = None

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.add_files_button = QPushButton("ファイルを追加…")
        self.add_folder_button = QPushButton("フォルダを追加…")
        self.remove_button = QPushButton("取り除く")
        file_buttons = QHBoxLayout()
        file_buttons.addWidget(self.add_files_button)
        file_buttons.addWidget(self.add_folder_button)
        file_buttons.addStretch(1)
        file_buttons.addWidget(self.remove_button)

        self.look_combo = QComboBox()
        self.look_combo.addItem(CURRENT_LOOK_TEXT, current_look)
        for preset in presets:
            self.look_combo.addItem(f"プリセット: {preset.name}", preset)

        self.resize_check = QCheckBox("長辺を")
        self.resize_check.setChecked(resize)
        self.long_side_spin = QSpinBox()
        self.long_side_spin.setRange(MIN_SIZE, MAX_SIZE)
        self.long_side_spin.setSuffix(" px")
        self.long_side_spin.setValue(min(max(long_side, MIN_SIZE), MAX_SIZE))
        resize_row = QHBoxLayout()
        resize_row.addWidget(self.resize_check)
        resize_row.addWidget(self.long_side_spin)
        resize_row.addWidget(QLabel("にする"))
        resize_row.addStretch(1)

        self.out_dir_label = ElidedLabel(NO_OUTPUT_TEXT)
        self.choose_out_dir_button = QPushButton("選ぶ…")
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_dir_label, 1)
        out_row.addWidget(self.choose_out_dir_button)

        note = QLabel(NOTE_TEXT)
        note.setWordWrap(True)

        form = QFormLayout()
        form.addRow("かける加工", self.look_combo)
        form.addRow("リサイズ", resize_row)
        form.addRow("保存先", out_row)

        self.buttons = QDialogButtonBox()
        self.start_button = self.buttons.addButton("開始", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton("キャンセル", QDialogButtonBox.ButtonRole.RejectRole)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("処理する画像"))
        layout.addWidget(self.file_list, 1)
        layout.addLayout(file_buttons)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        self.resize(560, 480)

        self.add_files_button.clicked.connect(self._choose_files)
        self.add_folder_button.clicked.connect(self._choose_folder)
        self.remove_button.clicked.connect(self._remove_selected)
        self.choose_out_dir_button.clicked.connect(self._choose_out_dir)
        self.resize_check.toggled.connect(self.long_side_spin.setEnabled)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.long_side_spin.setEnabled(resize)
        self.add_paths(sources or [])
        self._update_start_button()

    # --- 公開 API -------------------------------------------------------------

    def add_paths(self, paths: list[Path]) -> None:
        """ファイル・フォルダ（直下の画像）を一覧に加える。すでにあるものは加えない。"""
        existing = {_key(path) for path in self.sources()}
        for path in collect_images(paths):
            if _key(path) in existing:
                continue
            existing.add(_key(path))
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(str(path))
            self.file_list.addItem(item)
        self._update_start_button()

    def sources(self) -> list[Path]:
        """処理する画像の一覧を返す。"""
        return [
            self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.file_list.count())
        ]

    def set_out_dir(self, path: Path) -> None:
        """保存先のフォルダを設定する。"""
        self._out_dir = path
        self.out_dir_label.setText(str(path))
        self.out_dir_label.setToolTip(str(path))
        self._update_start_button()

    def out_dir(self) -> Path | None:
        """保存先のフォルダを返す（まだ選んでいなければ None）。"""
        return self._out_dir

    def options(self, save: SaveOptions) -> BatchOptions:
        """選んだ設定を返す。save は「保存の設定」（JPEG 品質・EXIF）。"""
        long_side = self.long_side_spin.value() if self.resize_check.isChecked() else None
        return BatchOptions(look=self.look_combo.currentData(), long_side=long_side, save=save)

    # --- 内部 -----------------------------------------------------------------

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "処理する画像を追加", "", OPEN_FILTER)
        self.add_paths([Path(p) for p in paths])

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "画像のあるフォルダを追加")
        if path:
            self.add_paths([Path(path)])

    def _choose_out_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "保存先のフォルダを選ぶ")
        if path:
            self.set_out_dir(Path(path))

    def _remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self._update_start_button()

    def _update_start_button(self) -> None:
        self.start_button.setEnabled(self.file_list.count() > 0 and self._out_dir is not None)


def _key(path: Path) -> str:
    """同じファイルかを比べるためのキー（macOS は大文字・小文字を区別しない）。"""
    return str(path.resolve()).casefold()
