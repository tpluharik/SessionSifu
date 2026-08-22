"""Qt desktop manager and system-tray interface shared by portable builds."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
from .hotkey import RecallHotkey, SHORTCUT_LABEL
from .shortcut import DEFAULT_SHORTCUT, normalize_shortcut

INTERVALS = [30, 60, 300, 600, 900, 1800]
RECALL_INTERVALS = [60, 300, 900, 1800]
RECALL_RETENTION_HOURS = [1, 6, 24, 72, 168]


def icon_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "app" / "org.gnome.SessionSifu.svg"


def recall_saving_icon() -> QIcon:
    """Add a high-contrast recording badge without another bundled asset."""
    pixmap = QIcon(str(icon_path())).pixmap(64, 64)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e85d75"))
    painter.drawEllipse(40, 2, 22, 22)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(47, 9, 8, 8)
    painter.end()
    return QIcon(pixmap)


def qt_shortcut(shortcut: str) -> QKeySequence:
    """Translate the portable Super spelling to Qt's Meta spelling."""

    return QKeySequence(shortcut.replace("Super", "Meta"))


class MainWindow(QMainWindow):
    def __init__(self, controller: SessionController) -> None:
        super().__init__()
        self.controller = controller
        self.settings = QSettings("SessionSifu", "SessionSifu")
        self.setWindowTitle(f"SessionSifu {VERSION}")
        self.setWindowIcon(QIcon(str(icon_path())))
        self.resize(760, 560)
        self._recall_state_callback = None
        self._recall_saving = False

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

        recall_box = QWidget()
        recall_layout = QVBoxLayout(recall_box)
        self.recall_enabled = QCheckBox("Enable experimental Privacy Recall")
        self.recall_enabled.setToolTip(
            "Disabled by default. Records searchable app/window metadata locally; no screenshots are taken."
        )
        self.recall_enabled.setChecked(
            self.settings.value("recall_enabled", False, type=bool)
        )
        self.recall_enabled.toggled.connect(self.toggle_recall)
        recall_layout.addWidget(self.recall_enabled)
        recall_notice = QLabel(
            "Off by default · metadata only · local storage · no network upload. "
            "Window titles can still contain sensitive information."
        )
        recall_notice.setWordWrap(True)
        recall_layout.addWidget(recall_notice)

        recall_form = QFormLayout()
        self.recall_interval = QComboBox()
        for seconds in RECALL_INTERVALS:
            self.recall_interval.addItem(
                f"{seconds // 60} minute(s)", seconds
            )
        configured_recall_interval = int(self.settings.value("recall_interval", 300))
        self.recall_interval.setCurrentIndex(
            max(0, self.recall_interval.findData(configured_recall_interval))
        )
        self.recall_interval.currentIndexChanged.connect(self.update_recall_timer)
        recall_form.addRow("Capture interval", self.recall_interval)

        self.recall_retention = QComboBox()
        for hours in RECALL_RETENTION_HOURS:
            label = f"{hours} hour(s)" if hours < 24 else f"{hours // 24} day(s)"
            self.recall_retention.addItem(label, hours)
        configured_retention = int(self.settings.value("recall_retention_hours", 24))
        self.recall_retention.setCurrentIndex(
            max(0, self.recall_retention.findData(configured_retention))
        )
        self.recall_retention.currentIndexChanged.connect(self.recall_settings_changed)
        recall_form.addRow("Retention", self.recall_retention)

        self.recall_exclusions = QLineEdit()
        self.recall_exclusions.setPlaceholderText("private-browser, password-manager")
        self.recall_exclusions.setText(str(self.settings.value("recall_excluded_apps", "")))
        self.recall_exclusions.editingFinished.connect(self.recall_settings_changed)
        recall_form.addRow("Excluded apps", self.recall_exclusions)
        recall_layout.addLayout(recall_form)

        self.recall_shortcut = QCheckBox(
            "Enable global Recall search shortcut"
        )
        self.recall_shortcut.setChecked(
            self.settings.value("recall_shortcut_enabled", True, type=bool)
        )
        self.recall_shortcut.toggled.connect(self.toggle_recall_shortcut)
        recall_layout.addWidget(self.recall_shortcut)
        self.recall_shortcut_value = QLineEdit()
        self.recall_shortcut_value.setPlaceholderText(DEFAULT_SHORTCUT)
        stored_shortcut = str(
            self.settings.value("recall_shortcut", DEFAULT_SHORTCUT)
        )
        try:
            stored_shortcut = normalize_shortcut(stored_shortcut)
        except ValueError:
            stored_shortcut = DEFAULT_SHORTCUT
        self.recall_shortcut_value.setText(stored_shortcut)
        self.recall_shortcut_value.editingFinished.connect(self.recall_shortcut_changed)
        recall_form.addRow("Search shortcut", self.recall_shortcut_value)

        self.recall_files = QCheckBox("Include full paths of open files")
        self.recall_files.setChecked(
            self.settings.value("recall_include_file_paths", False, type=bool)
        )
        self.recall_files.toggled.connect(self.recall_settings_changed)
        recall_layout.addWidget(self.recall_files)

        recall_controls = QHBoxLayout()
        self.recall_capture = QPushButton("Capture now")
        self.recall_capture.clicked.connect(self.save_recall)
        self.recall_search = QLineEdit()
        self.recall_search.setPlaceholderText("Search apps, window titles or opted-in file paths")
        self.recall_search.returnPressed.connect(self.refresh_recall)
        search_recall = QPushButton("Search")
        search_recall.clicked.connect(self.refresh_recall)
        recall_controls.addWidget(self.recall_capture)
        recall_controls.addWidget(self.recall_search, 1)
        recall_controls.addWidget(search_recall)
        recall_layout.addLayout(recall_controls)

        self.recall_results = QListWidget()
        recall_layout.addWidget(self.recall_results, 1)
        clear_recall = QPushButton("Delete all Recall history")
        clear_recall.clicked.connect(self.clear_recall)
        recall_layout.addWidget(clear_recall)

        tabs = QTabWidget()
        self.named = QListWidget()
        self.history = QListWidget()
        tabs.addTab(self._list_page(self.named, self.restore_named, self.delete_named), "Named sessions")
        tabs.addTab(self._list_page(self.history, self.restore_history), "History (latest five)")
        tabs.addTab(recall_box, "Privacy Recall")
        layout.addWidget(tabs, 1)

        diagnostics = QPushButton("Show platform diagnostics")
        diagnostics.clicked.connect(self.show_diagnostics)
        layout.addWidget(diagnostics)
        self.setCentralWidget(root)

        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.save_history(silent=True))
        self.update_interval()
        self.recall_timer = QTimer(self)
        self.recall_timer.timeout.connect(lambda: self.save_recall(silent=True))
        self.update_recall_timer()
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

    def _excluded_apps(self) -> list[str]:
        return [
            value.strip()
            for value in self.recall_exclusions.text().split(",")
            if value.strip()
        ]

    def recall_settings_changed(self, *_args) -> None:
        self.settings.setValue("recall_retention_hours", int(self.recall_retention.currentData()))
        self.settings.setValue("recall_excluded_apps", self.recall_exclusions.text().strip())
        self.settings.setValue("recall_include_file_paths", self.recall_files.isChecked())

    def toggle_recall_shortcut(self, enabled: bool) -> None:
        self.settings.setValue("recall_shortcut_enabled", enabled)
        self.recall_shortcut_value.setEnabled(enabled)
        if self._recall_state_callback is not None:
            self._notify_recall_state()

    def shortcut_value(self) -> str:
        return normalize_shortcut(self.recall_shortcut_value.text())

    def recall_shortcut_changed(self) -> None:
        try:
            shortcut = self.shortcut_value()
        except ValueError as error:
            self.status.setText(f"Invalid Recall shortcut: {error}")
            self.recall_shortcut_value.setText(
                str(self.settings.value("recall_shortcut", DEFAULT_SHORTCUT))
            )
            return
        self.recall_shortcut_value.setText(shortcut)
        self.settings.setValue("recall_shortcut", shortcut)
        self.status.setText(f"Recall search shortcut changed to {shortcut}.")
        self._notify_recall_state()

    def _notify_recall_state(self) -> None:
        if self._recall_state_callback is not None:
            self._recall_state_callback(
                self.recall_enabled.isChecked(),
                self.recall_shortcut.isChecked(),
                self.shortcut_value(),
                self._recall_saving,
            )

    def toggle_recall(self, enabled: bool) -> None:
        self.settings.setValue("recall_enabled", enabled)
        self.update_recall_timer()
        self.status.setText(
            "Privacy Recall is active; sanitized metadata will be recorded locally."
            if enabled
            else "Privacy Recall is paused. No activity metadata is being recorded."
        )
        if self._recall_state_callback is not None:
            self._notify_recall_state()

    def update_recall_timer(self, *_args) -> None:
        seconds = int(self.recall_interval.currentData())
        self.settings.setValue("recall_interval", seconds)
        enabled = self.recall_enabled.isChecked()
        self.recall_interval.setEnabled(enabled)
        self.recall_retention.setEnabled(enabled)
        self.recall_exclusions.setEnabled(enabled)
        self.recall_files.setEnabled(enabled)
        self.recall_capture.setEnabled(enabled)
        self.recall_shortcut.setEnabled(True)
        self.recall_shortcut_value.setEnabled(self.recall_shortcut.isChecked())
        if enabled:
            self.recall_timer.start(seconds * 1000)
        else:
            self.recall_timer.stop()

    def save_recall(self, silent: bool = False) -> None:
        if not self.recall_enabled.isChecked():
            if not silent:
                self.status.setText("Enable Privacy Recall before capturing activity metadata.")
            return
        if self._recall_saving:
            return
        self.recall_settings_changed()
        self._recall_saving = True
        self._notify_recall_state()
        QApplication.processEvents()
        try:
            self._perform(
                lambda: self.controller.save_recall(
                    retention_hours=int(self.recall_retention.currentData()),
                    excluded_apps=self._excluded_apps(),
                    include_file_paths=self.recall_files.isChecked(),
                ),
                "Saved a private local Recall entry.",
                silent=silent,
            )
        finally:
            self._recall_saving = False
            self._notify_recall_state()
            QApplication.processEvents()

    def refresh_recall(self) -> None:
        self.recall_results.clear()
        for entry in self.controller.search_recall(
            self.recall_search.text(), excluded_apps=self._excluded_apps()
        ):
            apps = ", ".join(entry.get("apps", [])[:4]) or "Unknown application"
            titles = " · ".join(entry.get("titles", [])[:3])
            label = f"{entry.get('captured_at', '')} — {apps}"
            if titles:
                label += f" — {titles}"
            self.recall_results.addItem(label)

    def clear_recall(self) -> None:
        answer = QMessageBox.question(
            self,
            "Delete Privacy Recall history?",
            "All locally recorded Recall entries will be permanently deleted.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            removed = self.controller.clear_recall()
            self.status.setText(f"Deleted {removed} Privacy Recall entries.")
            self.refresh_recall()

    def set_recall_state_callback(self, callback) -> None:
        self._recall_state_callback = callback
        self._notify_recall_state()

    def refresh(self) -> None:
        self.named.clear()
        for path in self.controller.named_sessions():
            self.named.addItem(path.stem)
            self.named.item(self.named.count() - 1).setData(Qt.UserRole, path.stem)
        self.history.clear()
        for path in self.controller.history():
            self.history.addItem(path.stem)
            self.history.item(self.history.count() - 1).setData(Qt.UserRole, str(path))
        self.refresh_recall()
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


class RecallSearchDialog(QDialog):
    """Small, independent search surface opened by the Recall shortcut."""

    def __init__(self, controller: SessionController, exclusions_provider) -> None:
        super().__init__()
        self.controller = controller
        self.exclusions_provider = exclusions_provider
        self.setWindowTitle("Search Privacy Recall")
        self.setWindowIcon(QIcon(str(icon_path())))
        self.resize(680, 420)
        layout = QVBoxLayout(self)
        title = QLabel("<h2>Search Privacy Recall</h2>")
        title.setTextFormat(Qt.RichText)
        layout.addWidget(title)
        self.notice = QLabel(
            "Excluded applications are redacted from these results, including older entries."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Application, window title or opted-in file path")
        self.query.returnPressed.connect(self.refresh)
        search = QPushButton("Search")
        search.clicked.connect(self.refresh)
        row.addWidget(self.query, 1)
        row.addWidget(search)
        layout.addLayout(row)
        self.results = QListWidget()
        layout.addWidget(self.results, 1)
        self.local_shortcut = QShortcut(QKeySequence(SHORTCUT_LABEL), self)
        self.local_shortcut.activated.connect(self.focus_search)

    def set_shortcut(self, shortcut: str) -> None:
        self.local_shortcut.setKey(qt_shortcut(shortcut))

    def focus_search(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.query.setFocus()
        self.query.selectAll()

    def refresh(self) -> None:
        self.results.clear()
        entries = self.controller.search_recall(
            self.query.text(), excluded_apps=self.exclusions_provider()
        )
        for entry in entries:
            apps = ", ".join(entry.get("apps", [])[:4]) or "Unknown application"
            titles = " · ".join(entry.get("titles", [])[:3])
            label = f"{entry.get('captured_at', '')} — {apps}"
            if titles:
                label += f" — {titles}"
            self.results.addItem(label)
        self.notice.setText(
            f"{len(entries)} matching entries. Excluded applications are redacted from all results."
            if entries
            else "No matching non-excluded Recall entries."
        )


def run_gui(
    controller: SessionController | None = None, *, open_recall_search: bool = False
) -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("SessionSifu")
    app.setApplicationVersion(VERSION)
    app.setQuitOnLastWindowClosed(False)
    controller = controller or SessionController()
    window = MainWindow(controller)
    recall_search = RecallSearchDialog(controller, window._excluded_apps)

    def show_recall_search() -> None:
        recall_search.refresh()
        recall_search.focus_search()

    local_shortcut = QShortcut(qt_shortcut(window.shortcut_value()), window)
    local_shortcut.activated.connect(show_recall_search)
    native_hotkey = RecallHotkey(window.shortcut_value())
    native_hotkey.triggered.connect(show_recall_search)
    native_hotkey.status_changed.connect(window.status.setText)

    normal_tray_icon = QIcon(str(icon_path()))
    saving_tray_icon = recall_saving_icon()
    tray = QSystemTrayIcon(normal_tray_icon, app)
    menu = QMenu()
    show = QAction("Open SessionSifu", menu)
    show.triggered.connect(lambda: (window.show(), window.raise_(), window.activateWindow()))
    save = QAction("Save snapshot now", menu)
    save.triggered.connect(window.save_history)
    restore = QAction("Restore latest snapshot", menu)
    restore.triggered.connect(window.restore_latest)
    recall = QAction("Privacy Recall capture (experimental)", menu)
    recall.setCheckable(True)
    recall.toggled.connect(window.recall_enabled.setChecked)
    search_recall = QAction(
        f"Browse Recall snapshots… ({window.shortcut_value()})", menu
    )
    search_recall.triggered.connect(show_recall_search)

    def recall_state_changed(
        capture_enabled: bool, shortcut_enabled: bool, shortcut: str, saving: bool
    ) -> None:
        recall.setChecked(capture_enabled)
        recall.setText(
            "Privacy Recall: saving…"
            if saving
            else "Privacy Recall capture (experimental)"
        )
        tray.setIcon(saving_tray_icon if saving else normal_tray_icon)
        tray.setToolTip(
            f"SessionSifu {VERSION} · Saving Privacy Recall…"
            if saving
            else f"SessionSifu {VERSION} · Privacy Recall active"
            if capture_enabled
            else f"SessionSifu {VERSION}"
        )
        local_shortcut.setKey(qt_shortcut(shortcut))
        recall_search.set_shortcut(shortcut)
        search_recall.setText(f"Browse Recall snapshots… ({shortcut})")
        native_hotkey.set_shortcut(shortcut)
        if shortcut_enabled:
            native_hotkey.start()
        else:
            native_hotkey.stop()

    window.set_recall_state_callback(recall_state_changed)
    quit_action = QAction("Turn Off SessionSifu", menu)
    quit_action.triggered.connect(app.quit)
    menu.addActions([show, save, restore, recall, search_recall])
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.setToolTip(
        f"SessionSifu {VERSION} · Privacy Recall active"
        if window.recall_enabled.isChecked()
        else f"SessionSifu {VERSION}"
    )
    tray.activated.connect(
        lambda reason: show.trigger()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()
    app.aboutToQuit.connect(native_hotkey.stop)
    if open_recall_search:
        show_recall_search()
    else:
        window.show()
    return app.exec()
