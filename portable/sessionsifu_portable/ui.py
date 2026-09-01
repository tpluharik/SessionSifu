"""Qt desktop manager and system-tray interface shared by portable builds."""

from __future__ import annotations

import json
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import (
    QByteArray, QBuffer, QEvent, QIODevice, QObject, QSettings, QSize,
    QTimer, Qt, QUrl, Signal,
)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
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
RECALL_QUOTA_MB = [128, 512, 1024, 2048, 4096]
RECALL_PREVIEW_PROFILES = {
    "storage": (960, 68),
    "readable": (1440, 74),
    "high": (1920, 80),
}
RECALL_PREVIEW_STORAGE_HINTS = {
    "storage": "Estimated 60–160 KiB/window",
    "readable": "Estimated 120–350 KiB/window",
    "high": "Estimated 220–650 KiB/window; watch the quota",
}


def recall_preview_profile(value: str) -> tuple[int, int]:
    return RECALL_PREVIEW_PROFILES.get(value, RECALL_PREVIEW_PROFILES["storage"])


def recall_entry_images(entry: dict) -> list[tuple[str, str]]:
    """List every encrypted application-window preview and its readable label."""
    images: list[tuple[str, str]] = []
    matched = entry.get("matched_window") if isinstance(entry.get("matched_window"), dict) else None
    windows = ([matched] if matched else []) + list(entry.get("windows", []))
    for window in windows:
        if not isinstance(window, dict) or not window.get("image"):
            continue
        pair = (
            str(window["image"]),
            str(window.get("title") or window.get("app_name") or window.get("app_id") or "Window"),
        )
        if pair[0] not in {value[0] for value in images}:
            images.append(pair)
    if entry.get("has_preview"):
        images.append(("", "Display overview"))
    return images


def recall_highlight_image_name(entry: dict) -> str | None:
    """Resolve the preview whose pixels match the result's OCR coordinates."""
    if "highlight_image" in entry:
        return str(entry.get("highlight_image") or "")
    matched = entry.get("matched_window")
    if isinstance(matched, dict) and matched.get("image"):
        return str(matched["image"])
    if str(entry.get("result_kind") or "") == "visual":
        return ""
    return None


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


def highlight_recall_pixmap(
    pixmap: QPixmap, boxes: list[dict], active_index: int = 0
) -> QPixmap:
    """Overlay matching normalized OCR word boxes on a Recall preview."""
    if pixmap.isNull() or not boxes:
        return pixmap
    highlighted = pixmap.copy()
    painter = QPainter(highlighted)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for box_index, box in enumerate(boxes[:64]):
        if not isinstance(box, dict):
            continue
        try:
            x = round(float(box["x"]) * highlighted.width() / 10000)
            y = round(float(box["y"]) * highlighted.height() / 10000)
            width = max(2, round(float(box["w"]) * highlighted.width() / 10000))
            height = max(2, round(float(box["h"]) * highlighted.height() / 10000))
        except (KeyError, TypeError, ValueError):
            continue
        active = box_index == active_index
        painter.setPen(QColor(255, 132, 0, 245 if active else 150))
        painter.setBrush(QColor(255, 199, 20, 120 if active else 55))
        painter.drawRect(x, y, width, height)
    painter.end()
    return highlighted


def recall_result_pixmap(controller: SessionController, entry: dict) -> QPixmap:
    """Prefer an encrypted window image and crop the desktop as fallback."""
    if not entry.get("has_preview"):
        return QPixmap()
    window = entry.get("matched_window")
    window_image = str(window.get("image") or "") if isinstance(window, dict) else ""
    preview = controller.recall_store.preview_bytes(
        str(entry.get("name", "")), image_name=window_image
    )
    exact_window_preview = bool(preview and window_image)
    if not preview:
        preview = controller.recall_store.preview_bytes(str(entry.get("name", "")))
    pixmap = QPixmap()
    if not preview or not pixmap.loadFromData(preview):
        return QPixmap()
    if exact_window_preview:
        return highlight_recall_pixmap(pixmap, entry.get("highlight_boxes", []))
    geometry = window.get("geometry", []) if isinstance(window, dict) else []
    screen = QApplication.primaryScreen()
    if len(geometry) != 4 or screen is None:
        return highlight_recall_pixmap(pixmap, entry.get("highlight_boxes", []))
    try:
        screen_geometry = screen.geometry()
        scale_x = pixmap.width() / max(1, screen_geometry.width())
        scale_y = pixmap.height() / max(1, screen_geometry.height())
        x = round((float(geometry[0]) - screen_geometry.x()) * scale_x)
        y = round((float(geometry[1]) - screen_geometry.y()) * scale_y)
        width = round(float(geometry[2]) * scale_x)
        height = round(float(geometry[3]) * scale_y)
        x = max(0, min(x, pixmap.width() - 1))
        y = max(0, min(y, pixmap.height() - 1))
        width = max(1, min(width, pixmap.width() - x))
        height = max(1, min(height, pixmap.height() - y))
        return highlight_recall_pixmap(
            pixmap.copy(x, y, width, height), entry.get("highlight_boxes", [])
        )
    except (TypeError, ValueError):
        return highlight_recall_pixmap(pixmap, entry.get("highlight_boxes", []))


class RestorePreviewDialog(QDialog):
    """Let people inspect and narrow a restore before applications are launched."""

    def __init__(self, plan: list[dict[str, object]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview session restoration")
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        heading = QLabel(
            "<h2>Choose what to restore</h2>"
            "<p>No application will be launched until you confirm this preview.</p>"
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.items = QListWidget()
        for application in plan:
            documents = list(application.get("documents", []))
            targets = list(application.get("targets", []))
            detail = []
            if documents:
                detail.append(f"{len(documents)} open file(s)")
            if targets:
                detail.append(f"{len(targets)} deep link(s)")
            label = (
                f"{application.get('application') or 'Application'} — "
                f"{application.get('windows', 0)} window(s)"
            )
            if detail:
                label += " · " + " · ".join(detail)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(application.get("identity") or ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip("\n".join([*documents, *targets])[:4000])
            self.items.addItem(item)
        layout.addWidget(self.items, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        restore_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        restore_button.setText("Restore selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_identities(self) -> set[str]:
        return {
            str(item.data(Qt.UserRole))
            for index in range(self.items.count())
            for item in (self.items.item(index),)
            if item.checkState() == Qt.CheckState.Checked and item.data(Qt.UserRole)
        }


class RecallCaptureBridge(QObject):
    """Move plain capture work across threads without moving Qt widgets."""

    prepared = Signal(object, object, str)
    completed = Signal(bool, str, bool)


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
        self._recall_capture_bridge = RecallCaptureBridge(self)
        self._recall_capture_bridge.prepared.connect(self._prepare_recall_visuals)
        self._recall_capture_bridge.completed.connect(self._finish_recall_capture)

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
        self.recall_enabled = QCheckBox("Enable Privacy Recall")
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
        self.recall_exclusions.editingFinished.connect(self.recall_privacy_exclusions_changed)
        recall_form.addRow("Excluded apps", self.recall_exclusions)

        self.recall_websites = QLineEdit()
        self.recall_websites.setPlaceholderText("bank.example, health.example")
        self.recall_websites.setText(str(self.settings.value("recall_excluded_websites", "")))
        self.recall_websites.editingFinished.connect(self.recall_privacy_exclusions_changed)
        recall_form.addRow("Excluded websites", self.recall_websites)

        self.recall_quota = QComboBox()
        for megabytes in RECALL_QUOTA_MB:
            label = f"{megabytes} MiB" if megabytes < 1024 else f"{megabytes // 1024} GiB"
            self.recall_quota.addItem(label, megabytes)
        configured_quota = int(self.settings.value("recall_quota_mb", 512))
        self.recall_quota.setCurrentIndex(max(0, self.recall_quota.findData(configured_quota)))
        self.recall_quota.currentIndexChanged.connect(self.recall_settings_changed)
        recall_form.addRow("Encrypted storage quota", self.recall_quota)
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

        self.recall_screenshots = QCheckBox("Capture compressed display previews")
        self.recall_screenshots.setChecked(
            self.settings.value("recall_screenshots", False, type=bool)
        )
        self.recall_screenshots.toggled.connect(self.recall_settings_changed)
        self.recall_screenshots.toggled.connect(self.update_recall_timer)
        recall_layout.addWidget(self.recall_screenshots)

        self.recall_preview_quality = QComboBox()
        for label, value in (
            ("Storage saver · 960 px", "storage"),
            ("Readable text · 1440 px", "readable"),
            ("High detail · 1920 px", "high"),
        ):
            self.recall_preview_quality.addItem(label, value)
        stored_quality = str(self.settings.value("recall_preview_quality", "storage"))
        quality_index = self.recall_preview_quality.findData(stored_quality)
        self.recall_preview_quality.setCurrentIndex(max(0, quality_index))
        self.recall_preview_quality.currentIndexChanged.connect(self.recall_settings_changed)
        recall_form.addRow("Screenshot detail", self.recall_preview_quality)
        self.recall_preview_hint = QLabel(
            RECALL_PREVIEW_STORAGE_HINTS.get(
                stored_quality, RECALL_PREVIEW_STORAGE_HINTS["storage"]
            )
        )
        recall_form.addRow("Storage estimate", self.recall_preview_hint)

        self.recall_ocr = QCheckBox("Index preview text with local OCR")
        self.recall_ocr.setChecked(self.settings.value("recall_ocr", False, type=bool))
        self.recall_ocr.toggled.connect(self.recall_settings_changed)
        recall_layout.addWidget(self.recall_ocr)

        self.recall_related = QCheckBox("Enable local related-match ranking")
        self.recall_related.setChecked(
            self.settings.value("recall_related_search", False, type=bool)
        )
        self.recall_related.toggled.connect(self.recall_settings_changed)
        recall_layout.addWidget(self.recall_related)
        self.recall_semantic_model = QLineEdit(str(
            self.settings.value("recall_semantic_model", "") or ""
        ))
        self.recall_semantic_model.setPlaceholderText("Optional local sentence-transformer model directory")
        self.recall_semantic_model.editingFinished.connect(self.recall_settings_changed)
        recall_form.addRow("Offline semantic model", self.recall_semantic_model)
        self.controller.configure_semantic_model(self.recall_semantic_model.text().strip())

        self.recall_sensitive = QCheckBox("Filter likely sensitive information")
        self.recall_sensitive.setChecked(
            self.settings.value("recall_sensitive_filter", True, type=bool)
        )
        self.recall_sensitive.toggled.connect(self.recall_settings_changed)
        recall_layout.addWidget(self.recall_sensitive)

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
        self.recall_results.setIconSize(QPixmap(240, 135).size())
        self.recall_results.itemDoubleClicked.connect(self.open_recall_item)
        recall_layout.addWidget(self.recall_results, 1)
        recall_item_actions = QHBoxLayout()
        open_recall = QPushButton("Reopen selected")
        open_recall.clicked.connect(self.open_recall_item)
        delete_selected = QPushButton("Delete selected")
        delete_selected.clicked.connect(self.delete_recall_item)
        delete_app = QPushButton("Delete selected application")
        delete_app.clicked.connect(self.delete_recall_app)
        delete_website = QPushButton("Delete selected website")
        delete_website.clicked.connect(self.delete_recall_website)
        recall_item_actions.addWidget(open_recall)
        recall_item_actions.addWidget(delete_selected)
        recall_item_actions.addWidget(delete_app)
        recall_item_actions.addWidget(delete_website)
        archive_export = QPushButton("Encrypted export")
        archive_export.clicked.connect(self.export_archive)
        archive_import = QPushButton("Encrypted import")
        archive_import.clicked.connect(self.import_archive)
        recall_item_actions.addWidget(archive_export)
        recall_item_actions.addWidget(archive_import)
        recall_layout.addLayout(recall_item_actions)
        clear_recall = QPushButton("Delete all Recall history")
        clear_recall.clicked.connect(self.clear_recall)
        recall_layout.addWidget(clear_recall)

        capsule_box = QWidget()
        capsule_layout = QVBoxLayout(capsule_box)
        capsule_notice = QLabel(
            "Workspace capsules keep an encrypted launch manifest. Profile capsules separate "
            "supported application data but are not a security sandbox; Flatpak and Windows "
            "Sandbox plans show their effective boundary before launch or export."
        )
        capsule_notice.setWordWrap(True)
        capsule_layout.addWidget(capsule_notice)
        capsule_form = QFormLayout()
        self.capsule_name = QLineEdit()
        self.capsule_name.setPlaceholderText("Research")
        capsule_form.addRow("Capsule name", self.capsule_name)
        self.capsule_backend = QComboBox()
        self.capsule_backend.addItem("Separate supported application profiles", "profile")
        self.capsule_backend.addItem("Flatpak application sandbox", "flatpak")
        self.capsule_backend.addItem("Windows Sandbox export", "windows-sandbox")
        capsule_form.addRow("Backend", self.capsule_backend)
        self.capsule_apps = QLineEdit()
        self.capsule_apps.setPlaceholderText("firefox, code · or org.mozilla.firefox for Flatpak")
        capsule_form.addRow("Applications", self.capsule_apps)
        self.capsule_folders = QLineEdit()
        self.capsule_folders.setPlaceholderText("Windows Sandbox read-only folders, separated by ;")
        capsule_form.addRow("Mapped folders", self.capsule_folders)
        self.capsule_offline = QCheckBox("Request offline networking")
        capsule_form.addRow("Network", self.capsule_offline)
        capsule_layout.addLayout(capsule_form)
        capsule_create = QPushButton("Save encrypted capsule")
        capsule_create.clicked.connect(self.create_capsule)
        capsule_layout.addWidget(capsule_create)
        self.capsule_items = QListWidget()
        capsule_layout.addWidget(self.capsule_items, 1)
        capsule_layout.addWidget(QLabel("Applications running from this SessionSifu capsule window"))
        self.capsule_running_items = QListWidget()
        self.capsule_running_items.setMinimumHeight(90)
        capsule_layout.addWidget(self.capsule_running_items)
        capsule_actions = QHBoxLayout()
        capsule_plan = QPushButton("Review preflight")
        capsule_plan.clicked.connect(self.preflight_capsule)
        capsule_launch = QPushButton("Launch")
        capsule_launch.clicked.connect(self.launch_capsule)
        capsule_export = QPushButton("Export .wsb")
        capsule_export.clicked.connect(self.export_windows_capsule)
        capsule_delete = QPushButton("Delete manifest")
        capsule_delete.clicked.connect(self.delete_capsule)
        capsule_delete_data = QPushButton("Delete profile data")
        capsule_delete_data.clicked.connect(self.delete_capsule_data)
        for button in (
            capsule_plan, capsule_launch, capsule_export, capsule_delete, capsule_delete_data
        ):
            capsule_actions.addWidget(button)
        capsule_layout.addLayout(capsule_actions)

        self.tabs = QTabWidget()
        self.named = QListWidget()
        self.history = QListWidget()
        self.tabs.addTab(self._list_page(self.named, self.restore_named, self.delete_named), "Named sessions")
        self.tabs.addTab(self._list_page(self.history, self.restore_history), "History (latest five)")
        self.tabs.addTab(recall_box, "Privacy Recall")
        self._capsule_tab_index = self.tabs.addTab(capsule_box, "Workspace capsules")
        layout.addWidget(self.tabs, 1)

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
        self.capsule_running_timer = QTimer(self)
        self.capsule_running_timer.setInterval(2000)
        self.capsule_running_timer.timeout.connect(self.refresh_running_capsules)
        self.capsule_running_timer.start()
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

    def create_capsule(self) -> None:
        name = self.capsule_name.text().strip()
        applications = [
            item.strip() for item in self.capsule_apps.text().split(",") if item.strip()
        ]
        folders = [
            item.strip() for item in self.capsule_folders.text().split(";") if item.strip()
        ]
        backend = str(self.capsule_backend.currentData())
        if not name:
            self.status.setText("Enter a capsule name first.")
            return
        self._perform(
            lambda: self.controller.create_capsule(
                name,
                backend,
                applications,
                offline=self.capsule_offline.isChecked(),
                mapped_folders=folders,
            ),
            f"Saved encrypted workspace capsule “{name}”. Review preflight before launch.",
        )

    def _selected_capsule(self) -> str:
        item = self.capsule_items.currentItem()
        return str(item.data(Qt.UserRole)) if item else ""

    def preflight_capsule(self) -> None:
        name = self._selected_capsule()
        if not name:
            self.status.setText("Select a workspace capsule first.")
            return
        try:
            plan = self.controller.preflight_capsule(name)
        except Exception as error:
            QMessageBox.warning(self, "Workspace capsule", str(error))
            return
        QMessageBox.information(
            self,
            f"Workspace capsule · {name}",
            json.dumps(plan, indent=2),
        )

    def launch_capsule(self) -> None:
        name = self._selected_capsule()
        if name:
            self._perform(
                lambda: self.controller.launch_capsule(name),
                f"Launched workspace capsule “{name}” after preflight.",
            )
            self.refresh_running_capsules()

    def show_capsules(self) -> None:
        """Present the capsule setup page and its live application monitor."""
        self.tabs.setCurrentIndex(self._capsule_tab_index)
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.capsule_name.setFocus()

    def refresh_running_capsules(self) -> None:
        self.capsule_running_items.clear()
        running = self.controller.capsules.list_running()
        if not running:
            self.capsule_running_items.addItem(
                "No capsule applications launched from this window are running."
            )
            return
        for application in running:
            self.capsule_running_items.addItem(
                f"{application['application']} — {application['capsule']} "
                f"({application['backend']}, PID {application['pid'] or 'managed'})"
            )

    def export_windows_capsule(self) -> None:
        name = self._selected_capsule()
        if not name:
            self.status.setText("Select a Windows Sandbox capsule first.")
            return
        destination, _filter = QFileDialog.getSaveFileName(
            self, "Export Windows Sandbox capsule", f"{name}.wsb", "Windows Sandbox (*.wsb)"
        )
        if destination:
            self._perform(
                lambda: self.controller.export_windows_capsule(name, Path(destination)),
                "Created a reviewable Windows Sandbox configuration.",
            )

    def delete_capsule(self) -> None:
        name = self._selected_capsule()
        if name:
            self._perform(
                lambda: self.controller.delete_capsule(name),
                "Deleted the encrypted capsule manifest.",
            )

    def delete_capsule_data(self) -> None:
        name = self._selected_capsule()
        if not name:
            self.status.setText("Select a workspace capsule first.")
            return
        answer = QMessageBox.question(
            self,
            "Delete workspace profile data?",
            "The capsule's separate browser/editor profile data will be permanently deleted.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._perform(
                lambda: self.controller.delete_capsule_data(name),
                "Deleted the capsule's separate profile data.",
            )

    def restore_named(self) -> None:
        item = self.named.currentItem()
        if item:
            name = str(item.data(Qt.UserRole))
            self._restore_with_preview(
                self.controller.plan_named(name),
                lambda selected: self.controller.restore_named_selection(name, selected),
            )

    def restore_history(self) -> None:
        item = self.history.currentItem()
        if item:
            path = Path(item.data(Qt.UserRole))
            self._restore_with_preview(
                self.controller.plan_path(path),
                lambda selected: self.controller.restore_path_selection(path, selected),
            )

    def delete_named(self) -> None:
        item = self.named.currentItem()
        if item:
            self._perform(lambda: self.controller.store.delete_named(item.data(Qt.UserRole)), "Session deleted.")

    def restore_latest(self) -> None:
        history = self.controller.history()
        if history:
            path = history[0]
            self._restore_with_preview(
                self.controller.plan_path(path),
                lambda selected: self.controller.restore_path_selection(path, selected),
            )

    def _restore_with_preview(self, plan, operation) -> None:
        if not plan:
            self.status.setText("This snapshot has no restorable applications.")
            return
        dialog = RestorePreviewDialog(plan, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.status.setText("Restore cancelled; no applications were launched.")
            return
        selected = dialog.selected_identities()
        if not selected:
            self.status.setText("Select at least one application to restore.")
            return
        self._perform(lambda: operation(selected), "Selected applications are being restored.")

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
        self.settings.setValue("recall_excluded_websites", self.recall_websites.text().strip())
        self.settings.setValue("recall_quota_mb", int(self.recall_quota.currentData()))
        self.settings.setValue("recall_include_file_paths", self.recall_files.isChecked())
        self.settings.setValue("recall_screenshots", self.recall_screenshots.isChecked())
        self.settings.setValue(
            "recall_preview_quality", self.recall_preview_quality.currentData()
        )
        self.recall_preview_hint.setText(RECALL_PREVIEW_STORAGE_HINTS.get(
            str(self.recall_preview_quality.currentData() or "storage"),
            RECALL_PREVIEW_STORAGE_HINTS["storage"],
        ))
        self.settings.setValue("recall_ocr", self.recall_ocr.isChecked())
        self.settings.setValue("recall_related_search", self.recall_related.isChecked())
        semantic_path = self.recall_semantic_model.text().strip()
        self.settings.setValue("recall_semantic_model", semantic_path)
        self.controller.configure_semantic_model(semantic_path)
        self.settings.setValue("recall_sensitive_filter", self.recall_sensitive.isChecked())

    def recall_privacy_exclusions_changed(self) -> None:
        self.recall_settings_changed()
        for value in self._excluded_apps():
            if value.casefold() != "sessionsifu":
                self.controller.delete_recall(app=value)
        for value in self.recall_websites.text().split(","):
            if value.strip():
                self.controller.delete_recall(website=value.strip().casefold().lstrip("."))

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
        self.recall_websites.setEnabled(enabled)
        self.recall_quota.setEnabled(enabled)
        self.recall_files.setEnabled(enabled)
        self.recall_screenshots.setEnabled(enabled)
        self.recall_preview_quality.setEnabled(enabled and self.recall_screenshots.isChecked())
        self.recall_ocr.setEnabled(enabled and self.recall_screenshots.isChecked())
        self.recall_related.setEnabled(enabled)
        self.recall_sensitive.setEnabled(enabled)
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
        paused_until = int(self.settings.value("recall_pause_until", 0))
        if paused_until < 0 or paused_until > int(time.time()):
            if not silent:
                self.status.setText("Privacy Recall capture is paused; existing history remains searchable.")
            return
        if paused_until > 0:
            self.settings.setValue("recall_pause_until", 0)
        if self._recall_saving:
            return
        self.recall_settings_changed()
        self._recall_saving = True
        self._notify_recall_state()
        request = {
            "retention_hours": int(self.recall_retention.currentData()),
            "excluded_apps": tuple(self._excluded_apps()),
            "excluded_websites": tuple(
                value.strip().casefold().lstrip(".")
                for value in self.recall_websites.text().split(",")
                if value.strip()
            ),
            "include_file_paths": self.recall_files.isChecked(),
            "ocr_enabled": self.recall_ocr.isChecked(),
            "sensitive_filter": self.recall_sensitive.isChecked(),
            "quota_mb": int(self.recall_quota.currentData()),
            "silent": bool(silent),
        }

        def prepare() -> None:
            try:
                session = self.controller.prepare_recall(
                    include_file_paths=request["include_file_paths"]
                )
                error = ""
            except Exception as caught:
                session = None
                error = str(caught)[:1024]
            self._recall_capture_bridge.prepared.emit(request, session, error)

        threading.Thread(
            target=prepare, name="sessionsifu-recall-prepare", daemon=True
        ).start()

    def _prepare_recall_visuals(self, request: object, session: object, error: str) -> None:
        request = request if isinstance(request, dict) else {}
        silent = bool(request.get("silent"))
        if error or session is None:
            self._recall_capture_bridge.completed.emit(
                False, error or "No desktop session was captured.", silent
            )
            return
        try:
            display, windows, diagnostics, edge, quality = self._capture_recall_images(session)
        except Exception as caught:
            self._recall_capture_bridge.completed.emit(False, str(caught)[:1024], silent)
            return

        def finalize() -> None:
            try:
                preview = self._jpeg_bytes(display, edge, quality) if display else None
                window_previews = {
                    index: encoded
                    for index, image in windows.items()
                    for encoded in [self._jpeg_bytes(image, edge, max(60, quality - 3))]
                    if encoded
                }
                diagnostics["captured_window_images"] = len(window_previews)
                diagnostics["missing_window_images"] = max(
                    0, int(diagnostics.get("expected_windows", 0)) - len(window_previews)
                )
                diagnostics["display_overview_captured"] = preview is not None
                session.capture_diagnostics.update(diagnostics)
                self.controller.save_prepared_recall(
                    session,
                    retention_hours=int(request["retention_hours"]),
                    excluded_apps=request["excluded_apps"],
                    excluded_websites=request["excluded_websites"],
                    include_file_paths=bool(request["include_file_paths"]),
                    preview=preview,
                    window_previews=window_previews,
                    ocr_enabled=bool(request["ocr_enabled"]),
                    sensitive_filter=bool(request["sensitive_filter"]),
                    quota_mb=int(request["quota_mb"]),
                )
                success, message = True, "Saved an encrypted private Recall entry."
            except Exception as caught:
                success, message = False, str(caught)[:1024]
            self._recall_capture_bridge.completed.emit(success, message, silent)

        threading.Thread(
            target=finalize, name="sessionsifu-recall-finalize", daemon=True
        ).start()

    def _finish_recall_capture(self, success: bool, message: str, silent: bool) -> None:
        self._recall_saving = False
        self._notify_recall_state()
        self.status.setText(message)
        if success:
            self.refresh()
        elif not silent:
            QMessageBox.warning(self, "SessionSifu", message)

    def pause_recall(self, seconds: int) -> None:
        if seconds < 0:
            until = -1
        elif seconds == 0:
            until = 0
        else:
            until = int(time.time()) + seconds
        self.settings.setValue("recall_pause_until", until)
        self.status.setText("Privacy Recall resumed." if until == 0 else "Privacy Recall capture paused.")

    def refresh_recall(self) -> None:
        self.recall_results.clear()
        for entry in self.controller.search_recall(
            self.recall_search.text(),
            excluded_apps=self._excluded_apps(),
            semantic=self.recall_related.isChecked(),
        ):
            apps = ", ".join(entry.get("apps", [])[:4]) or "Unknown application"
            titles = " · ".join(entry.get("titles", [])[:3])
            label = f"{entry.get('captured_at', '')} — {apps}"
            if titles:
                label += f" — {titles}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry)
            pixmap = recall_result_pixmap(self.controller, entry)
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap.scaled(240, 135, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
            self.recall_results.addItem(item)

    def _capture_recall_preview(self) -> bytes | None:
        if not self.recall_screenshots.isChecked():
            return None
        screen = QApplication.primaryScreen()
        if screen is None:
            return None
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            return None
        if max(pixmap.width(), pixmap.height()) > 1280:
            pixmap = pixmap.scaled(1280, 1280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "JPEG", 70)
        buffer.close()
        return bytes(data)

    @staticmethod
    def _jpeg_bytes(image: QImage | QPixmap, maximum_edge: int = 960, quality: int = 65) -> bytes | None:
        if image.isNull():
            return None
        if max(image.width(), image.height()) > maximum_edge:
            image = image.scaled(
                maximum_edge,
                maximum_edge,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        saved = image.save(buffer, "JPEG", quality)
        buffer.close()
        return bytes(data) if saved and 0 < len(data) <= 8 * 1024 * 1024 else None

    def _capture_recall_visuals(self, session) -> tuple[bytes | None, dict[int, bytes], dict]:
        """Synchronous compatibility wrapper used by non-GUI integrations."""
        display, windows, diagnostics, edge, quality = self._capture_recall_images(session)
        preview = self._jpeg_bytes(display, edge, quality) if display else None
        window_previews = {
            index: encoded
            for index, image in windows.items()
            for encoded in [self._jpeg_bytes(image, edge, max(60, quality - 3))]
            if encoded
        }
        diagnostics.update({
            "captured_window_images": len(window_previews),
            "missing_window_images": max(
                0, int(diagnostics.get("expected_windows", 0)) - len(window_previews)
            ),
            "display_overview_captured": preview is not None,
        })
        return preview, window_previews, diagnostics

    def _capture_recall_images(
        self, session
    ) -> tuple[QImage | None, dict[int, QImage], dict, int, int]:
        """Grab GUI-owned pixels; compression happens later in a worker."""
        if not self.recall_screenshots.isChecked():
            return None, {}, {
                "expected_windows": min(len(session.windows), 64),
                "captured_window_images": 0,
                "missing_window_images": min(len(session.windows), 64),
                "screenshots_enabled": False,
            }, 960, 68
        screens = []
        for screen in QApplication.screens():
            desktop = screen.grabWindow(0)
            if not desktop.isNull():
                screens.append((screen.geometry(), desktop.toImage(), screen))
        primary = QApplication.primaryScreen()
        primary_desktop = next(
            (desktop for _geometry, desktop, screen in screens if screen is primary),
            screens[0][1] if screens else QImage(),
        )
        preview_edge, jpeg_quality = recall_preview_profile(
            str(self.recall_preview_quality.currentData() or "storage")
        )
        window_images: dict[int, QImage] = {}
        for index, window in enumerate(session.windows[:64]):
            image = QImage()
            native_id = str(window.window_id or "")
            try:
                if ":" not in native_id:
                    handle = int(native_id, 0)
                    if handle:
                        screen = next(
                            (item[2] for item in screens if item[0].contains(
                                int(window.geometry[0] + window.geometry[2] / 2),
                                int(window.geometry[1] + window.geometry[3] / 2),
                            )),
                            QApplication.primaryScreen(),
                        )
                        if screen is not None:
                            image = screen.grabWindow(handle).toImage()
            except (TypeError, ValueError):
                pass
            if image.isNull() and not window.minimized:
                wx, wy, width, height = window.geometry
                for geometry, desktop, _screen in screens:
                    left = max(wx, geometry.x())
                    top = max(wy, geometry.y())
                    right = min(wx + width, geometry.x() + geometry.width())
                    bottom = min(wy + height, geometry.y() + geometry.height())
                    if right <= left or bottom <= top:
                        continue
                    scale_x = desktop.width() / max(1, geometry.width())
                    scale_y = desktop.height() / max(1, geometry.height())
                    image = desktop.copy(
                        round((left - geometry.x()) * scale_x),
                        round((top - geometry.y()) * scale_y),
                        max(1, round((right - left) * scale_x)),
                        max(1, round((bottom - top) * scale_y)),
                    )
                    break
            if not image.isNull():
                window_images[index] = image
        expected = min(len(session.windows), 64)
        return (primary_desktop if not primary_desktop.isNull() else None), window_images, {
            "expected_windows": expected,
            "captured_window_images": len(window_images),
            "missing_window_images": max(0, expected - len(window_images)),
            "screenshots_enabled": True,
            "display_overview_captured": not primary_desktop.isNull(),
        }, preview_edge, jpeg_quality

    def open_recall_item(self, *_args) -> None:
        item = self.recall_results.currentItem()
        entry = item.data(Qt.UserRole) if item else {}
        target = next(iter(entry.get("targets", [])), "") if isinstance(entry, dict) else ""
        if target:
            QDesktopServices.openUrl(QUrl(target))

    def delete_recall_item(self) -> None:
        item = self.recall_results.currentItem()
        entry = item.data(Qt.UserRole) if item else {}
        if isinstance(entry, dict) and entry.get("name"):
            self.controller.delete_recall(record=str(entry["name"]))
            self.refresh_recall()

    def delete_recall_app(self) -> None:
        item = self.recall_results.currentItem()
        entry = item.data(Qt.UserRole) if item else {}
        app = next(iter(entry.get("apps", [])), "") if isinstance(entry, dict) else ""
        if app:
            self.controller.delete_recall(app=app)
            self.refresh_recall()

    def delete_recall_website(self) -> None:
        item = self.recall_results.currentItem()
        entry = item.data(Qt.UserRole) if item else {}
        website = next(iter(entry.get("urls", [])), "") if isinstance(entry, dict) else ""
        if website:
            self.controller.delete_recall(website=website)
            self.refresh_recall()

    def export_archive(self) -> None:
        destination, _filter = QFileDialog.getSaveFileName(
            self, "Encrypted SessionSifu export", "SessionSifu.ssxa",
            "SessionSifu archive (*.ssxa)",
        )
        if not destination:
            return
        passphrase, accepted = QInputDialog.getText(
            self, "Protect export", "Passphrase (at least 12 characters):",
            QLineEdit.EchoMode.Password,
        )
        if accepted:
            self._perform(
                lambda: self.controller.export_archive(Path(destination), passphrase),
                "Encrypted export created.",
            )

    def import_archive(self) -> None:
        source, _filter = QFileDialog.getOpenFileName(
            self, "Import SessionSifu archive", "", "SessionSifu archive (*.ssxa)",
        )
        if not source:
            return
        passphrase, accepted = QInputDialog.getText(
            self, "Unlock import", "Archive passphrase:", QLineEdit.EchoMode.Password,
        )
        if accepted:
            self._perform(
                lambda: self.controller.import_archive(Path(source), passphrase),
                "Encrypted archive imported.",
            )
            self.refresh()

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
        self.capsule_items.clear()
        for capsule in self.controller.list_capsules():
            name = str(capsule.get("name") or "")
            backend = str(capsule.get("backend") or "")
            item = QListWidgetItem(f"{name} — {backend}")
            item.setData(Qt.UserRole, name)
            self.capsule_items.addItem(item)
        self.refresh_running_capsules()
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


class RecallSearchBridge(QObject):
    """Deliver worker results to Qt's GUI thread without polling."""

    completed = Signal(int, object, str)
    thumbnail = Signal(int, int, str, object)


class RecallSearchDialog(QDialog):
    """Large master-detail Recall browser shared by portable platforms."""

    def __init__(self, controller: SessionController, exclusions_provider) -> None:
        super().__init__()
        self.controller = controller
        self.exclusions_provider = exclusions_provider
        self.setWindowTitle("Search Privacy Recall")
        self.setWindowIcon(QIcon(str(icon_path())))
        self.settings = QSettings("SessionSifu", "SessionSifu")
        self.resize(1280, 800)
        self._detail_entry: dict = {}
        self._detail_images: list[tuple[str, str]] = []
        self._detail_position = 0
        self._detail_pixmap = QPixmap()
        self._detail_source_pixmap = QPixmap()
        self._zoom = 0.0
        self._pinch_start_zoom = 1.0
        self._match_position = 0
        self._search_generation = 0
        self._search_inflight = False
        self._pending_search: dict | None = None
        self._all_entries: list[dict] = []
        self._visible_count = 24
        self._search_bridge = RecallSearchBridge(self)
        self._search_bridge.completed.connect(self._finish_refresh)
        self._search_bridge.thumbnail.connect(self._finish_thumbnail)
        self._thumbnail_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="sessionsifu-thumbnail"
        )
        self._thumbnail_cache: OrderedDict[str, QImage] = OrderedDict()
        self.destroyed.connect(
            lambda: self._thumbnail_executor.shutdown(wait=False, cancel_futures=True)
        )
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
        self.query.setPlaceholderText("Application, window, file, website or text in a screenshot")
        self.query.returnPressed.connect(self.refresh)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh)
        self.query.textChanged.connect(lambda *_args: self.search_timer.start())
        self.app_filter = QComboBox()
        self.app_filter.addItem("All applications", "")
        self.app_filter.currentIndexChanged.connect(self.refresh)
        self.view_mode = QComboBox()
        self.view_mode.addItem("Visual", "visual")
        self.view_mode.addItem("Compact", "compact")
        stored_mode = str(self.settings.value("recall_search_view_mode", "visual"))
        self.view_mode.setCurrentIndex(max(0, self.view_mode.findData(stored_mode)))
        self.view_mode.currentIndexChanged.connect(self.change_view_mode)
        row.addWidget(self.query, 1)
        row.addWidget(self.app_filter)
        row.addWidget(self.view_mode)
        layout.addLayout(row)
        timeline_row = QHBoxLayout()
        self.group_scenes = QCheckBox("Group similar scenes")
        self.group_scenes.setChecked(True)
        self.group_scenes.toggled.connect(self.refresh)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.valueChanged.connect(self.select_timeline_position)
        timeline_row.addWidget(self.group_scenes)
        timeline_row.addWidget(QLabel("Older"))
        timeline_row.addWidget(self.timeline, 1)
        timeline_row.addWidget(QLabel("Newer"))
        layout.addLayout(timeline_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.results = QListWidget()
        self.results.setIconSize(QSize(240, 135))
        self.results.itemDoubleClicked.connect(self.open_selected)
        self.results.currentItemChanged.connect(self.show_selected)
        splitter.addWidget(self.results)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel("<h2>Select a saved moment</h2>")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        self.detail_meta = QLabel("Every captured application window will appear below.")
        self.detail_meta.setWordWrap(True)
        detail_layout.addWidget(self.detail_meta)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview = QLabel("Screenshot unavailable")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(640, 400)
        self.preview_scroll.setWidget(self.preview)
        self.preview_scroll.viewport().installEventFilter(self)
        self.preview_scroll.viewport().grabGesture(Qt.GestureType.PinchGesture)
        detail_layout.addWidget(self.preview_scroll, 1)
        self.preview_state = QLabel("Metadata-only saved moment")
        self.preview_state.setWordWrap(True)
        detail_layout.addWidget(self.preview_state)
        gesture_hint = QLabel(
            "Two-finger scroll to pan · pinch or Ctrl+scroll to zoom"
        )
        gesture_hint.setStyleSheet("color: palette(mid);")
        detail_layout.addWidget(gesture_hint)
        navigation = QHBoxLayout()
        previous = QPushButton("‹ Window")
        previous.clicked.connect(lambda: self.step_image(-1))
        following = QPushButton("Window ›")
        following.clicked.connect(lambda: self.step_image(1))
        previous_match = QPushButton("‹ Match")
        previous_match.clicked.connect(lambda: self.step_match(-1))
        next_match = QPushButton("Match ›")
        next_match.clicked.connect(lambda: self.step_match(1))
        self.match_counter = QLabel("No OCR match")
        fit = QPushButton("Fit")
        fit.clicked.connect(lambda: self.set_zoom(0.0))
        actual = QPushButton("100%")
        actual.clicked.connect(lambda: self.set_zoom(1.0))
        zoom_match = QPushButton("Zoom to match")
        zoom_match.clicked.connect(lambda: self.set_zoom(1.6))
        for widget in (
            previous, following, previous_match, next_match,
            self.match_counter, fit, actual, zoom_match,
        ):
            navigation.addWidget(widget)
        detail_layout.addLayout(navigation)
        self.filmstrip = QListWidget()
        self.filmstrip.setViewMode(QListView.ViewMode.IconMode)
        self.filmstrip.setFlow(QListView.Flow.LeftToRight)
        self.filmstrip.setWrapping(False)
        self.filmstrip.setIconSize(QSize(128, 72))
        self.filmstrip.setFixedHeight(120)
        self.filmstrip.currentRowChanged.connect(self.set_image)
        detail_layout.addWidget(self.filmstrip)
        splitter.addWidget(detail)
        splitter.setSizes([390, 890])
        layout.addWidget(splitter, 1)
        self.load_more = QPushButton("Load 24 more results")
        self.load_more.clicked.connect(self.load_more_results)
        self.load_more.hide()
        layout.addWidget(self.load_more)
        actions = QHBoxLayout()
        open_button = QPushButton("Reopen selected window")
        open_button.clicked.connect(self.open_selected)
        actions.addWidget(open_button)
        bookmark_button = QPushButton("Bookmark")
        bookmark_button.clicked.connect(self.bookmark_selected)
        collection_button = QPushButton("Collection / note")
        collection_button.clicked.connect(self.annotate_selected)
        reindex_button = QPushButton("Reindex OCR")
        reindex_button.clicked.connect(self.reindex_selected)
        diagnostics_button = QPushButton("OCR diagnostics")
        diagnostics_button.clicked.connect(self.show_ocr_diagnostics)
        ask_button = QPushButton("Ask history")
        ask_button.clicked.connect(self.ask_history)
        for widget in (bookmark_button, collection_button, reindex_button, diagnostics_button, ask_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.local_shortcut = QShortcut(QKeySequence(SHORTCUT_LABEL), self)
        self.local_shortcut.activated.connect(self.focus_search)
        for key, callback in (
            ("Left", lambda: self.step_image(-1)),
            ("Right", lambda: self.step_image(1)),
            ("+", lambda: self.set_zoom(min(3.0, max(1.0, self._zoom or 1.0) + 0.25))),
            ("-", lambda: self.set_zoom(max(0.5, (self._zoom or 1.0) - 0.25))),
            ("0", lambda: self.set_zoom(1.0)),
            ("Space", self.toggle_fullscreen),
            ("Return", self.open_selected),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)

    def change_view_mode(self) -> None:
        mode = str(self.view_mode.currentData() or "visual")
        self.settings.setValue("recall_search_view_mode", mode)
        self.results.setViewMode(
            QListView.ViewMode.IconMode if mode == "visual" else QListView.ViewMode.ListMode
        )
        self.results.setIconSize(QSize(240, 135) if mode == "visual" else QSize(96, 54))
        self._render_entries()

    def set_shortcut(self, shortcut: str) -> None:
        self.local_shortcut.setKey(qt_shortcut(shortcut))

    def focus_search(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.query.setFocus()
        self.query.selectAll()

    def refresh(self) -> None:
        self._search_generation += 1
        request = {
            "generation": self._search_generation,
            "query": self.query.text(),
            "excluded_apps": tuple(self.exclusions_provider()),
            "app": str(self.app_filter.currentData() or ""),
            "semantic": QSettings("SessionSifu", "SessionSifu").value(
                "recall_related_search", False, type=bool
            ),
            "group": self.group_scenes.isChecked(),
        }
        self._pending_search = request
        self.notice.setText("Searching encrypted local history…")
        if not self._search_inflight:
            self._start_pending_refresh()

    def _start_pending_refresh(self) -> None:
        request = self._pending_search
        if request is None:
            return
        self._pending_search = None
        self._search_inflight = True

        def worker() -> None:
            error = ""
            try:
                entries = self.controller.search_recall(
                    request["query"],
                    excluded_apps=request["excluded_apps"],
                    app=request["app"],
                    semantic=request["semantic"],
                )
                if request["group"] and not request["query"].strip() and not request["app"]:
                    entries = self.controller.recall_store.group_scenes(entries)
            except (OSError, RuntimeError, ValueError) as caught:
                entries = []
                error = str(caught)[:512]
            self._search_bridge.completed.emit(request["generation"], entries, error)

        threading.Thread(
            target=worker, name="sessionsifu-recall-search", daemon=True
        ).start()

    def _finish_refresh(self, generation: int, entries: object, error: str) -> None:
        self._search_inflight = False
        if generation == self._search_generation:
            safe_entries = entries if isinstance(entries, list) else []
            self._apply_entries(safe_entries)
            if error:
                self.notice.setText(f"Recall vault unavailable: {error}")
        if self._pending_search is not None:
            self._start_pending_refresh()

    def _apply_entries(self, entries: list[dict]) -> None:
        if self.app_filter.count() == 1:
            apps = sorted(
                {app for entry in entries for app in entry.get("apps", [])},
                key=str.casefold,
            )
            self.app_filter.blockSignals(True)
            for app in apps:
                self.app_filter.addItem(app, app)
            self.app_filter.blockSignals(False)
        self._all_entries = entries
        self._visible_count = 24
        self._render_entries()

    def _render_entries(self) -> None:
        self.results.clear()
        mode = str(self.view_mode.currentData() or "visual")
        visible_entries = self._all_entries[:self._visible_count]
        for row, entry in enumerate(visible_entries):
            apps = ", ".join(entry.get("apps", [])[:4]) or "Unknown application"
            titles = " · ".join(entry.get("titles", [])[:3])
            label = f"{apps} — {titles or 'Window moment'}\n{entry.get('captured_at', '')}"
            match_label = {
                "Window image text": "Found in this screenshot",
                "Visual text": "Found in a display screenshot",
                "Window text": "Found in the window title",
                "Window file": "Found in an open file",
                "Application": "Found in the application name",
                "Timeline": "Saved moment",
            }.get(str(entry.get("match_type", "")), "Matching saved moment")
            label += f" · {match_label}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry)
            if mode == "visual":
                key = self._thumbnail_key(entry)
                cached = self._thumbnail_cache.get(key)
                if cached is not None:
                    self._thumbnail_cache.move_to_end(key)
                    item.setIcon(QIcon(QPixmap.fromImage(cached)))
                else:
                    self._queue_thumbnail(self._search_generation, row, key, entry)
            self.results.addItem(item)
        self.notice.setText(
            f"{len(self._all_entries)} matching window moments. "
            f"Showing {len(visible_entries)}; excluded applications are redacted from all results."
            if self._all_entries
            else "No matching non-excluded Recall entries."
        )
        self.change_view_mode_without_refresh()
        self.load_more.setVisible(len(visible_entries) < len(self._all_entries))
        self.timeline.blockSignals(True)
        self.timeline.setRange(0, max(0, len(visible_entries) - 1))
        self.timeline.setValue(0)
        self.timeline.blockSignals(False)
        if self.results.count():
            self.results.setCurrentRow(0)

    @staticmethod
    def _thumbnail_key(entry: dict) -> str:
        return "\0".join((
            str(entry.get("name") or ""),
            str(recall_highlight_image_name(entry) or ""),
            json.dumps(entry.get("highlight_boxes") or [], sort_keys=True)[:8192],
        ))

    def _queue_thumbnail(
        self, generation: int, row: int, key: str, entry: dict
    ) -> None:
        record = str(entry.get("name") or "")
        window = entry.get("matched_window")
        image_name = str(window.get("image") or "") if isinstance(window, dict) else ""
        entry_copy = dict(entry)
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry() if screen is not None else None
        geometry = (
            [screen_geometry.x(), screen_geometry.y(), screen_geometry.width(), screen_geometry.height()]
            if screen_geometry is not None else []
        )

        def worker() -> None:
            data = self.controller.recall_store.preview_bytes(
                record, image_name=image_name
            ) if image_name else None
            exact = bool(data and image_name)
            if not data:
                data = self.controller.recall_store.preview_bytes(record)
            image = QImage()
            if data:
                image.loadFromData(data)
            if not image.isNull() and not exact:
                window_geometry = window.get("geometry", []) if isinstance(window, dict) else []
                if len(window_geometry) == 4 and len(geometry) == 4:
                    try:
                        scale_x = image.width() / max(1, geometry[2])
                        scale_y = image.height() / max(1, geometry[3])
                        x = round((float(window_geometry[0]) - geometry[0]) * scale_x)
                        y = round((float(window_geometry[1]) - geometry[1]) * scale_y)
                        width = round(float(window_geometry[2]) * scale_x)
                        height = round(float(window_geometry[3]) * scale_y)
                        x = max(0, min(x, image.width() - 1))
                        y = max(0, min(y, image.height() - 1))
                        width = max(1, min(width, image.width() - x))
                        height = max(1, min(height, image.height() - y))
                        image = image.copy(x, y, width, height)
                    except (TypeError, ValueError):
                        pass
            if not image.isNull():
                image = highlight_recall_pixmap(
                    image, entry_copy.get("highlight_boxes", [])
                ).scaled(
                    240, 135, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._search_bridge.thumbnail.emit(generation, row, key, image)

        self._thumbnail_executor.submit(worker)

    def _finish_thumbnail(
        self, generation: int, row: int, key: str, image: object
    ) -> None:
        if not isinstance(image, QImage) or image.isNull():
            return
        self._thumbnail_cache[key] = image
        self._thumbnail_cache.move_to_end(key)
        while len(self._thumbnail_cache) > 128:
            self._thumbnail_cache.popitem(last=False)
        if generation == self._search_generation and 0 <= row < self.results.count():
            self.results.item(row).setIcon(QIcon(QPixmap.fromImage(image)))

    def load_more_results(self) -> None:
        self._visible_count = min(len(self._all_entries), self._visible_count + 24)
        self._render_entries()

    def select_timeline_position(self, position: int) -> None:
        if self.results.count():
            self.results.setCurrentRow(max(0, min(self.results.count() - 1, position)))

    def selected_record(self) -> str:
        item = self.results.currentItem()
        entry = item.data(Qt.UserRole) if item else {}
        return str(entry.get("name") or "") if isinstance(entry, dict) else ""

    def bookmark_selected(self) -> None:
        record = self.selected_record()
        if record:
            entry = self._detail_entry
            current = bool(dict(entry.get("annotations") or {}).get("bookmarked"))
            self.controller.annotate_recall(record, bookmarked=not current)
            self.refresh()

    def annotate_selected(self) -> None:
        record = self.selected_record()
        if not record:
            return
        existing = dict(self._detail_entry.get("annotations") or {})
        collection, ok = QInputDialog.getText(
            self, "Recall collection", "Collection:", text=str(existing.get("collection") or "")
        )
        if not ok:
            return
        note, ok = QInputDialog.getMultiLineText(
            self, "Recall note", "Private local note:", str(existing.get("note") or "")
        )
        if ok:
            self.controller.annotate_recall(record, collection=collection, note=note)
            self.refresh()

    def reindex_selected(self) -> None:
        record = self.selected_record()
        if not record:
            return
        try:
            result = self.controller.reindex_recall(record)
            QMessageBox.information(self, "OCR reindex complete", json.dumps(result, indent=2))
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, "OCR reindex failed", str(error))

    def show_ocr_diagnostics(self) -> None:
        record = self.selected_record()
        if record:
            QMessageBox.information(
                self, "OCR diagnostics",
                json.dumps(self.controller.recall_ocr_diagnostics(record), indent=2),
            )

    def ask_history(self) -> None:
        question = self.query.text().strip()
        if not question:
            question, ok = QInputDialog.getText(self, "Ask local history", "Question:")
            if not ok:
                return
        answer = self.controller.ask_recall(question)
        citations = "\n".join(
            f"• {item.get('captured_at', '')} · {item.get('application', '')} · {item.get('title', '')}"
            for item in answer.get("citations", [])
        )
        QMessageBox.information(
            self, "Local history answer", f"{answer.get('answer', '')}\n\nEvidence:\n{citations}",
        )

    def change_view_mode_without_refresh(self) -> None:
        mode = str(self.view_mode.currentData() or "visual")
        self.results.setViewMode(
            QListView.ViewMode.IconMode if mode == "visual" else QListView.ViewMode.ListMode
        )
        self.results.setIconSize(QSize(240, 135) if mode == "visual" else QSize(96, 54))

    def show_selected(self, current, _previous=None) -> None:
        entry = current.data(Qt.UserRole) if current else {}
        self._detail_entry = entry if isinstance(entry, dict) else {}
        apps = ", ".join(self._detail_entry.get("apps", [])[:4]) or "Unknown application"
        titles = " · ".join(self._detail_entry.get("titles", [])[:2])
        self.detail_title.setText(f"<h2>{titles or apps}</h2>")
        diagnostics = self._detail_entry.get("capture_diagnostics", {})
        captured = int(diagnostics.get("captured_window_images", 0) or 0)
        expected = int(diagnostics.get("eligible_windows", diagnostics.get("expected_windows", 0)) or 0)
        completeness = f" · {captured}/{expected} window images" if expected else ""
        self.detail_meta.setText(
            f"{apps} · {self._detail_entry.get('captured_at', '')} · "
            f"{self._detail_entry.get('match_type', 'Saved moment')}{completeness}"
        )
        self._detail_images = recall_entry_images(self._detail_entry)
        self.filmstrip.blockSignals(True)
        self.filmstrip.clear()
        for index, (image_name, label) in enumerate(self._detail_images):
            item = QListWidgetItem(label[:28])
            # Keep the filmstrip responsive for records with many windows.
            # Remaining full images are decrypted only when selected.
            if index < 12:
                data = self.controller.recall_store.preview_bytes(
                    str(self._detail_entry.get("name", "")), image_name=image_name
                )
                thumbnail = QPixmap()
                if data:
                    thumbnail.loadFromData(data)
                if not thumbnail.isNull():
                    item.setIcon(QIcon(thumbnail.scaled(
                        128, 72, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )))
            self.filmstrip.addItem(item)
        self.filmstrip.blockSignals(False)
        if self._detail_images:
            highlighted_image = recall_highlight_image_name(self._detail_entry)
            preferred = next(
                (
                    index for index, (image_name, _label) in enumerate(self._detail_images)
                    if image_name == highlighted_image
                ),
                0,
            )
            self.filmstrip.setCurrentRow(preferred)
            self.set_image(preferred)
        else:
            self._detail_pixmap = QPixmap()
            self.preview.clear()
            self.preview.setText(
                "Screenshot capture was disabled, excluded by privacy policy, or unavailable."
            )
            self.preview_state.setText("Metadata captured · no visual preview")

    def set_image(self, position: int) -> None:
        if not 0 <= position < len(self._detail_images):
            return
        self._detail_position = position
        image_name, label = self._detail_images[position]
        data = self.controller.recall_store.preview_bytes(
            str(self._detail_entry.get("name", "")), image_name=image_name
        )
        pixmap = QPixmap()
        if data:
            pixmap.loadFromData(data)
        highlighted_image = recall_highlight_image_name(self._detail_entry)
        boxes = (
            self._detail_entry.get("highlight_boxes", [])
            if highlighted_image is not None and image_name == highlighted_image
            else []
        )
        self._detail_source_pixmap = pixmap
        self._detail_pixmap = highlight_recall_pixmap(pixmap, boxes, 0)
        self._match_position = 0
        self.match_counter.setText(
            f"Match 1 of {len(boxes)}" if boxes else "No OCR match"
        )
        self.preview_state.setText(
            f"{position + 1} of {len(self._detail_images)} · {label} · "
            f"{'Exact application-window screenshot' if image_name else 'Display overview'}"
        )
        self.apply_zoom()

    def step_image(self, delta: int) -> None:
        if self._detail_images:
            self.filmstrip.setCurrentRow(
                (self._detail_position + delta) % len(self._detail_images)
            )

    def step_match(self, delta: int) -> None:
        image_name = self._detail_images[self._detail_position][0]
        boxes = (
            self._detail_entry.get("highlight_boxes", [])
            if image_name == recall_highlight_image_name(self._detail_entry)
            else []
        )
        if not boxes:
            return
        self._match_position = (self._match_position + delta) % len(boxes)
        self._detail_pixmap = highlight_recall_pixmap(
            self._detail_source_pixmap, boxes, self._match_position
        )
        self.apply_zoom()
        self.match_counter.setText(f"Match {self._match_position + 1} of {len(boxes)}")
        box = boxes[self._match_position]
        self.set_zoom(max(1.6, self._zoom))
        horizontal = self.preview_scroll.horizontalScrollBar()
        vertical = self.preview_scroll.verticalScrollBar()
        horizontal.setValue(round(float(box.get("x", 0)) * horizontal.maximum() / 10000))
        vertical.setValue(round(float(box.get("y", 0)) * vertical.maximum() / 10000))

    def effective_zoom(self) -> float:
        if self._zoom > 0 or self._detail_pixmap.isNull():
            return self._zoom or 1.0
        viewport = self.preview_scroll.viewport().size()
        return min(
            max(1, viewport.width() - 8) / self._detail_pixmap.width(),
            max(1, viewport.height() - 8) / self._detail_pixmap.height(),
            1.0,
        )

    def scroll_center(self) -> tuple[float, float]:
        def center(scrollbar) -> float:
            extent = max(1, scrollbar.maximum() + scrollbar.pageStep())
            return max(
                0.0,
                min(1.0, (scrollbar.value() + scrollbar.pageStep() / 2) / extent),
            )

        return (
            center(self.preview_scroll.horizontalScrollBar()),
            center(self.preview_scroll.verticalScrollBar()),
        )

    def restore_scroll_center(self, anchor: tuple[float, float]) -> None:
        for ratio, scrollbar in zip(
            anchor,
            (
                self.preview_scroll.horizontalScrollBar(),
                self.preview_scroll.verticalScrollBar(),
            ),
        ):
            extent = scrollbar.maximum() + scrollbar.pageStep()
            scrollbar.setValue(round(ratio * extent - scrollbar.pageStep() / 2))

    def set_zoom(self, value: float) -> None:
        anchor = self.scroll_center()
        self._zoom = 0.0 if value <= 0 else max(0.25, min(4.0, value))
        self.apply_zoom(anchor)

    def apply_zoom(self, anchor: tuple[float, float] | None = None) -> None:
        if self._detail_pixmap.isNull():
            self.preview.clear()
            self.preview.setText("Screenshot unavailable")
            return
        if self._zoom <= 0:
            viewport = self.preview_scroll.viewport().size()
            rendered = self._detail_pixmap.scaled(
                max(1, viewport.width() - 8), max(1, viewport.height() - 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            rendered = self._detail_pixmap.scaled(
                round(self._detail_pixmap.width() * self._zoom),
                round(self._detail_pixmap.height() * self._zoom),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.preview.setPixmap(rendered)
        self.preview.resize(rendered.size())
        if anchor is not None:
            QTimer.singleShot(0, lambda: self.restore_scroll_center(anchor))

    def zoom_by_factor(self, factor: float) -> None:
        self.set_zoom(self.effective_zoom() * max(0.5, min(2.0, factor)))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.preview_scroll.viewport():
            if event.type() == QEvent.Type.Gesture:
                pinch = event.gesture(Qt.GestureType.PinchGesture)
                if pinch is not None:
                    if pinch.state() == Qt.GestureState.GestureStarted:
                        self._pinch_start_zoom = self.effective_zoom()
                    self.set_zoom(
                        self._pinch_start_zoom * float(pinch.totalScaleFactor())
                    )
                    event.accept()
                    return True
            if event.type() == QEvent.Type.NativeGesture:
                if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                    self.zoom_by_factor(1.0 + float(event.value()))
                    event.accept()
                    return True
            if (
                event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                delta = event.pixelDelta().y() or event.angleDelta().y()
                if delta:
                    self.zoom_by_factor(1.12 if delta > 0 else 1 / 1.12)
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def open_selected(self, *_args) -> None:
        item = self.results.currentItem()
        entry = item.data(Qt.UserRole) if item else {}
        target = next(iter(entry.get("targets", [])), "") if isinstance(entry, dict) else ""
        if target:
            QDesktopServices.openUrl(QUrl(target))


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
    capsules = QAction("Set up Workspace Capsules…", menu)
    capsules.triggered.connect(window.show_capsules)
    pause_menu = QMenu("Pause Recall", menu)
    for label, seconds in (("Resume", 0), ("15 minutes", 900), ("1 hour", 3600), ("Indefinitely", -1)):
        action = QAction(label, pause_menu)
        action.triggered.connect(lambda _checked=False, value=seconds: window.pause_recall(value))
        pause_menu.addAction(action)

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
    menu.addActions([show, save, restore, recall, search_recall, capsules])
    menu.addMenu(pause_menu)
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
