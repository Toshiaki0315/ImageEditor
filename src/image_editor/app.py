"""QApplication の生成と起動。"""

import sys
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType

from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtGui import QFileOpenEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from image_editor import __version__
from image_editor.core.io import load_image
from image_editor.ui.main_window import WINDOW_TITLE, MainWindow

ORGANIZATION_DOMAIN = "io.github.toshiaki0315"
LOG_DIR = Path.home() / "Library" / "Logs" / "ImageEditor"
LOG_FILE = LOG_DIR / "image_editor.log"
# 起動してすぐ終了する（ビルドした .app の起動確認用）
SMOKE_TEST_OPTION = "--smoke-test"


class ImageEditorApplication(QApplication):
    """Finder・Dock からの「ファイルを開く」要求 (QFileOpenEvent) を受け取れる QApplication。

    ウィンドウの準備前に届いた要求は、ハンドラが設定されるまで保持する。
    """

    def __init__(self, argv: Sequence[str]) -> None:
        super().__init__(list(argv))
        self._file_open_handler: Callable[[Path], object] | None = None
        self._pending_files: list[Path] = []

    def set_file_open_handler(self, handler: Callable[[Path], object]) -> None:
        """ファイルを開く要求の処理先を設定し、それまでに届いた要求を渡す。"""
        self._file_open_handler = handler
        pending, self._pending_files = self._pending_files, []
        for path in pending:
            handler(path)

    def request_open(self, path: Path) -> None:
        """ファイルを開く要求を処理先に渡す。処理先がまだなければ保持する。"""
        if self._file_open_handler is None:
            self._pending_files.append(path)
        else:
            self._file_open_handler(path)

    def event(self, event: QEvent | None) -> bool:
        if isinstance(event, QFileOpenEvent) and event.file():
            self.request_open(Path(event.file()))
            return True
        return super().event(event)


def create_window() -> MainWindow:
    """メインウィンドウを生成する。"""
    return MainWindow()


def can_load(path: Path) -> bool:
    """画像として読み込めるかを返す（ダイアログは出さない）。"""
    try:
        load_image(path)
    except Exception:  # 読めない理由は問わない（起動確認で失敗にするだけ）
        return False
    return True


def files_from_argv(argv: Sequence[str]) -> list[Path]:
    """コマンドライン引数から開くファイルを取り出す（プログラム名と `-` 始まりの引数は除く）。"""
    return [Path(arg) for arg in argv[1:] if not arg.startswith("-")]


def install_excepthook(log_file: Path = LOG_FILE) -> None:
    """未処理例外でアプリを終了させず、ログに書いてダイアログで通知する (NFR-04)。

    PyQt6 はスロット内の未処理例外で既定ではプロセスを終了するため、その代わりになる。
    """

    def handle(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(text)
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                "予期しないエラー",
                f"予期しないエラーが発生しました。\n{exc_type.__name__}: {exc}\n\n"
                f"詳細はログを参照してください:\n{log_file}",
            )

    sys.excepthook = handle


def main(argv: Sequence[str] | None = None) -> int:
    """アプリを起動し、終了コードを返す。"""
    argv = list(sys.argv if argv is None else argv)
    install_excepthook()
    app = ImageEditorApplication(argv)
    app.setApplicationName(WINDOW_TITLE)
    app.setApplicationDisplayName(WINDOW_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationDomain(ORGANIZATION_DOMAIN)

    window = create_window()
    window.show()

    # 引数で渡されたファイル（先頭の 1 枚）と、起動前に Finder から要求されたファイルを開く
    files = files_from_argv(argv)
    if SMOKE_TEST_OPTION in argv:
        # 起動確認: 渡したファイルが読めなければ失敗にする（.app に形式の部品が入っているかの
        # 確認）。読めないときにエラーのダイアログで止まらないよう、画面に出す前に確かめる
        if files and not can_load(files[0]):
            return 1
        QTimer.singleShot(500, app.quit)
    if files:
        window.load_file(files[0])
    app.set_file_open_handler(window.load_file)
    return app.exec()
