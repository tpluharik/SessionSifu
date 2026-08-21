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
assert metadata["version-name"] == "1.0.1"

schema = ET.parse(extension / "schemas" / "org.gnome.shell.extensions.sessionsifu.gschema.xml")
schema_node = schema.find("schema")
assert schema_node is not None
assert schema_node.attrib["id"] == metadata["settings-schema"]

build_script = (root / "packaging" / "build-deb.sh").read_text()
assert 'mkdir -p "$stage/usr/share/glib-2.0/schemas"' in build_script
assert "org.gnome.shell.extensions.sessionsifu.gschema.xml" in build_script

dbus = ET.parse(
    extension
    / "dbus-interfaces"
    / "org.gnome.Shell.Extensions.SessionSifu.Control.xml"
)
interface = dbus.find("interface")
assert interface is not None
assert interface.attrib["name"] == "org.gnome.Shell.Extensions.SessionSifu.Control"
methods = {method.attrib["name"] for method in interface.findall("method")}
assert {"Ping", "SaveSession", "RestoreSession", "DeleteSession", "ListSessions"} <= methods

source_text = "\n".join(path.read_text(errors="replace") for path in extension.rglob("*.js"))
assert "org.gnome.shell.extensions.another-window-session-manager" not in source_text
assert "another-window-session-manager@gmail.com" not in source_text
assert "Session Keeper" not in source_text
assert "session-keeper@local" not in source_text
assert "Meta.is_wayland_compositor" not in source_text

print("static checks passed")
