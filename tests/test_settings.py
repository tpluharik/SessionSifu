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

manifest = module.parse_update_manifest(
    json.dumps(
        {
            "version": "1.2.3",
            "package_url": "https://raw.githubusercontent.com/tpluharik/SessionSifu/main/updates/sessionsifu_1.2.3_all.deb",
            "sha256": "a" * 64,
            "size": 12345,
            "notes": "Test update",
        }
    )
)
assert manifest["version"] == "1.2.3"
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

try:
    module.parse_update_manifest(
        json.dumps(
            {
                "version": "1.2.3",
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
