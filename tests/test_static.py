#!/usr/bin/python3
from __future__ import annotations

import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET


root = pathlib.Path(sys.argv[1])
extension = root / "extension" / "sessionsifu@local"

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
assert metadata["version-name"] == "3.1.6"
assert metadata["version"] == 25

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
assert 'version="3.1.6"' in build_script
assert "test_user_update_package.py" in build_script
assert "docs/TROUBLESHOOTING.md" in build_script
assert "CHANGELOG.md" in build_script
assert "tests/open-files-smoke.js" in build_script
assert "tests/runtime-safety-smoke.js" in build_script
assert "tests/window-safety-smoke.js" in build_script
assert "tests/security-smoke.js" in build_script
assert "tests/recall-activity-smoke.js" in build_script
assert "tests/recall-privacy-smoke.js" in build_script
assert "tests/test_portable.py" in build_script
assert "ROADMAP.md" in build_script

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
assert "result.matches" in source_text
assert "_excludedApplicationVisible" in source_text
assert "screenshotBlockingExclusions" in source_text
assert "PRUNE_INTERVAL_US" in source_text
assert "_screenshotSaving" in source_text
assert "--recall-search" in source_text
assert "GLib.chmod(path, 0o600)" in source_text
assert "sessionsifu-symbolic.svg" in source_text
assert "(?:-\\d{3})?" in source_text
assert "iso.slice(20, 23)" in source_text

app_source = (root / "app" / "sessionsifu").read_text()
assert 'CURRENT_VERSION = "3.1.6"' in app_source
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
assert "def _window_pixbuf" in app_source
assert "def recall_window_image_indices" in app_source
assert "def recall_image_indices" in app_source
assert 'title="Recall Window Gallery"' in app_source
assert 'Gtk.Button(label="Previous")' in app_source
assert 'Gtk.Button(label="Next")' in app_source
assert '"matched_window"' in (root / "app" / "recall_engine.py").read_text()
assert "recall_windows" in (root / "app" / "recall_engine.py").read_text()
assert '["tesseract", str(image), "stdout", "--psm", "11"]' in (
    root / "app" / "recall_engine.py"
).read_text()
assert "recall_screenshot_path" in app_source
assert "def compress_recall_preview" in app_source
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
assert "Captured ${windowCapture.captured} of ${windowCapture.expected}" in recorder_source
assert "${windowCapture.matched} live actors matched" in recorder_source
assert 'if not bool(match.get("focused", False)):' in app_source
assert "MAX_RECALL_PREVIEW_EDGE = 1280" in app_source
assert "MAX_RECALL_WINDOW_PREVIEW_EDGE = 960" in app_source
assert 'save_preview(cropped, target, MAX_RECALL_PREVIEW_EDGE, "70")' in app_source
assert 'MAX_RECALL_WINDOW_PREVIEW_EDGE,\n                "65"' in app_source
assert "paint_to_content(null)" in source_text
assert "Shell.Screenshot.composite_to_stream" in source_text
assert "_captureWindowActors(name)" in source_text
assert "sync_gnome_recall_shortcut" in app_source
assert "def live_extension_current" in app_source
assert "def reload_extension" in app_source
assert '["gnome-extensions", "disable", UUID]' in app_source
assert '"Reload Integration" if live and not integration_current' in app_source
assert "if not live_extension_current():" in app_source
indicator_source = (extension / "indicator.js").read_text()
assert "!this._windowSettleWaits || !mayRestoreApplications()" in indicator_source
assert "this._windowSettleWaits?.delete(metaWindow)" in indicator_source
save_source = (extension / "saveSession.js").read_text()
assert "compact ? 0 : 4" in save_source
assert "replace_contents_bytes_async" in save_source
assert "this._saveSessionIdleId" not in save_source
open_files_source = (extension / "openFiles.js").read_text()
assert "OPEN_FD_SCAN_LIMIT = 128" in open_files_source
assert "RECENT_FILE_SCAN_LIMIT = 512" in open_files_source
assert "isReadableRegularFile(target)" not in open_files_source
portable_ui = (root / "portable" / "sessionsifu_portable" / "ui.py").read_text()
assert "class RecallSearchDialog" in portable_ui
assert "def recall_result_pixmap" in portable_ui
assert "RecallHotkey" in portable_ui
assert "def recall_saving_icon" in portable_ui
assert "Saving Privacy Recall…" in portable_ui
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
assert 'installed_app_dir / "recall_engine.py"' in app_source
assert '["dpkg-deb", "--extract"' in app_source
assert "launch_default_for_uri" in app_source
assert "RecallVault" in app_source
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
assert "this._moveSession.cancelWindow(metaWindow)" in source_text
assert "w === metaWindow && num === toMonitorIndex" in source_text
assert "currentMonitor < 0" in source_text
assert "this._moveSession.destroy()" in source_text
assert "this._restoringWindows" in source_text
assert "NEW_WINDOW_SETTLE_DELAY_MS = 750" in source_text
assert "mayRestoreApplications" in source_text
assert "restorePreviousDelay = this._settings.get_int('restore-previous-delay') * 1000" in source_text
assert "_sessionApplicationKey" in source_text
assert "Turn Off SessionSifu" in source_text
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
    portable / "hotkey.py",
    portable / "ui.py",
    portable / "adapters" / "windows.py",
    portable / "adapters" / "macos.py",
    portable / "adapters" / "linux.py",
    root / ".github" / "workflows" / "release.yml",
    root / "ROADMAP.md",
):
    assert required.is_file(), required

roadmap = (root / "ROADMAP.md").read_text()
assert len(re.findall(r"^## \d+\.", roadmap, re.MULTILINE)) == 11

workflow = (root / ".github" / "workflows" / "release.yml").read_text()
for runner in ("ubuntu-26.04", "windows-2025", "macos-15", "macos-15-intel"):
    assert runner in workflow
assert "contents: write" in workflow
assert "gh release create" in workflow

print("static checks passed")
