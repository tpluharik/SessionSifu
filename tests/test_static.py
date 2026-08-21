#!/usr/bin/python3
from __future__ import annotations

import json
import pathlib
import sys
import xml.etree.ElementTree as ET


root = pathlib.Path(sys.argv[1])
extension = root / "extension" / "sessionsifu@local"

metadata = json.loads((extension / "metadata.json").read_text())
assert metadata["uuid"] == "sessionsifu@local"
assert metadata["shell-version"] == ["50"]
assert metadata["settings-schema"] == "org.gnome.shell.extensions.sessionsifu"
assert metadata["version-name"] == "1.2.2"

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

build_script = (root / "packaging" / "build-deb.sh").read_text()
assert 'mkdir -p "$stage/usr/share/glib-2.0/schemas"' in build_script
assert "org.gnome.shell.extensions.sessionsifu.gschema.xml" in build_script
assert "sessionsifu@local.shell-extension.zip" in build_script
assert '"$updates_dir/latest.json"' in build_script
assert 'version="1.2.2"' in build_script
assert "docs/TROUBLESHOOTING.md" in build_script
assert "CHANGELOG.md" in build_script
assert "tests/open-files-smoke.js" in build_script
assert "tests/window-safety-smoke.js" in build_script

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
} <= methods

source_text = "\n".join(path.read_text(errors="replace") for path in extension.rglob("*.js"))
assert "org.gnome.shell.extensions.another-window-session-manager" not in source_text
assert "another-window-session-manager@gmail.com" not in source_text
assert "Session Keeper" not in source_text
assert "session-keeper@local" not in source_text
assert "Meta.is_wayland_compositor" not in source_text
assert "history_limit = 5" in source_text
assert "continuous-save-interval" in source_text

app_source = (root / "app" / "sessionsifu").read_text()
assert 'CURRENT_VERSION = "1.2.2"' in app_source
assert "self.snapshot_intervals = [30, 60, 300, 600, 900, 1800]" in app_source
assert "raw.githubusercontent.com/tpluharik/SessionSifu" in app_source
assert "Downloaded update failed SHA-256 verification" in app_source
assert "install_user_payload" in app_source
assert '["dpkg-deb", "--extract"' in app_source
assert "launch_default_for_uri" not in app_source

assert "open_files" in source_text
assert "`/proc/${pid}/fd`" in source_text
assert "appInfo.launch(files, context)" in source_text
assert "recently-used.xbel" in source_text
assert "commandLineFiles" in source_text
assert "_launchedFilesByApp" in source_text
assert "isWindowUsable" in source_text
assert "_pendingMonitorWaits" in source_text
assert "_pendingGeometryRestores" in source_text
assert "this._moveSession.cancelWindow(metaWindow)" in source_text
assert "w === metaWindow && num === toMonitorIndex" in source_text
assert "currentMonitor < 0" in source_text
assert "this._moveSession.destroy()" in source_text
assert "this._restoringWindows" in source_text
assert "Turn Off SessionSifu" in source_text
assert "['gnome-extensions', 'disable', 'sessionsifu@local']" in source_text

print("static checks passed")
