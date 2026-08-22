#!/usr/bin/python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import hashlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock


target = pathlib.Path(sys.argv[1])
executable = target if target.is_file() else target / "app" / "sessionsifu"
loader = importlib.machinery.SourceFileLoader("sessionsifu_settings_test", str(executable))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

settings = module.settings()
assert settings.get_boolean("show-indicator") is True
assert settings.get_int("autostart-delay") >= 0
assert settings.get_boolean("continuous-save-enabled") is True
assert settings.get_int("continuous-save-interval") == 300
assert settings.get_boolean("recall-enabled") is False
assert settings.get_int("recall-interval") == 300
assert settings.get_int("recall-retention-hours") == 24
assert settings.get_boolean("recall-include-file-paths") is False
assert "SessionSifu" in settings.get_strv("recall-excluded-apps")
assert settings.get_boolean("recall-search-shortcut-enabled") is True
assert settings.get_strv("recall-search-shortcut") == ["<Control><Alt>space"]
settings.set_strv("recall-search-shortcut", ["<Control><Shift>r"])
assert settings.get_strv("recall-search-shortcut") == ["<Control><Shift>r"]
settings.set_strv("recall-search-shortcut", ["<Control><Alt>space"])
settings.set_int("continuous-save-interval", 30)
assert settings.get_int("continuous-save-interval") == 30
settings.set_int("continuous-save-interval", 300)

manifest = module.parse_update_manifest(
    json.dumps(
        {
            "version": "2.2.0",
            "package_url": "https://raw.githubusercontent.com/tpluharik/SessionSifu/main/updates/sessionsifu_2.2.0_all.deb",
            "sha256": "a" * 64,
            "size": 12345,
            "notes": "Test update",
        }
    )
)
assert manifest["version"] == "2.2.0"
assert manifest["size"] == 12345


class FakeResponse:
    def __init__(self, contents: bytes, url: str):
        self._stream = io.BytesIO(contents)
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url


payload = b"a test Debian package payload"
download_manifest = {
    **manifest,
    "sha256": hashlib.sha256(payload).hexdigest(),
    "size": len(payload),
}
with tempfile.TemporaryDirectory() as cache_dir:
    response = FakeResponse(payload, download_manifest["package_url"])
    with mock.patch.object(module.urllib.request, "urlopen", return_value=response):
        with mock.patch.object(module.GLib, "get_user_cache_dir", return_value=cache_dir):
            downloaded = module.download_update(download_manifest)
    assert downloaded.read_bytes() == payload

with tempfile.TemporaryDirectory() as install_root:
    install_root = pathlib.Path(install_root)
    payload_root = install_root / "payload"
    source_app = payload_root / "usr/bin/sessionsifu"
    source_desktop = payload_root / "usr/share/applications/org.gnome.SessionSifu.desktop"
    source_autostart = payload_root / "etc/xdg/autostart/org.gnome.SessionSifu.desktop"
    source_icon = payload_root / "usr/share/icons/hicolor/scalable/apps/org.gnome.SessionSifu.svg"
    source_extension = payload_root / "usr/share/gnome-shell/extensions/sessionsifu@local"
    source_bundle = payload_root / "usr/share/sessionsifu/sessionsifu@local.shell-extension.zip"
    for path in [source_app, source_desktop, source_autostart, source_icon, source_bundle]:
        path.parent.mkdir(parents=True, exist_ok=True)
    source_extension.mkdir(parents=True)
    source_app.write_text("#!/usr/bin/python3\nprint('updated')\n")
    source_desktop.write_text("[Desktop Entry]\nType=Application\nExec=sessionsifu\n")
    source_autostart.write_text("[Desktop Entry]\nType=Application\nExec=sessionsifu --autostart\n")
    source_icon.write_text("<svg/>\n")
    source_bundle.write_bytes(b"extension bundle")
    (source_extension / "metadata.json").write_text('{"version-name":"1.2.2"}\n')

    data_dir = install_root / "data"
    config_dir = install_root / "config"
    bin_dir = install_root / "bin"
    local_app = module.install_user_payload(
        payload_root,
        user_data_dir=data_dir,
        user_config_dir=config_dir,
        user_bin_dir=bin_dir,
    )
    assert local_app == bin_dir / "sessionsifu"
    assert local_app.read_text() == source_app.read_text()
    assert local_app.stat().st_mode & 0o111
    assert f'Exec="{local_app}"' in (
        data_dir / "applications/org.gnome.SessionSifu.desktop"
    ).read_text()
    assert f'Exec="{local_app}" --autostart' in (
        config_dir / "autostart/org.gnome.SessionSifu.desktop"
    ).read_text()
    assert (
        data_dir / "gnome-shell/extensions/sessionsifu@local/metadata.json"
    ).is_file()
    assert (
        data_dir / "sessionsifu/sessionsifu@local.shell-extension.zip"
    ).read_bytes() == b"extension bundle"

try:
    module.parse_update_manifest(
        json.dumps(
            {
                "version": "2.2.0",
                "package_url": "https://example.com/sessionsifu.deb",
                "sha256": "a" * 64,
                "size": 12345,
            }
        )
    )
except ValueError:
    pass
else:
    raise AssertionError("untrusted update host was accepted")

with tempfile.NamedTemporaryFile(suffix=".shell-extension.zip") as bundle:
    module.os.environ["SESSIONSIFU_EXTENSION_BUNDLE"] = bundle.name
    installed = subprocess.CompletedProcess([], 0, "", "")
    not_discovered = subprocess.CompletedProcess([], 2, "", "does not exist")
    with mock.patch.object(module, "extension_state", return_value=("missing", "")):
        with mock.patch.object(module, "extension_needs_update", return_value=False):
            with mock.patch.object(module.subprocess, "run", side_effect=[installed, not_discovered]) as run:
                ok, message = module.enable_extension()
    assert ok is True
    assert message == "Extension installed. Log out and back in once to start it."
    assert module.extension_scheduled() is True
    assert run.call_args_list[0].args[0][0:3] == [
        "gnome-extensions", "install", "--force"
    ]
    assert run.call_args_list[1].args[0] == [
        "gnome-extensions", "enable", "sessionsifu@local"
    ]

print("settings schema lookup test passed")
