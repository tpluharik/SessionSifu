"""Qt desktop manager and system-tray interface shared by portable builds."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import VERSION
from .controller import SessionController

INTERVALS = [30, 60, 300, 600, 900, 1800]


def icon_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "app" / "org.gnome.SessionSifu.svg"


class MainWindow(QMainWindow):
    def __init__(self, controller: SessionController) -> None:
        super().__init__()
        self.controller = controller
        self.settings = QSettings("SessionSifu", "SessionSifu")
        self.setWindowTitle(f"SessionSifu {VERSION}")
        self.setWindowIcon(QIcon(str(icon_path())))
        self.resize(760, 560)

        root = QWidget()
        layout = QVBoxLayout(root)
        heading = QLabel(f"<h1>SessionSifu</h1><p>{controller.adapter.desktop} session restoration</p>")
        heading.setTextFormat(Qt.RichText)
        layout.addWidget(heading)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        save_row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Session name")
        save = QPushButton("Save named session")
        save.clicked.connect(self.save_named)
        snapshot = QPushButton("Save snapshot now")
        snapshot.clicked.connect(self.save_history)
        save_row.addWidget(self.name, 1)
        save_row.addWidget(save)
        save_row.addWidget(snapshot)
        layout.addLayout(save_row)

        form = QFormLayout()
        self.interval = QComboBox()
        for seconds in INTERVALS:
            label = f"{seconds} seconds" if seconds < 60 else f"{seconds // 60} minute(s)"
            self.interval.addItem(label, seconds)
        selected = int(self.settings.value("snapshot_interval", 300))
        self.interval.setCurrentIndex(max(0, self.interval.findData(selected)))
        self.interval.currentIndexChanged.connect(self.update_interval)
        form.addRow("Automatic snapshot interval", self.interval)
        layout.addLayout(form)

        tabs = QTabWidget()
        self.named = QListWidget()
        self.history = QListWidget()
        tabs.addTab(self._list_page(self.named, self.restore_named, self.delete_named), "Named sessions")
        tabs.addTab(self._list_page(self.history, self.restore_history), "History (latest five)")
        layout.addWidget(tabs, 1)

        diagnostics = QPushButton("Show platform diagnostics")
        diagnostics.clicked.connect(self.show_diagnostics)
        layout.addWidget(diagnostics)
        self.setCentralWidget(root)

        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.save_history(silent=True))
        self.update_interval()
        self.refresh()

    def _list_page(self, widget: QListWidget, restore_callback, delete_callback=None) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(widget)
        row = QHBoxLayout()
        restore = QPushButton("Restore selected")
        restore.clicked.connect(restore_callback)
        row.addWidget(restore)
        if delete_callback:
            delete = QPushButton("Delete selected")
            delete.clicked.connect(delete_callback)
            row.addWidget(delete)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _perform(self, operation, success: str, silent: bool = False) -> object | None:
        try:
            result = operation()
            self.status.setText(success)
            self.refresh()
            return result
        except Exception as error:
            self.status.setText(str(error))
            if not silent:
                QMessageBox.warning(self, "SessionSifu", str(error))
            return None

    def save_named(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.status.setText("Enter a session name first.")
            return
        self._perform(lambda: self.controller.save_named(name), f"Saved session “{name}”.")

    def save_history(self, silent: bool = False) -> None:
        self._perform(self.controller.save_history, "Saved an automatic snapshot.", silent=silent)

    def restore_named(self) -> None:
        item = self.named.currentItem()
        if item:
            self._perform(lambda: self.controller.restore_named(item.data(Qt.UserRole)), "Restore started.")

    def restore_history(self) -> None:
        item = self.history.currentItem()
        if item:
            self._perform(lambda: self.controller.restore_path(Path(item.data(Qt.UserRole))), "Restore started.")

    def delete_named(self) -> None:
        item = self.named.currentItem()
        if item:
            self._perform(lambda: self.controller.store.delete_named(item.data(Qt.UserRole)), "Session deleted.")

    def restore_latest(self) -> None:
        history = self.controller.history()
        if history:
            self._perform(lambda: self.controller.restore_path(history[0]), "Latest snapshot restore started.")

    def update_interval(self) -> None:
        seconds = int(self.interval.currentData())
        self.settings.setValue("snapshot_interval", seconds)
        self.timer.start(seconds * 1000)

    def refresh(self) -> None:
        self.named.clear()
        for path in self.controller.named_sessions():
            self.named.addItem(path.stem)
            self.named.item(self.named.count() - 1).setData(Qt.UserRole, path.stem)
        self.history.clear()
        for path in self.controller.history():
            self.history.addItem(path.stem)
            self.history.item(self.history.count() - 1).setData(Qt.UserRole, str(path))
        capabilities = self.controller.adapter.capabilities
        self.status.setText(
            f"Backend: {self.controller.adapter.desktop} · "
            f"window geometry: {'yes' if capabilities.geometry else 'application-only fallback'}"
        )

    def show_diagnostics(self) -> None:
        QMessageBox.information(
            self,
            "SessionSifu platform diagnostics",
            json.dumps(self.controller.diagnostics(), indent=2),
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            event.accept()


def run_gui(controller: SessionController | None = None) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SessionSifu")
    app.setApplicationVersion(VERSION)
    app.setQuitOnLastWindowClosed(False)
    controller = controller or SessionController()
    window = MainWindow(controller)

    tray = QSystemTrayIcon(QIcon(str(icon_path())), app)
    menu = QMenu()
    show = QAction("Open SessionSifu", menu)
    show.triggered.connect(lambda: (window.show(), window.raise_(), window.activateWindow()))
    save = QAction("Save snapshot now", menu)
    save.triggered.connect(window.save_history)
    restore = QAction("Restore latest snapshot", menu)
    restore.triggered.connect(window.restore_latest)
    quit_action = QAction("Turn Off SessionSifu", menu)
    quit_action.triggered.connect(app.quit)
    menu.addActions([show, save, restore])
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.setToolTip(f"SessionSifu {VERSION}")
    tray.activated.connect(
        lambda reason: show.trigger()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()
    window.show()
    return app.exec()
