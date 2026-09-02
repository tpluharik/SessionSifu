#!/usr/bin/python3
from __future__ import annotations

import json
import hashlib
import pathlib
import re
import sys
import xml.etree.ElementTree as ET


root = pathlib.Path(sys.argv[1])
extension = root / "extension" / "sessionsifu@local"

ocr_files = {
    "ces.traineddata": "934bcaf97ef3348413263331131c9fa7f55f30db333c711929c124fb635f7e1b",
    "eng.traineddata": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "configs/tsv": "59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
}
for relative, expected_sha256 in ocr_files.items():
    model = root / "ocr" / "tessdata" / relative
    assert model.is_file() and not model.is_symlink()
    assert hashlib.sha256(model.read_bytes()).hexdigest() == expected_sha256
assert (root / "ocr/tessdata/ces.traineddata").stat().st_size > 1_000_000
assert (root / "ocr/tessdata/eng.traineddata").stat().st_size > 1_000_000
assert "87416418657359cb625c412a48b6e1d6d41c29bd" in (
    root / "ocr/README.md"
).read_text()

app_icon = root / "app" / "org.gnome.SessionSifu.svg"
project_logo = root / "branding" / "sessionsifu-logo.svg"
symbolic_icon = extension / "icons" / "sessionsifu-symbolic.svg"
for artwork in (app_icon, project_logo, symbolic_icon):
    assert artwork.is_file()
    assert ET.parse(artwork).getroot().tag.endswith("svg")
symbolic_source = symbolic_icon.read_text()
assert "<mask" not in symbolic_source
assert "fill-rule=\"evenodd\"" in symbolic_source
assert (root / "branding" / "sessionsifu-yinyang-concept.png").read_bytes().startswith(
    b"\x89PNG\r\n\x1a\n"
)
assert (root / "branding" / "sessionsifu-app-icon.png").read_bytes().startswith(
    b"\x89PNG\r\n\x1a\n"
)

metadata = json.loads((extension / "metadata.json").read_text())
assert metadata["uuid"] == "sessionsifu@local"
assert metadata["shell-version"] == ["50"]
assert metadata["settings-schema"] == "org.gnome.shell.extensions.sessionsifu"
assert metadata["version-name"] == "3.5.14"
assert metadata["version"] == 49
autostart_source = (extension / "ui" / "autostart.js").read_text()
file_utils_source = (extension / "utils" / "fileUtils.js").read_text()
assert "extensionObject.metadata['version-name']" in file_utils_source
assert "SessionSifu ${FileUtils.current_extension_version} is ready" in autostart_source
assert "SessionSifu 3.5.5 is ready" not in autostart_source

schema = ET.parse(extension / "schemas" / "org.gnome.shell.extensions.sessionsifu.gschema.xml")
schema_node = schema.find("schema")
assert schema_node is not None
assert schema_node.attrib["id"] == metadata["settings-schema"]
schema_keys = {key.attrib["name"]: key for key in schema_node.findall("key")}
assert schema_keys["continuous-save-enabled"].findtext("default") == "true"
assert schema_keys["continuous-save-interval"].findtext("default") == "300"
assert schema_keys["continuous-save-interval"].find("range").attrib == {
    "min": "30",
    "max": "3600",
}
assert schema_keys["recall-enabled"].findtext("default") == "false"
assert schema_keys["recall-interval"].findtext("default") == "300"
assert schema_keys["recall-retention-hours"].findtext("default") == "24"
assert schema_keys["recall-include-file-paths"].findtext("default") == "false"
assert schema_keys["recall-capture-screenshots"].findtext("default") == "false"
assert schema_keys["recall-preview-quality"].findtext("default") == "'storage'"
assert schema_keys["recall-search-view-mode"].findtext("default") == "'visual'"
assert schema_keys["recall-ocr-enabled"].findtext("default") == "false"
assert schema_keys["recall-semantic-search-enabled"].findtext("default") == "false"
assert schema_keys["recall-sensitive-filter"].findtext("default") == "true"
assert schema_keys["recall-storage-quota-mb"].findtext("default") == "512"
assert schema_keys["recall-search-shortcut-enabled"].findtext("default") == "true"
assert "Control" in schema_keys["recall-search-shortcut"].findtext("default")

build_script = (root / "packaging" / "build-deb.sh").read_text()
assert 'mkdir -p "$stage/usr/share/glib-2.0/schemas"' in build_script
assert "org.gnome.shell.extensions.sessionsifu.gschema.xml" in build_script
assert "sessionsifu@local.shell-extension.zip" in build_script
assert "org.gnome.SessionSifu.svg" in build_script
assert '"$updates_dir/latest.json"' in build_script
assert 'version="3.5.14"' in build_script
package_control = (root / "packaging" / "control").read_text()
assert "python3-pyatspi" in package_control
assert "gnome-settings-daemon-common" in package_control
assert "gnome-shell-extension-manager | gnome-shell-extension-prefs" in package_control
package_depends = next(
    line for line in package_control.splitlines() if line.startswith("Depends:")
)
assert "gnome-shell" not in package_depends
assert "Recommends: gnome-shell," in package_control
debian_control = (root / "debian" / "control").read_text()
build_control, binary_control = debian_control.split("Package: sessionsifu", 1)
assert "gnome-shell-extension-manager" not in build_control
assert "gnome-shell (>= 50)" not in build_control
assert "gnome-settings-daemon-common" in build_control
assert "gnome-shell-extension-manager | gnome-shell-extension-prefs" in binary_control
assert "test_user_update_package.py" in build_script
assert "docs/TROUBLESHOOTING.md" in build_script
assert "docs/COMPETITIVE_ANALYSIS.md" in build_script
assert "CHANGELOG.md" in build_script
assert "tests/open-files-smoke.js" in build_script
assert "tests/runtime-safety-smoke.js" in build_script
assert "tests/window-safety-smoke.js" in build_script
assert "tests/restore-safety-smoke.js" in build_script
assert "tests/security-smoke.js" in build_script
assert "tests/recall-activity-smoke.js" in build_script
assert "tests/recall-privacy-smoke.js" in build_script
assert "tests/test_portable.py" in build_script
assert "ROADMAP.md" in build_script
assert "tests/test_docs.py" in build_script
assert 'ocr/tessdata/ces.traineddata' in build_script
assert 'ocr/tessdata/eng.traineddata' in build_script

dbus = ET.parse(
    extension
    / "dbus-interfaces"
    / "org.gnome.Shell.Extensions.SessionSifu.Control.xml"
)
interface = dbus.find("interface")
assert interface is not None
assert interface.attrib["name"] == "org.gnome.Shell.Extensions.SessionSifu.Control"
methods = {method.attrib["name"] for method in interface.findall("method")}
assert {
    "Ping",
    "SaveSession",
    "RestoreSession",
    "DeleteSession",
    "ListSessions",
    "ListHistory",
    "SaveHistoryNow",
    "RestoreHistory",
    "ListRecall",
    "CaptureRecallNow",
    "DeleteRecall",
} <= methods

source_text = "\n".join(path.read_text(errors="replace") for path in extension.rglob("*.js"))
assert "org.gnome.shell.extensions.another-window-session-manager" not in source_text
assert "another-window-session-manager@gmail.com" not in source_text
assert "Session Keeper" not in source_text
assert "session-keeper@local" not in source_text
assert "Meta.is_wayland_compositor" not in source_text
assert "history_limit = 5" in source_text
assert "continuous-save-interval" in source_text
assert "recall-enabled" in source_text
assert "Privacy Recall: Active" in source_text
assert "Privacy Recall: Saving…" in source_text
assert "media-record-symbolic" in source_text
assert "recallActivity.begin()" in source_text
assert "get_boolean('show-indicator') ||" in source_text
assert "saveRecallAsync" in source_text
assert "listRecall(\n                query, this._settings.get_strv('recall-excluded-apps')" in source_text
assert "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding" in source_text
assert "sessionsifu-recall/" in source_text
assert "changed::recall-search-shortcut'" in source_text
assert "new Shell.Screenshot" in source_text
assert "screenshot.screenshot(false, stream" in source_text
assert "recall_displays" in source_text
assert "-display-${index}.jpg" in source_text
assert "--compress-recall-preview" in source_text
assert "--window-only" in source_text
assert "windowOnly" in source_text
assert "Skipped Recall screenshots because the session is locked" in source_text
assert "excluded app is visible" not in source_text
assert "result.matches" in source_text
assert "_excludedApplicationVisible" in source_text
assert "screenshotBlockingExclusions" in source_text
assert "screenshotCaptureMode" in source_text
assert "PRUNE_INTERVAL_US" in source_text
assert "_screenshotSaving" in source_text
assert "--recall-search" in source_text
assert "GLib.chmod(path, 0o600)" in source_text
assert "sessionsifu-symbolic.svg" in source_text
assert "(?:-\\d{3})?" in source_text
assert "iso.slice(20, 23)" in source_text

app_source = (root / "app" / "sessionsifu").read_text()
assert 'CURRENT_VERSION = "3.5.14"' in app_source
assert 'if _module_path in sys.path:' in app_source
assert 'sys.path.remove(_module_path)' in app_source
assert 'sys.path.insert(0, _module_path)' in app_source
assert 'self.settings.value("recall_enabled", False, type=bool)' in (
    root / "portable" / "sessionsifu_portable" / "ui.py"
).read_text()
assert "class RecallSearchWindow" in app_source
assert ".get_n_items()" not in app_source
assert "model.iter_n_children(None)" in app_source
assert "Gtk.FlowBox" in app_source
assert "GLib.timeout_add(250, self._run_scheduled_search)" in app_source
assert "max_children_per_line=1" in app_source
assert 'Gtk.MenuButton(label="More")' in app_source
assert 'Gtk.Scale.new_with_range' not in app_source
assert "def _window_pixbuf" in app_source
assert "def recall_window_image_indices" in app_source
assert "def recall_image_indices" in app_source
assert "def recall_highlight_image_index" in app_source
assert "def recall_capture_summary" in app_source
assert 'title="Recall Window Gallery"' in app_source
assert 'Gtk.Button(label="Previous")' in app_source
assert 'Gtk.Button(label="Next")' in app_source
assert "RestoreSessionSelection" in app_source
assert '"--local-api-stdio"' in app_source
assert '"matched_window"' in (root / "app" / "recall_engine.py").read_text()
assert "recall_windows" in (root / "app" / "recall_engine.py").read_text()
recall_engine_source = (root / "app" / "recall_engine.py").read_text()
assert '"preserve_interword_spaces=1", "tsv"' in recall_engine_source
assert "def _prepare_ocr_image" in recall_engine_source
assert '"--dpi", "180"' in recall_engine_source
assert '"ocr_boxes": ocr_boxes' in recall_engine_source
assert '"highlight_boxes": self._matching_ocr_boxes(window, needle)' in recall_engine_source
assert "MIN_OCR_CONFIDENCE = 30.0" in recall_engine_source
assert '"--tessdata-dir", str(bundled), "-l", "ces+eng"' in recall_engine_source
assert "def _draw_ocr_highlights" in app_source
assert "def _highlighted_picture" in app_source
assert "highlight_layer.queue_draw()" in app_source
assert "recall_screenshot_path" in app_source
assert "def compress_recall_preview" in app_source
assert "def _accessible_text_for_windows" in recall_engine_source
assert 'window.get("recall_pid")' in recall_engine_source
recorder_source = (
    root / "extension" / "sessionsifu@local" / "recallRecorder.js"
).read_text()
assert "function _stableWindowKey(value)" in recorder_source
assert "function _metaWindowForActor(actor)" in recorder_source
assert "actor.get_meta_window?.()" in recorder_source
assert "const metaWindow = _metaWindowForActor(actor);" in recorder_source
assert "const window = _metaWindowForActor(actor);" in recorder_source
assert "windowIndexes.get(windowId)" in recorder_source
assert "MetaWindowUtils.getStableWindowId(metaWindow));" in recorder_source
assert (
    "windowIndexes.get(MetaWindowUtils.getStableWindowId(metaWindow))"
    not in recorder_source
)
assert "Prepared ${windowCapture.available} of ${windowCapture.expected}" in recorder_source
assert "${windowCapture.cached} from workspace cache" in recorder_source
assert 'if not bool(match.get("focused", False)):' in app_source
assert '"storage": (960, 68)' in app_source
assert '"readable": (1440, 74)' in app_source
assert '"high": (1920, 80)' in app_source
assert "class RecallSearchWindow" in app_source
assert "self.detail_filmstrip" in app_source
assert 'Gtk.ToggleButton(label="Visual")' in app_source
assert 'Gtk.ToggleButton(label="Compact")' in app_source
assert 'for label, zoom in (("Fit", 0.0), ("100%", 1.0), ("Zoom to match", 1.6))' in app_source
assert "def _center_match" in app_source
assert "Gtk.GestureZoom" in app_source
assert "Gtk.EventControllerScroll" in app_source
assert "def _touchpad_scroll" in app_source
assert "def _restore_scroll_center" in app_source
assert "paint_to_content(null)" not in recorder_source
assert "screenshot.screenshot_area(" in recorder_source
assert "source.screenshot_area_finish(result)" in recorder_source
assert "MAX_WINDOW_CAPTURES_PER_PASS = 24" in recorder_source
assert "WINDOW_CAPTURE_BUDGET_US" in recorder_source
assert "await _yieldToShell()" in recorder_source
assert "_captureWindowActors(name, exclusions, shouldContinue)" in source_text
assert "WorkspaceCache.restorePreview(" in recorder_source
assert "WorkspaceCache.storePreview(" in recorder_source
assert "active-workspace-changed" in recorder_source
assert "notify::focus-window" in recorder_source
assert "await this._workspaceCachePromise" in recorder_source
assert "isWindowRegionUnobscured(metaWindow, stack)" in recorder_source
assert "recall_preview_captured_at" in recorder_source
assert "tests/recall-workspace-cache-smoke.js" in build_script
assert "_windowMatchesExclusions(metaWindow, exclusions, tracker)" in source_text
assert "sync_gnome_recall_shortcut" in app_source
assert "def live_extension_current" in app_source
assert "def reload_extension" in app_source
assert '["gnome-extensions", "disable", UUID]' in app_source
assert '"Reload Integration" if live and not integration_current' in app_source
assert "if not live_extension_current():" in app_source
indicator_source = (extension / "indicator.js").read_text()
assert "!this._windowSettleWaits || !mayRestoreApplications()" in indicator_source
assert "this._windowSettleWaits?.delete(metaWindow)" in indicator_source
assert "this._moveSession?.cancelWindow(metaWindow)" in indicator_source
assert "reloadGeneration !== this._sessionReloadGeneration" in indicator_source
save_source = (extension / "saveSession.js").read_text()
assert "compact ? 0 : 4" in save_source
assert "replace_contents_bytes_async" in save_source
assert "this._saveSessionIdleId" not in save_source
assert "sessionConfig.n_workspace = global.workspace_manager.n_workspaces;" in save_source.split("async _buildSession", 1)[1]
open_files_source = (extension / "openFiles.js").read_text()
assert "OPEN_FD_SCAN_LIMIT = 128" in open_files_source
assert "RECENT_FILE_SCAN_LIMIT = 512" in open_files_source
assert "isReadableRegularFile(target)" not in open_files_source
portable_ui = (root / "portable" / "sessionsifu_portable" / "ui.py").read_text()
assert "class RecallSearchDialog" in portable_ui
assert "QSplitter" in portable_ui
assert "self.filmstrip" in portable_ui
assert "Qt.GestureType.PinchGesture" in portable_ui
assert "QEvent.Type.NativeGesture" in portable_ui
assert "QEvent.Type.Wheel" in portable_ui
assert "def eventFilter" in portable_ui
assert "def restore_scroll_center" in portable_ui
assert '"Storage saver · 960 px"' in portable_ui
assert "class RecallSearchDialog" in portable_ui
assert "def recall_result_pixmap" in portable_ui
assert "def recall_highlight_image_name" in portable_ui
assert "sessionsifu-recall-search" in portable_ui
assert "Load 24 more results" in portable_ui
assert "self._all_entries[:self._visible_count]" in portable_ui
assert "RecallHotkey" in portable_ui
assert "def recall_saving_icon" in portable_ui
assert "Saving Privacy Recall…" in portable_ui
assert 'QAction("Set up Workspace Capsules…"' in portable_ui
assert "def show_capsules" in portable_ui
assert "def refresh_running_capsules" in portable_ui
assert (root / "portable" / "sessionsifu_portable" / "hotkey.py").is_file()
assert (root / "portable" / "sessionsifu_portable" / "shortcut.py").is_file()
hotkey_source = (root / "portable" / "sessionsifu_portable" / "hotkey.py").read_text()
for platform_api in (
    "RegisterHotKey",
    "addGlobalMonitorForEventsMatchingMask_handler_",
    "org.freedesktop.portal.GlobalShortcuts",
):
    assert platform_api in hotkey_source
extension_entry = (extension / "extension.js").read_text()
assert "this._settings.get_strv('recall-search-shortcut')" in extension_entry
assert "!this._settings.get_boolean('recall-enabled') ||" not in extension_entry
assert "self.snapshot_intervals = [30, 60, 300, 600, 900, 1800]" in app_source
assert "raw.githubusercontent.com/tpluharik/SessionSifu" in app_source
assert "Downloaded update failed SHA-256 verification" in app_source
assert "Update manifest signature verification failed" in app_source
assert "UPDATE_SIGNING_PUBLIC_KEY" in app_source
assert "harden_local_storage()" in app_source
assert "install_user_payload" in app_source
assert "missing_user_payload_modules" in app_source
assert "Download & Repair" in app_source
assert 'for name in (' in app_source
for support_module in (
    "recall_engine.py", "semantic.py", "restore_journal.py", "mcp.py", "capsule.py"
):
    assert f'"{support_module}"' in app_source
assert 'installed_app_dir / name' in app_source
assert '["dpkg-deb", "--extract"' in app_source
assert "launch_default_for_uri" in app_source
assert "RecallVault" in app_source
assert "from recall_engine import RecallPolicy, RecallVault, RestoreJournal" in app_source
assert "from restore_journal import RestoreJournal" not in app_source
assert (root / "app" / "recall_engine.py").is_file()
assert (root / "docs" / "RECALL_RESEARCH.md").is_file()

assert "open_files" in source_text
assert "`/proc/${pid}/fd`" in source_text
assert "appInfo.launch(files, context)" in source_text
assert "recently-used.xbel" in source_text
assert "commandLineFiles" in source_text
assert "appInfoSupportsDocumentFiles" in source_text
assert "_launchedFilesByApp" in source_text
assert "isWindowUsable" in source_text
assert "_pendingMonitorWaits" in source_text
assert "_pendingGeometryRestores" in source_text
assert "this._moveSession?.cancelWindow(metaWindow)" in source_text
assert "w === metaWindow && num === toMonitorIndex" in source_text
move_session_source = (extension / "moveSession.js").read_text()
assert "get_work_area_for_monitor(" not in move_session_source
assert "this._moveSession.destroy()" in source_text
assert "this._restoringWindows" in source_text
assert "NEW_WINDOW_SETTLE_DELAY_MS = 750" in source_text
assert "this._windowRestoreQueue" in source_text
assert "WINDOW_RESTORE_INTERVAL_MS" in source_text
assert "MIN_RESTORE_INTERVAL_MS" in source_text
assert "MAX_PREVIOUS_SESSION_WINDOWS" in source_text
assert "deduplicatePreviousSessionEntries(sessionEntries)" in source_text
assert "AUTOMATIC_RESTORE_INTERVAL_MS" in source_text
assert "automaticRestoreGroups(entries)" in source_text
assert "last-automatic-restore-attempt" in source_text
assert "automaticRestoreAttemptAllowed" in source_text
assert "restoreCommandAllowed(cmd)" in source_text
assert "appInfo.should_show?.() === false" in source_text
assert "!await this._waitBeforeNextRestore(AUTOMATIC_RESTORE_INTERVAL_MS)" in source_text
assert "!await this._waitBeforeNextRestore(MIN_RESTORE_INTERVAL_MS)" in source_text
assert "get_work_area_current_monitor()" in source_text
assert "clampWindowGeometry" in source_text
assert "_waitForCompositor()" in source_text
assert "move_frame(true" not in source_text
assert "Main.activateWindow(metaWindow" not in source_text
assert "mayRestoreApplications" in source_text
assert "restorePreviousDelay = this._settings.get_int('restore-previous-delay') * 1000" in source_text
assert "_sessionApplicationKey" in source_text
assert "command-sha256:" in source_text
assert "session.cmd.join('\\u0000')" not in source_text
assert "[Meta.WindowType.NORMAL, Meta.WindowType.UTILITY]" in source_text
assert "GObject.signal_handler_is_connected" in source_text
assert "Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS" in source_text
assert "Turn Off SessionSifu" in source_text
assert "Set Up Workspace Capsules…" in source_text
assert "[FileUtils.getManagerExecutable(), '--capsules']" in source_text
assert "bash -c" not in source_text
assert "launch-app.sh" not in source_text
assert "new RegExp(keyword)" not in source_text
assert "spawnDirectArgv" in source_text
assert "GLib.chmod(sessionFile.get_path(), 0o600)" in source_text
assert "Refusing symbolic-link session file" in source_text
assert "['gnome-extensions', 'disable', 'sessionsifu@local']" in source_text

portable = root / "portable" / "sessionsifu_portable"
for required in (
    portable / "model.py",
    portable / "storage.py",
    portable / "controller.py",
    portable / "recall.py",
    portable / "api.py",
    portable / "content.py",
    portable / "hotkey.py",
    portable / "ui.py",
    portable / "capsule.py",
    portable / "adapters" / "windows.py",
    portable / "adapters" / "macos.py",
    portable / "adapters" / "linux.py",
    root / ".github" / "workflows" / "release.yml",
    root / "ROADMAP.md",
):
    assert required.is_file(), required

roadmap = (root / "ROADMAP.md").read_text()
assert "## Shipped foundation — 3.5.14" in roadmap
for shipped_feature in ("semantic embedding", "restore journals", "scene grouping", "collections", "JetBrains", "monitor identity", "Ask history", "MCP", "export/import"):
    assert shipped_feature in roadmap
assert "## Explicit non-goals" in roadmap
assert "Workspace capsules shipped — 3.5.6" in roadmap
assert "Windows Sandbox" in roadmap
assert (root / "docs" / "COMPETITIVE_ANALYSIS.md").is_file()

control_xml = (
    extension / "dbus-interfaces" / "org.gnome.Shell.Extensions.SessionSifu.Control.xml"
).read_text()
for method in ("PlanSession", "RestoreSessionSelection", "PlanHistory", "RestoreHistorySelection"):
    assert f'name="{method}"' in control_xml

workflow = (root / ".github" / "workflows" / "release.yml").read_text()
for runner in (
    "ubuntu-24.04", "ubuntu-26.04", "windows-2025", "macos-15", "macos-15-intel"
):
    assert runner in workflow
assert "contents: write" in workflow
assert "gh release create" in workflow
assert 'package="dist/sessionsifu_${version}_all.deb"' in workflow
assert "sessionsifu_3.5.8_all.deb" not in workflow

print("static checks passed")
